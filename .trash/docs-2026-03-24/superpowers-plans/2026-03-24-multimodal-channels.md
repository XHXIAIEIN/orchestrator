# Multimodal Channel Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Full multimodal support for Telegram and WeChat channels — receive and send images, voice, files, video; WeChat typing indicator; WeChat CDN encrypt/decrypt pipeline.

**Architecture:** Refactor channel layer into a unified media pipeline. Inbound: parse media from platform messages → download/decrypt → pass to LLM (vision model for images). Outbound: LLM generates media intent → upload/encrypt → send via platform API. WeChat CDN uses AES-128-ECB encryption. Telegram uses native Bot API multipart uploads.

**Tech Stack:** Python 3, `cryptography` (AES-128-ECB), `urllib` (zero external HTTP deps), `ffmpeg` (SILK→WAV voice transcode), Ollama gemma3:27b (vision), Claude API (multimodal fallback).

**Spec reference:** `docs/superpowers/specs/2026-03-23-governance-refactor-design.md` (N/A — spec derived from openclaw-weixin 1.0.3 source reverse-engineering)

**Protocol reference (read-only, do not import):** `/tmp/ilink-proto/package/src/` — TypeScript source of `@tencent-weixin/openclaw-weixin` 1.0.3

---

## File Structure

### New Files
| File | Responsibility |
|---|---|
| `src/channels/media.py` | Unified media types, download/save helpers, MIME detection |
| `src/channels/wechat/cdn.py` | AES-128-ECB encrypt/decrypt + CDN upload/download |

### Modified Files
| File | Changes |
|---|---|
| `src/channels/base.py` | Add media fields to `ChannelMessage` |
| `src/channels/wechat/api.py` | Add `get_upload_url`, `send_image`, `send_file`, `send_video`, `send_voice`; enhance `extract_text` to extract all media items; add `get_config` for typing_ticket |
| `src/channels/wechat/channel.py` | Inbound media parsing, outbound media dispatch, typing indicator integration |
| `src/channels/telegram/channel.py` | Inbound media (photo/voice/document/sticker/video), outbound media methods (`sendPhoto`, `sendVoice`, `sendDocument`, `sendSticker`, `sendVideo`) |
| `src/channels/chat.py` | Multimodal message passing to LLM (images → vision route), media-aware reply_fn |
| `src/channels/config.py` | Add media config: `MEDIA_DIR`, `MEDIA_MAX_BYTES`, `CDN_BASE_URL` |
| `src/core/llm_router.py` | No changes needed (already supports `images` param) |
| `requirements.txt` | Add `cryptography>=42.0.0` |
| `Dockerfile` | No changes needed (`ffmpeg` already installed) |

---

## Task 1: Add `cryptography` dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add cryptography to requirements.txt**

```
# After PyYAML line, add:
cryptography>=42.0.0
```

- [ ] **Step 2: Install locally to verify**

Run: `pip install cryptography>=42.0.0`
Expected: installs successfully

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add cryptography for WeChat CDN AES-128-ECB"
```

---

## Task 2: Unified media types — `src/channels/media.py`

**Files:**
- Create: `src/channels/media.py`

- [ ] **Step 1: Create media.py with types and helpers**

```python
"""
Unified media types for channel layer.

Platform-agnostic media representation. Each channel adapter converts
platform-specific media to/from these types.
"""
import hashlib
import logging
import mimetypes
import os
import urllib.request
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

MEDIA_DIR = Path(os.environ.get("CHANNEL_MEDIA_DIR", "tmp/media"))
MEDIA_MAX_BYTES = int(os.environ.get("CHANNEL_MEDIA_MAX_BYTES", 50 * 1024 * 1024))


class MediaType(IntEnum):
    """Matches iLink MessageItemType."""
    TEXT = 1
    IMAGE = 2
    VOICE = 3
    FILE = 4
    VIDEO = 5


@dataclass
class MediaAttachment:
    """A single media attachment (inbound or outbound)."""
    media_type: MediaType
    local_path: str = ""          # local file path (after download/decrypt)
    mime_type: str = ""           # e.g. "image/jpeg", "audio/wav"
    file_name: str = ""           # original filename (for FILE type)
    file_size: int = 0            # bytes
    duration_ms: int = 0          # voice/video duration
    width: int = 0                # image/video width
    height: int = 0               # image/video height
    text: str = ""                # voice transcription / caption
    # Platform-specific CDN refs (WeChat only, for lazy download)
    cdn_encrypt_query_param: str = ""
    cdn_aes_key: str = ""         # base64 or hex depending on source


def ensure_media_dir(subdir: str = "inbound") -> Path:
    """Create and return media storage directory."""
    d = MEDIA_DIR / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d


def guess_mime(filename: str) -> str:
    """Guess MIME type from filename."""
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def save_media_buffer(buf: bytes, mime: str = "", subdir: str = "inbound",
                      original_filename: str = "") -> str:
    """Save a buffer to media dir, return absolute path."""
    d = ensure_media_dir(subdir)
    ext = _ext_from_mime(mime) if mime else ".bin"
    if original_filename:
        name = original_filename
    else:
        h = hashlib.md5(buf[:4096]).hexdigest()[:8]
        name = f"{h}{ext}"
    path = d / name
    path.write_bytes(buf)
    return str(path.resolve())


