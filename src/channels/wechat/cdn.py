"""
WeChat iLink CDN — AES-128-ECB encrypt/decrypt + upload/download.

Port of @tencent-weixin/openclaw-weixin 1.0.3 CDN pipeline.
Protocol: files are AES-128-ECB encrypted (PKCS7 padding) before upload.
Download URL uses encrypt_query_param from CDN response headers.
"""
import base64
import hashlib
import logging
import math
import os
import urllib.parse
import urllib.request
import urllib.error

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

log = logging.getLogger(__name__)

CDN_BASE_URL = os.environ.get("WECHAT_CDN_BASE_URL", "https://novac2c.cdn.weixin.qq.com/c2c")
UPLOAD_MAX_RETRIES = 3


# ── AES-128-ECB ────────────────────────────────────────────────────────────

def aes_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(padded) + enc.finalize()


def aes_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    dec = cipher.decryptor()
    padded = dec.update(ciphertext) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def aes_ecb_padded_size(plaintext_size: int) -> int:
    return math.ceil((plaintext_size + 1) / 16) * 16


# ── AES Key Parsing ────────────────────────────────────────────────────────

def parse_aes_key(aes_key_b64: str) -> bytes:
    """
    Parse CDNMedia.aes_key into raw 16-byte key.

    Two encodings in the wild:
      - base64(raw 16 bytes)           → images
      - base64(hex string of 16 bytes) → file / voice / video
    """
    raw = base64.b64decode(aes_key_b64)
    if len(raw) == 16:
        return raw
    if len(raw) == 32:
        try:
            key = bytes.fromhex(raw.decode("ascii"))
            if len(key) == 16:
                return key
        except (ValueError, UnicodeDecodeError):
            pass
    raise ValueError(f"Cannot parse AES key: decoded length={len(raw)}")


# ── CDN Download ───────────────────────────────────────────────────────────

def cdn_download(encrypt_query_param: str, cdn_base_url: str = "",
                 timeout: int = 30) -> bytes:
    base = cdn_base_url or CDN_BASE_URL
    url = f"{base}/download?encrypted_query_param={urllib.parse.quote(encrypt_query_param)}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def cdn_download_and_decrypt(encrypt_query_param: str, aes_key_b64: str,
                              cdn_base_url: str = "", timeout: int = 30) -> bytes:
    ciphertext = cdn_download(encrypt_query_param, cdn_base_url, timeout)
    key = parse_aes_key(aes_key_b64)
    return aes_ecb_decrypt(ciphertext, key)


def cdn_download_plain(encrypt_query_param: str, cdn_base_url: str = "",
                       timeout: int = 30) -> bytes:
    return cdn_download(encrypt_query_param, cdn_base_url, timeout)


# ── CDN Upload ─────────────────────────────────────────────────────────────

def cdn_upload(plaintext: bytes, upload_param: str, filekey: str,
               aes_key: bytes, cdn_base_url: str = "") -> str:
    """Upload AES-encrypted buffer to CDN. Returns encrypt_query_param (download token)."""
    base = cdn_base_url or CDN_BASE_URL
    ciphertext = aes_ecb_encrypt(plaintext, aes_key)
    url = (f"{base}/upload?"
           f"encrypted_query_param={urllib.parse.quote(upload_param)}"
           f"&filekey={urllib.parse.quote(filekey)}")

    last_error = None
    for attempt in range(1, UPLOAD_MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url, data=ciphertext, method="POST",
                headers={"Content-Type": "application/octet-stream"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"CDN upload {resp.status}")
                download_param = resp.headers.get("x-encrypted-param", "")
                if not download_param:
                    raise RuntimeError("CDN response missing x-encrypted-param")
                log.debug(f"cdn: upload ok attempt={attempt} filekey={filekey[:16]}")
                return download_param
        except Exception as e:
            last_error = e
            if attempt < UPLOAD_MAX_RETRIES:
                log.warning(f"cdn: upload attempt {attempt} failed: {e}")
            else:
                log.error(f"cdn: upload all {UPLOAD_MAX_RETRIES} attempts failed: {e}")

    raise last_error or RuntimeError("CDN upload failed")


def upload_media_file(file_path: str, to_user_id: str, media_type: int,
                      bot_token: str, base_url: str,
                      cdn_base_url: str = "") -> dict:
    """
    Full upload pipeline: read file → hash → gen AES key → getUploadUrl → CDN upload.

    Args:
        media_type: 1=IMAGE, 2=VIDEO, 3=FILE, 4=VOICE (UploadMediaType enum)

    Returns:
        {filekey, download_encrypt_query_param, aes_key_hex, file_size, file_size_cipher}
    """
    from src.channels.wechat.api import get_upload_url

    with open(file_path, "rb") as f:
        plaintext = f.read()
    raw_size = len(plaintext)
    raw_md5 = hashlib.md5(plaintext).hexdigest()
    cipher_size = aes_ecb_padded_size(raw_size)

    aes_key = os.urandom(16)
    filekey = os.urandom(16).hex()

    resp = get_upload_url(
        bot_token=bot_token,
        base_url=base_url,
        filekey=filekey,
        media_type=media_type,
        to_user_id=to_user_id,
        rawsize=raw_size,
        rawfilemd5=raw_md5,
        filesize=cipher_size,
        aeskey=aes_key.hex(),
        no_need_thumb=True,
    )
    upload_param = resp.get("upload_param", "")
    if not upload_param:
        raise RuntimeError(f"getUploadUrl returned no upload_param: {resp}")

    download_param = cdn_upload(plaintext, upload_param, filekey, aes_key, cdn_base_url)

    return {
        "filekey": filekey,
        "download_encrypt_query_param": download_param,
        "aes_key_hex": aes_key.hex(),
        "file_size": raw_size,
        "file_size_cipher": cipher_size,
    }
