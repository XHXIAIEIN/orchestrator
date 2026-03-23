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
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

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
    local_path: str = ""
    mime_type: str = ""
    file_name: str = ""
    file_size: int = 0
    duration_ms: int = 0
    width: int = 0
    height: int = 0
    text: str = ""                # voice transcription / caption
    cdn_encrypt_query_param: str = ""
    cdn_aes_key: str = ""


def ensure_media_dir(subdir: str = "inbound") -> Path:
    d = MEDIA_DIR / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d


def guess_mime(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def save_media_buffer(buf: bytes, mime: str = "", subdir: str = "inbound",
                      original_filename: str = "") -> str:
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
    from urllib.parse import urlparse
    path = urlparse(url).path
    if "." in path.split("/")[-1]:
        return "." + path.split(".")[-1][:5]
    return ".bin"