def download_url(url: str, subdir: str = "inbound", timeout: int = 30) -> str:
    """Download a URL to media dir, return local path."""
    d = ensure_media_dir(subdir)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        buf = resp.read(MEDIA_MAX_BYTES + 1)
        if len(buf) > MEDIA_MAX_BYTES:
            raise ValueError(f"Media too large (>{MEDIA_MAX_BYTES} bytes)")
    ext = _ext_from_mime(content_type) or _ext_from_url(url)
    h = hashlib.md5(buf[:4096]).hexdigest()[:8]
    path = d / f"{h}{ext}"
    path.write_bytes(buf)
    return str(path.resolve())


def _ext_from_mime(mime: str) -> str:
    """MIME → extension."""
    mapping = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
        "image/webp": ".webp", "audio/wav": ".wav", "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3", "audio/silk": ".silk", "video/mp4": ".mp4",
        "application/pdf": ".pdf",
    }
    for prefix, ext in mapping.items():
        if mime.startswith(prefix):
            return ext
    return ".bin"


def _ext_from_url(url: str) -> str:
    """Extract extension from URL path."""
    from urllib.parse import urlparse
    path = urlparse(url).path
    if "." in path.split("/")[-1]:
        return "." + path.split(".")[-1][:5]
    return ".bin"
```

- [ ] **Step 2: Commit**

```bash
git add src/channels/media.py
git commit -m "feat(media): add unified media types and helpers"
```

---

## Task 3: WeChat CDN layer — `src/channels/wechat/cdn.py`

**Files:**
- Create: `src/channels/wechat/cdn.py`

This is the critical piece — Python port of the TypeScript CDN encrypt/decrypt pipeline from openclaw-weixin.

- [ ] **Step 1: Create cdn.py**

```python
"""
WeChat iLink CDN — AES-128-ECB encrypt/decrypt + upload/download.

Port of @tencent-weixin/openclaw-weixin 1.0.3 CDN pipeline.
Protocol: files are AES-128-ECB encrypted (PKCS7 padding) before upload.
Download URL uses encrypt_query_param from CDN response headers.
"""
import hashlib
import logging
import math
import os
import urllib.request
import urllib.error

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

log = logging.getLogger(__name__)

CDN_BASE_URL = os.environ.get("WECHAT_CDN_BASE_URL", "https://cdn.ilinkai.weixin.qq.com")
UPLOAD_MAX_RETRIES = 3


# ── AES-128-ECB ────────────────────────────────────────────────────────────

def aes_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """AES-128-ECB with PKCS7 padding."""
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(padded) + enc.finalize()


def aes_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    """AES-128-ECB with PKCS7 unpadding."""
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    dec = cipher.decryptor()
    padded = dec.update(ciphertext) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def aes_ecb_padded_size(plaintext_size: int) -> int:
    """Compute ciphertext size (PKCS7 pads to 16-byte boundary)."""
    return math.ceil((plaintext_size + 1) / 16) * 16


# ── AES Key Parsing ────────────────────────────────────────────────────────

def parse_aes_key(aes_key_b64: str) -> bytes:
    """
    Parse CDNMedia.aes_key into raw 16-byte key.

    Two encodings in the wild:
      - base64(raw 16 bytes)           → images
      - base64(hex string of 16 bytes) → file / voice / video

    In the second case, base64-decoding yields 32 ASCII hex chars
    which must be parsed as hex to recover the 16-byte key.
    """
    import base64
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

def cdn_download_url(encrypt_query_param: str, cdn_base_url: str = "") -> str:
    """Build CDN download URL."""
    base = cdn_base_url or CDN_BASE_URL
    return f"{base}/download?encrypted_query_param={urllib.parse.quote(encrypt_query_param)}"


def cdn_download(encrypt_query_param: str, cdn_base_url: str = "",
                 timeout: int = 30) -> bytes:
    """Download raw (encrypted) bytes from CDN."""
    import urllib.parse
    url = cdn_download_url(encrypt_query_param, cdn_base_url)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def cdn_download_and_decrypt(encrypt_query_param: str, aes_key_b64: str,
                              cdn_base_url: str = "",
                              timeout: int = 30) -> bytes:
    """Download from CDN + AES-128-ECB decrypt."""
    ciphertext = cdn_download(encrypt_query_param, cdn_base_url, timeout)
    key = parse_aes_key(aes_key_b64)
    return aes_ecb_decrypt(ciphertext, key)


def cdn_download_plain(encrypt_query_param: str, cdn_base_url: str = "",
                       timeout: int = 30) -> bytes:
    """Download from CDN without decryption (some images are unencrypted)."""
    return cdn_download(encrypt_query_param, cdn_base_url, timeout)


# ── CDN Upload ─────────────────────────────────────────────────────────────

def cdn_upload(plaintext: bytes, upload_param: str, filekey: str,
               aes_key: bytes, cdn_base_url: str = "") -> str:
    """
    Upload AES-encrypted buffer to CDN.
    Returns: encrypt_query_param (download token).
    """
    import urllib.parse
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

    plaintext = open(file_path, "rb").read()
    raw_size = len(plaintext)
    raw_md5 = hashlib.md5(plaintext).hexdigest()
    cipher_size = aes_ecb_padded_size(raw_size)

    aes_key = os.urandom(16)
    filekey = os.urandom(16).hex()

    # Get presigned upload URL
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

    # Upload to CDN
    download_param = cdn_upload(
        plaintext, upload_param, filekey, aes_key, cdn_base_url
    )

    return {
        "filekey": filekey,
        "download_encrypt_query_param": download_param,
        "aes_key_hex": aes_key.hex(),
        "file_size": raw_size,
        "file_size_cipher": cipher_size,
    }
```

- [ ] **Step 2: Commit**

```bash
git add src/channels/wechat/cdn.py
git commit -m "feat(wechat): add CDN AES-128-ECB encrypt/decrypt + upload/download"
```

---

## Task 4: Expand `ChannelMessage` with media — `src/channels/base.py`

**Files:**
- Modify: `src/channels/base.py`

- [ ] **Step 1: Add media fields to ChannelMessage**

Add import and fields:

```python
from src.channels.media import MediaAttachment, MediaType  # new import

@dataclass
class ChannelMessage:
    """平台无关的消息对象。"""
    text: str
    event_type: str = ""
    priority: str = "NORMAL"
    department: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Media support
    media: list[MediaAttachment] = field(default_factory=list)
```

- [ ] **Step 2: Commit**

```bash
git add src/channels/base.py
git commit -m "feat(base): add media attachments to ChannelMessage"
```

---

## Task 5: Expand WeChat API — `src/channels/wechat/api.py`

**Files:**
- Modify: `src/channels/wechat/api.py`

- [ ] **Step 1: Add get_upload_url endpoint**

After the existing `send_typing` function, add:

```python
def get_upload_url(bot_token: str, base_url: str = DEFAULT_BASE_URL,
                   **kwargs) -> dict:
    """Get presigned CDN upload URL. kwargs: filekey, media_type, to_user_id, rawsize, rawfilemd5, filesize, aeskey, no_need_thumb."""
    body = {k: v for k, v in kwargs.items() if v is not None}
    body["base_info"] = _base_info()
    return _api_post(base_url, "ilink/bot/getuploadurl", bot_token, body, timeout=15)
```

- [ ] **Step 2: Add media message builders**

Add `send_image`, `send_file`, `send_video` functions that build proper `item_list` with the correct `MessageItemType`:

```python
# MessageItemType constants (matches iLink protocol)
ITEM_TEXT = 1
ITEM_IMAGE = 2
ITEM_VOICE = 3
ITEM_FILE = 4
ITEM_VIDEO = 5


def _send_media_message(bot_token: str, to_user_id: str, context_token: str,
                        item: dict, caption: str = "",
                        base_url: str = DEFAULT_BASE_URL) -> dict:
    """Send a media message with optional text caption."""
    import base64 as b64mod
    items = []
    if caption:
        items.append({"type": ITEM_TEXT, "text_item": {"text": caption}})
    items.append(item)

    # Send each item as separate request (iLink protocol requirement)
    result = {}
    for single_item in items:
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": _generate_client_id(),
                "message_type": 2,   # BOT
                "message_state": 2,  # FINISH
                "context_token": context_token,
                "item_list": [single_item],
            },
            "base_info": _base_info(),
        }
        result = _api_post(base_url, "ilink/bot/sendmessage", bot_token, body)
    return result


def send_image(bot_token: str, to_user_id: str, context_token: str,
               uploaded: dict, caption: str = "",
               base_url: str = DEFAULT_BASE_URL) -> dict:
    """Send image using CDN upload result."""
    import base64 as b64mod
    item = {
        "type": ITEM_IMAGE,
        "image_item": {
            "media": {
                "encrypt_query_param": uploaded["download_encrypt_query_param"],
                "aes_key": b64mod.b64encode(
                    bytes.fromhex(uploaded["aes_key_hex"])
                ).decode(),
                "encrypt_type": 1,
            },
            "mid_size": uploaded["file_size_cipher"],
        },
    }
    return _send_media_message(bot_token, to_user_id, context_token, item, caption, base_url)


def send_file(bot_token: str, to_user_id: str, context_token: str,
              uploaded: dict, file_name: str, caption: str = "",
              base_url: str = DEFAULT_BASE_URL) -> dict:
    """Send file attachment using CDN upload result."""
    import base64 as b64mod
    item = {
        "type": ITEM_FILE,
        "file_item": {
            "media": {
                "encrypt_query_param": uploaded["download_encrypt_query_param"],
                "aes_key": b64mod.b64encode(
                    bytes.fromhex(uploaded["aes_key_hex"])
                ).decode(),
                "encrypt_type": 1,
            },
            "file_name": file_name,
            "len": str(uploaded["file_size"]),
        },
    }
    return _send_media_message(bot_token, to_user_id, context_token, item, caption, base_url)


def send_video(bot_token: str, to_user_id: str, context_token: str,
               uploaded: dict, caption: str = "",
               base_url: str = DEFAULT_BASE_URL) -> dict:
    """Send video using CDN upload result."""
    import base64 as b64mod
    item = {
        "type": ITEM_VIDEO,
        "video_item": {
            "media": {
                "encrypt_query_param": uploaded["download_encrypt_query_param"],
                "aes_key": b64mod.b64encode(
                    bytes.fromhex(uploaded["aes_key_hex"])
                ).decode(),
                "encrypt_type": 1,
            },
            "video_size": uploaded["file_size_cipher"],
        },
    }
    return _send_media_message(bot_token, to_user_id, context_token, item, caption, base_url)
```

- [ ] **Step 3: Enhance extract_text to return all media items**

Add a new function `extract_media_items` that parses all item types from a message:

```python
def extract_media_items(msg: dict) -> list[dict]:
    """Extract all media items from a WeixinMessage.

    Returns list of dicts with keys:
        type: ITEM_IMAGE / ITEM_VOICE / ITEM_FILE / ITEM_VIDEO
        + type-specific fields (image_item, voice_item, file_item, video_item)
    """
    items = []
    for item in msg.get("item_list") or []:
        t = item.get("type", 0)
        if t == ITEM_IMAGE and item.get("image_item"):
            items.append(item)
        elif t == ITEM_VOICE and item.get("voice_item"):
            items.append(item)
        elif t == ITEM_FILE and item.get("file_item"):
            items.append(item)
        elif t == ITEM_VIDEO and item.get("video_item"):
            items.append(item)
    return items
```

- [ ] **Step 4: Commit**

```bash
git add src/channels/wechat/api.py
git commit -m "feat(wechat-api): add media send/receive + CDN upload URL endpoint"
```

---

## Task 6: WeChat Channel — inbound media + typing + outbound media

**Files:**
- Modify: `src/channels/wechat/channel.py`

This is the largest task. Full rewrite of the channel with media support.

- [ ] **Step 1: Add imports and typing_ticket management**

Add new imports at top:

```python
from src.channels.media import MediaAttachment, MediaType
from src.channels.wechat.api import (
    # existing imports...
    extract_media_items, get_config, send_typing,
    send_image, send_file, send_video,
    ITEM_IMAGE, ITEM_VOICE, ITEM_FILE, ITEM_VIDEO,
)
from src.channels.wechat.cdn import (
    cdn_download_and_decrypt, cdn_download_plain,
    upload_media_file, CDN_BASE_URL,
)
from src.channels.media import save_media_buffer, guess_mime
```

- [ ] **Step 2: Add typing indicator to WeChatChannel**

Add `_typing_tickets` dict and methods:

```python
class WeChatChannel(Channel):
    def __init__(self, ...):
        # ... existing init ...
        self._typing_tickets: dict[str, str] = {}  # user_id → ticket
        self._cdn_base_url = os.environ.get("WECHAT_CDN_BASE_URL", CDN_BASE_URL)

    def _fetch_typing_ticket(self, user_id: str) -> str:
        """Get typing_ticket from getconfig, cache it."""
        if user_id in self._typing_tickets:
            return self._typing_tickets[user_id]
        try:
            ctx_token = get_context_token(user_id)
            resp = get_config(self.bot_token, user_id, ctx_token or "", self.base_url)
            ticket = resp.get("typing_ticket", "")
            if ticket:
                self._typing_tickets[user_id] = ticket
            return ticket
        except Exception as e:
            log.debug(f"wechat: get typing_ticket failed: {e}")
            return ""

    def _send_typing(self, user_id: str, status: int = 1):
        """Send typing indicator. status: 1=typing, 2=cancel."""
        ticket = self._fetch_typing_ticket(user_id)
        if not ticket:
            return
        try:
            send_typing(self.bot_token, user_id, ticket, status, self.base_url)
        except Exception as e:
            log.debug(f"wechat: send_typing failed: {e}")

    def _keep_typing(self, user_id: str) -> threading.Event:
        """Keep sending typing indicator every 5s until stop event is set."""
        stop = threading.Event()
        def _loop():
            while not stop.is_set():
                self._send_typing(user_id, 1)
                stop.wait(timeout=5)
            self._send_typing(user_id, 2)  # cancel
        threading.Thread(target=_loop, name="wx-typing", daemon=True).start()
        return stop
```

- [ ] **Step 3: Rewrite _handle_message for media support**

Replace the existing `_handle_message` to parse all media types:

```python
def _handle_message(self, msg: dict):
    if msg.get("message_type") != 1:  # USER message
        return

    user_id = extract_from_user(msg)
    text = extract_text(msg).strip()
    ctx_token = msg.get("context_token", "")
    media_items = extract_media_items(msg)

    if not user_id:
        return
    if not text and not media_items:
        return
    if ctx_token:
        set_context_token(user_id, ctx_token)
    if self._allowed_users and user_id not in self._allowed_users:
        log.warning(f"wechat: rejected from unauthorized {user_id[:16]}...")
        return

    now = time.time()
    if now - self._last_msg_time.get(user_id, 0) < ch_cfg.RATE_LIMIT_WINDOW:
        return
    self._last_msg_time[user_id] = now

    # Download media attachments
    attachments = []
    for item in media_items:
        try:
            att = self._download_media_item(item)
            if att:
                attachments.append(att)
        except Exception as e:
            log.warning(f"wechat: media download failed: {e}")

    log.info(f"wechat: msg from {user_id[:16]}...: {text[:50]} media={len(attachments)}")

    if text.startswith("/"):
        chat_engine.handle_command(text, user_id, self._reply_text, "wechat")
    else:
        if len(text) > ch_cfg.LONG_MSG_THRESHOLD:
            file_path, char_count = chat_engine.save_to_inbox(text)
            preview = text[:80].replace("\n", " ")
            ref = f'[用户发送了长消息 ({char_count}字)，已保存到 {file_path}，预览: "{preview}..."]'
            self._start_chat(user_id, ref, original_text=text, media=attachments)
        else:
            self._start_chat(user_id, text, media=attachments)
```

- [ ] **Step 4: Add _download_media_item helper**

```python
def _download_media_item(self, item: dict) -> MediaAttachment | None:
    """Download and decrypt a single media item from CDN."""
    t = item.get("type", 0)

    if t == ITEM_IMAGE:
        img = item.get("image_item", {})
        media = img.get("media", {})
        eqp = media.get("encrypt_query_param", "")
        if not eqp:
            return None
        # Prefer image_item.aeskey (hex) over media.aes_key (base64)
        aes_key_b64 = img.get("aeskey")
        if aes_key_b64:
            import base64 as b64mod
            aes_key_b64 = b64mod.b64encode(bytes.fromhex(aes_key_b64)).decode()
        else:
            aes_key_b64 = media.get("aes_key", "")

        if aes_key_b64:
            buf = cdn_download_and_decrypt(eqp, aes_key_b64, self._cdn_base_url)
        else:
            buf = cdn_download_plain(eqp, self._cdn_base_url)
        path = save_media_buffer(buf, "image/jpeg", "inbound")
        return MediaAttachment(
            media_type=MediaType.IMAGE, local_path=path, mime_type="image/jpeg",
        )

    elif t == ITEM_VOICE:
        voice = item.get("voice_item", {})
        media = voice.get("media", {})
        eqp = media.get("encrypt_query_param", "")
        aes_key = media.get("aes_key", "")
        if not eqp or not aes_key:
            return None
        silk_buf = cdn_download_and_decrypt(eqp, aes_key, self._cdn_base_url)
        # Try SILK → WAV transcode via ffmpeg
        wav_buf = _silk_to_wav(silk_buf)
        if wav_buf:
            path = save_media_buffer(wav_buf, "audio/wav", "inbound")
            mime = "audio/wav"
        else:
            path = save_media_buffer(silk_buf, "audio/silk", "inbound")
            mime = "audio/silk"
        return MediaAttachment(
            media_type=MediaType.VOICE, local_path=path, mime_type=mime,
            text=voice.get("text", ""),
            duration_ms=voice.get("playtime", 0),
        )

    elif t == ITEM_FILE:
        fi = item.get("file_item", {})
        media = fi.get("media", {})
        eqp = media.get("encrypt_query_param", "")
        aes_key = media.get("aes_key", "")
        if not eqp or not aes_key:
            return None
        buf = cdn_download_and_decrypt(eqp, aes_key, self._cdn_base_url)
        fname = fi.get("file_name", "file.bin")
        path = save_media_buffer(buf, guess_mime(fname), "inbound", fname)
        return MediaAttachment(
            media_type=MediaType.FILE, local_path=path,
            mime_type=guess_mime(fname), file_name=fname,
            file_size=int(fi.get("len", 0)),
        )

    elif t == ITEM_VIDEO:
        vid = item.get("video_item", {})
        media = vid.get("media", {})
        eqp = media.get("encrypt_query_param", "")
        aes_key = media.get("aes_key", "")
        if not eqp or not aes_key:
            return None
        buf = cdn_download_and_decrypt(eqp, aes_key, self._cdn_base_url)
        path = save_media_buffer(buf, "video/mp4", "inbound")
        return MediaAttachment(
            media_type=MediaType.VIDEO, local_path=path, mime_type="video/mp4",
        )

    return None
```

- [ ] **Step 5: Add SILK → WAV helper (module-level)**

```python
def _silk_to_wav(silk_buf: bytes) -> bytes | None:
    """Transcode SILK audio to WAV using ffmpeg. Returns None on failure."""
    import subprocess
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix=".silk", delete=False) as f:
            f.write(silk_buf)
            silk_path = f.name
        wav_path = silk_path.replace(".silk", ".wav")
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
             "-i", silk_path, wav_path],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0 and os.path.exists(wav_path):
            wav_buf = open(wav_path, "rb").read()
            return wav_buf if wav_buf else None
    except Exception as e:
        log.debug(f"wechat: silk→wav failed: {e}")
    finally:
        for p in [silk_path, wav_path]:
            try:
                os.unlink(p)
            except Exception:
                pass
    return None
```

- [ ] **Step 6: Update _start_chat to pass media + typing**

```python
def _start_chat(self, user_id: str, text: str, original_text: str = "",
                media: list[MediaAttachment] | None = None):
    def _chat_with_typing():
        typing_stop = self._keep_typing(user_id)
        try:
            chat_engine.do_chat(
                user_id, text, original_text,
                self._get_system_prompt(),
                lambda cid, txt, **kw: self._reply_media(cid, txt, **kw),
                "wechat",
                media=media,
            )
        finally:
            typing_stop.set()

    threading.Thread(target=_chat_with_typing, name="wx-chat", daemon=True).start()
```

- [ ] **Step 7: Add _reply_media for outbound media**

```python
def _reply_media(self, user_id: str, text: str,
                 media_path: str = "", media_type: str = "") -> bool:
    """Reply with text and/or media."""
    ctx_token = get_context_token(user_id)
    if not ctx_token:
        log.warning(f"wechat: no context_token for {user_id[:16]}...")
        return False
    try:
        if media_path and os.path.exists(media_path):
            mime = media_type or guess_mime(media_path)
            if mime.startswith("image/"):
                upload_type = 1  # IMAGE
            elif mime.startswith("video/"):
                upload_type = 2  # VIDEO
            else:
                upload_type = 3  # FILE

            uploaded = upload_media_file(
                media_path, user_id, upload_type,
                self.bot_token, self.base_url, self._cdn_base_url,
            )
            plain = _strip_markdown(text) if text else ""
            if mime.startswith("image/"):
                send_image(self.bot_token, user_id, ctx_token, uploaded, plain, self.base_url)
            elif mime.startswith("video/"):
                send_video(self.bot_token, user_id, ctx_token, uploaded, plain, self.base_url)
            else:
                fname = os.path.basename(media_path)
                send_file(self.bot_token, user_id, ctx_token, uploaded, fname, plain, self.base_url)
            return True

        # Text only
        plain = _strip_markdown(text)
        for chunk in _split_message(plain):
            send_message(self.bot_token, user_id, chunk, ctx_token, self.base_url)
        return True
    except Exception as e:
        log.warning(f"wechat: reply failed: {e}")
        return False
```

- [ ] **Step 8: Commit**

```bash
git add src/channels/wechat/channel.py
git commit -m "feat(wechat): full multimodal - inbound media download, outbound CDN upload, typing indicator"
```

---

## Task 7: Telegram Channel — inbound + outbound multimodal

**Files:**
- Modify: `src/channels/telegram/channel.py`

- [ ] **Step 1: Add imports**

```python
import os
from src.channels.media import MediaAttachment, MediaType, save_media_buffer, download_url
```

- [ ] **Step 2: Add TG API media methods**

```python
def _tg_get_file_url(self, file_id: str) -> str:
    """Get download URL for a Telegram file."""
    resp = self._tg_api("getFile", {"file_id": file_id})
    if resp and resp.get("ok"):
        path = resp["result"]["file_path"]
        return f"https://api.telegram.org/file/bot{self.token}/{path}"
    return ""

def _tg_api(self, method: str, params: dict) -> dict:
    """Call Telegram Bot API."""
    payload = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(
        f"{self._base_url}/{method}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=ch_cfg.SEND_TIMEOUT)
        return json.loads(resp.read())
    except Exception as e:
        log.warning(f"telegram: {method} failed: {e}")
        return {}

def _send_photo(self, chat_id: str, photo_path: str, caption: str = "") -> bool:
    """Send photo via multipart upload."""
    return self._send_multipart(chat_id, "sendPhoto", "photo", photo_path, caption)

def _send_document(self, chat_id: str, doc_path: str, caption: str = "") -> bool:
    """Send document via multipart upload."""
    return self._send_multipart(chat_id, "sendDocument", "document", doc_path, caption)

def _send_voice(self, chat_id: str, voice_path: str, caption: str = "") -> bool:
    """Send voice via multipart upload."""
    return self._send_multipart(chat_id, "sendVoice", "voice", voice_path, caption)

def _send_video(self, chat_id: str, video_path: str, caption: str = "") -> bool:
    """Send video via multipart upload."""
    return self._send_multipart(chat_id, "sendVideo", "video", video_path, caption)

def _send_sticker(self, chat_id: str, sticker_path: str) -> bool:
    """Send sticker via multipart upload."""
    return self._send_multipart(chat_id, "sendSticker", "sticker", sticker_path)

def _send_multipart(self, chat_id: str, method: str, field_name: str,
                    file_path: str, caption: str = "") -> bool:
    """Send file via multipart/form-data to Telegram."""
    import mimetypes
    boundary = "----OrchestratorBoundary"
    filename = os.path.basename(file_path)
    mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    body = bytearray()
    # chat_id field
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode()
    # caption field (if any)
    if caption:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode()
    # file field
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
    body += f"Content-Type: {mime}\r\n\r\n".encode()
    body += open(file_path, "rb").read()
    body += f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{self._base_url}/{method}",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        return result.get("ok", False)
    except Exception as e:
        log.warning(f"telegram: {method} failed: {e}")
        return False
```

- [ ] **Step 3: Rewrite _handle_update for media**

Replace the existing method to handle photos, voice, documents, stickers, video:

```python
def _handle_update(self, update: dict):
    self._last_update_id = update.get("update_id", self._last_update_id)
    message = update.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    if not chat_id:
        return

    # Auth
    if ch_cfg.ALLOWED_USERS:
        if not ch_cfg.user_can(chat_id, "chat"):
            return
    elif self.chat_id and chat_id != self.chat_id:
        return

    # Rate limit
    now = time.time()
    if now - self._last_msg_time.get(chat_id, 0) < ch_cfg.RATE_LIMIT_WINDOW:
        return
    self._last_msg_time[chat_id] = now

    text = (message.get("text") or message.get("caption") or "").strip()
    attachments = []

    # Extract media from message
    if "photo" in message:
        # Telegram sends multiple sizes, pick largest
        photo = message["photo"][-1]
        file_id = photo["file_id"]
        att = self._download_tg_file(file_id, MediaType.IMAGE, "image/jpeg")
        if att:
            attachments.append(att)

    if "voice" in message:
        file_id = message["voice"]["file_id"]
        att = self._download_tg_file(file_id, MediaType.VOICE, "audio/ogg",
                                      duration_ms=message["voice"].get("duration", 0) * 1000)
        if att:
            attachments.append(att)

    if "audio" in message:
        file_id = message["audio"]["file_id"]
        att = self._download_tg_file(file_id, MediaType.VOICE,
                                      message["audio"].get("mime_type", "audio/mpeg"),
                                      duration_ms=message["audio"].get("duration", 0) * 1000)
        if att:
            attachments.append(att)

    if "document" in message:
        doc = message["document"]
        file_id = doc["file_id"]
        att = self._download_tg_file(file_id, MediaType.FILE,
                                      doc.get("mime_type", "application/octet-stream"))
        if att:
            att.file_name = doc.get("file_name", "")
            attachments.append(att)

    if "sticker" in message:
        sticker = message["sticker"]
        file_id = sticker["file_id"]
        att = self._download_tg_file(file_id, MediaType.IMAGE, "image/webp")
        if att:
            attachments.append(att)

    if "video" in message:
        vid = message["video"]
        file_id = vid["file_id"]
        att = self._download_tg_file(file_id, MediaType.VIDEO, "video/mp4",
                                      duration_ms=vid.get("duration", 0) * 1000)
        if att:
            attachments.append(att)

    if "video_note" in message:
        vn = message["video_note"]
        file_id = vn["file_id"]
        att = self._download_tg_file(file_id, MediaType.VIDEO, "video/mp4",
                                      duration_ms=vn.get("duration", 0) * 1000)
        if att:
            attachments.append(att)

    if not text and not attachments:
        return

    if text and text.startswith("/"):
        self._send_typing(chat_id)
        chat_engine.handle_command(text, chat_id, self._send_text, "telegram")
    else:
        if text and len(text) > ch_cfg.LONG_MSG_THRESHOLD:
            file_path, char_count = chat_engine.save_to_inbox(text)
            preview = text[:80].replace("\n", " ")
            ref = f'[用户发送了长消息 ({char_count}字)，已保存到 {file_path}，预览: "{preview}..."]'
            self._start_chat(chat_id, ref, original_text=text, media=attachments)
        else:
            desc = text or self._describe_media(attachments)
            self._start_chat(chat_id, desc, media=attachments)

def _download_tg_file(self, file_id: str, media_type: MediaType,
                      mime: str, duration_ms: int = 0) -> MediaAttachment | None:
    """Download a Telegram file by file_id."""
    try:
        url = self._tg_get_file_url(file_id)
        if not url:
            return None
        local_path = download_url(url, "inbound")
        return MediaAttachment(
            media_type=media_type, local_path=local_path,
            mime_type=mime, duration_ms=duration_ms,
        )
    except Exception as e:
        log.warning(f"telegram: file download failed: {e}")
        return None

@staticmethod
def _describe_media(attachments: list[MediaAttachment]) -> str:
    """Generate text description for media-only messages."""
    descs = []
    for a in attachments:
        if a.media_type == MediaType.IMAGE:
            descs.append("[用户发送了一张图片]")
        elif a.media_type == MediaType.VOICE:
            descs.append(f"[用户发送了一条语音{f': {a.text}' if a.text else ''}]")
        elif a.media_type == MediaType.FILE:
            descs.append(f"[用户发送了文件: {a.file_name or '未知'}]")
        elif a.media_type == MediaType.VIDEO:
            descs.append("[用户发送了一段视频]")
    return " ".join(descs) if descs else "[用户发送了媒体消息]"
```

- [ ] **Step 4: Update _start_chat + add _reply_media**

```python
def _start_chat(self, chat_id: str, text: str, original_text: str = "",
                media: list[MediaAttachment] | None = None):
    def _chat_with_typing():
        typing_stop = self._keep_typing(chat_id)
        try:
            chat_engine.do_chat(
                chat_id, text, original_text,
                self._get_system_prompt(),
                lambda cid, txt, **kw: self._reply_media(cid, txt, **kw),
                "telegram",
                permission_check_fn=lambda cid, tool: ch_cfg.user_can(cid, tool),
                media=media,
            )
        finally:
            typing_stop.set()

    threading.Thread(target=_chat_with_typing, name="tg-chat", daemon=True).start()

def _reply_media(self, chat_id: str, text: str,
                 media_path: str = "", media_type: str = "") -> bool:
    """Reply with text and/or media."""
    if media_path and os.path.exists(media_path):
        mime = media_type or ""
        caption = text[:1024] if text else ""  # TG caption limit
        if mime.startswith("image/"):
            return self._send_photo(chat_id, media_path, caption)
        elif mime.startswith("video/"):
            return self._send_video(chat_id, media_path, caption)
        elif mime.startswith("audio/"):
            return self._send_voice(chat_id, media_path, caption)
        else:
            return self._send_document(chat_id, media_path, caption)

    # Text only (existing behavior)
    return self._send_text(chat_id, text)
```

- [ ] **Step 5: Commit**

```bash
git add src/channels/telegram/channel.py
git commit -m "feat(telegram): full multimodal - receive/send photo, voice, file, video, sticker"
```

---

## Task 8: Chat engine — multimodal message passing to LLM

**Files:**
- Modify: `src/channels/chat.py`

- [ ] **Step 1: Update do_chat signature to accept media**

```python
def do_chat(chat_id: str, text: str, original_text: str,
            system_prompt: str, reply_fn, channel_source: str = "channel",
            permission_check_fn=None,
            media: list = None):  # list[MediaAttachment]
```

- [ ] **Step 2: Add image handling — route to vision model or Claude multimodal**

When `media` contains images, build multimodal messages for Claude API or route to Ollama gemma3:27b vision:

```python
# Inside do_chat, after building messages, before routing:
image_paths = []
if media:
    from src.channels.media import MediaType
    for att in media:
        if att.media_type == MediaType.IMAGE and att.local_path:
            image_paths.append(att.local_path)
        elif att.media_type == MediaType.VOICE and att.text:
            # Voice with transcription: append to text
            text = f"{text}\n[语音转文字: {att.text}]" if text else f"[语音转文字: {att.text}]"
        elif att.media_type == MediaType.FILE:
            text = f"{text}\n[用户发送了文件: {att.file_name}]" if text else f"[用户发送了文件: {att.file_name}]"

# Force Claude API when images present (need multimodal)
if image_paths:
    # Skip local model, go straight to Claude with images
    # ... (modify the Claude API call to include images)
```

In the Claude API loop, build multimodal content:

```python
# When building messages for Claude with images:
if image_paths:
    import base64
    content_parts = []
    for img_path in image_paths:
        img_data = open(img_path, "rb").read()
        b64 = base64.b64encode(img_data).decode()
        # Detect mime
        mime = "image/jpeg"
        if img_path.endswith(".png"):
            mime = "image/png"
        elif img_path.endswith(".webp"):
            mime = "image/webp"
        content_parts.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        })
    content_parts.append({"type": "text", "text": text or "请描述这张图片"})
    messages.append({"role": "user", "content": content_parts})
else:
    messages.append({"role": "user", "content": text})
```

- [ ] **Step 3: Commit**

```bash
git add src/channels/chat.py
git commit -m "feat(chat): multimodal LLM routing - images to Claude vision, voice transcription passthrough"
```

---

## Task 9: Config additions

**Files:**
- Modify: `src/channels/config.py`

- [ ] **Step 1: Add media config vars**

```python
# ── 媒体 ──
MEDIA_DIR = _str("CHANNEL_MEDIA_DIR", "tmp/media")
MEDIA_MAX_BYTES = _int("CHANNEL_MEDIA_MAX_BYTES", 50 * 1024 * 1024)
WECHAT_CDN_BASE_URL = _str("WECHAT_CDN_BASE_URL", "https://cdn.ilinkai.weixin.qq.com")
```

- [ ] **Step 2: Commit**

```bash
git add src/channels/config.py
git commit -m "feat(config): add media directory and CDN config"
```

---

## Task 10: Integration test — Docker rebuild + manual verification

**Files:** None (testing only)

- [ ] **Step 1: Docker rebuild**

```bash
docker compose build --no-cache
docker compose up -d
```

- [ ] **Step 2: Verify bot starts without errors**

```bash
docker logs --tail 30 orchestrator
```

Expected: Telegram and WeChat channels started, no import errors.

- [ ] **Step 3: Test inbound — send image to WeChat bot**

Send a photo from WeChat. Check logs for:
- `wechat: msg from ... media=1`
- CDN download success
- LLM response about the image

- [ ] **Step 4: Test inbound — send image to Telegram bot**

Send a photo. Check logs for media download and vision processing.

- [ ] **Step 5: Test WeChat typing indicator**

Send any message. Check that typing indicator appears in WeChat while bot is thinking.

- [ ] **Step 6: Test outbound — bot sends image (via wake_claude or dispatch_task)**

Trigger a task that generates an image. Verify it arrives as a proper image (not a file path).

- [ ] **Step 7: Commit final state**

```bash
git add -A
git commit -m "feat: full multimodal channel support — TG + WX image/voice/file/video + WX typing"
```

---

## Summary of Changes

| Component | Before | After |
|---|---|---|
| **WeChat inbound** | Text + voice transcription only | Text + image + voice + file + video (CDN decrypt) |
| **WeChat outbound** | Text only | Text + image + file + video (CDN encrypt + upload) |
| **WeChat typing** | API wrapped but unused | Full typing indicator with 5s keepalive |
| **Telegram inbound** | Text only | Text + photo + voice + document + sticker + video + video_note |
| **Telegram outbound** | Text only | Text + photo + voice + document + sticker + video |
| **Chat engine** | Text only to LLM | Multimodal: images → Claude vision, voice → transcription passthrough |
| **Dependencies** | None for crypto | `cryptography>=42.0.0` for AES-128-ECB |
