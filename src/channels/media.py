"""
Unified media types for channel layer.

Platform-agnostic media representation. Each channel adapter converts
platform-specific media to/from these types.
"""
import hashlib
import logging
import mimetypes
import os
import re
import subprocess
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
    # SSRF gate — validate URL before fetching (S13)
    from src.governance.safety.ssrf import assert_safe_url
    assert_safe_url(url)

    d = ensure_media_dir(subdir)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        buf = resp.read(MEDIA_MAX_BYTES + 1)
        if len(buf) > MEDIA_MAX_BYTES:
            raise ValueError(f"Media too large (>{MEDIA_MAX_BYTES} bytes)")
    ext = _ext_from_mime(content_type) or _ext_from_url(url)
    # When MIME/URL give .bin, try magic bytes on the downloaded buffer
    if ext == ".bin" and len(buf) >= 16:
        mime_detected = _detect_mime_from_header(buf[:16])
        if mime_detected and mime_detected in _MIME_TO_EXT:
            ext = _MIME_TO_EXT[mime_detected]
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


# ── Magic-bytes image detection ──────────────────────────────────────────

# Signatures: (offset, magic_bytes, mime_type)
_IMAGE_SIGNATURES: list[tuple[int, bytes, str]] = [
    (0, b"\xff\xd8\xff",       "image/jpeg"),
    (0, b"\x89PNG\r\n\x1a\n",  "image/png"),
    (0, b"GIF87a",             "image/gif"),
    (0, b"GIF89a",             "image/gif"),
    (0, b"RIFF",               "image/webp"),  # RIFF....WEBP — extra check below
]


def _detect_mime_from_header(header: bytes) -> str:
    """Detect image MIME from raw header bytes (>= 16 bytes recommended).

    Returns mime string ("image/jpeg" etc.) or empty string.
    """
    if len(header) < 4:
        return ""
    for offset, magic, mime in _IMAGE_SIGNATURES:
        end = offset + len(magic)
        if header[offset:end] == magic:
            if magic == b"RIFF":
                if len(header) >= 12 and header[8:12] == b"WEBP":
                    return "image/webp"
                continue
            return mime
    return ""


def detect_image_mime(path: str) -> str:
    """Detect image MIME type from file magic bytes.

    Returns mime string ("image/jpeg" etc.) or empty string if not a
    recognised image format.  Never raises.
    """
    try:
        with open(path, "rb") as f:
            header = f.read(16)
    except Exception:
        return ""
    return _detect_mime_from_header(header)


_MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/png":  ".png",
    "image/gif":  ".gif",
    "image/webp": ".webp",
}


def is_image_file(path: str) -> bool:
    """Check if *path* is a recognisable image (by extension OR magic bytes)."""
    ext = Path(path).suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return True
    return bool(detect_image_mime(path))


# ── Document text extraction (stolen from MarkItDown patterns) ──────────

# Pattern C: lazy dependency detection — None = untested, True/False = cached
_markitdown_available: bool | None = None

# MIME types we can extract text from
_EXTRACTABLE_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",   # docx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation", # pptx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",         # xlsx
    "application/vnd.ms-excel",                                                   # xls
    "application/epub+zip",
    "text/html",
    "text/csv",
}

# Also match by extension when MIME is generic "application/octet-stream"
_EXTRACTABLE_EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".epub", ".html", ".htm", ".csv"}

EXTRACT_TIMEOUT = 30  # seconds
EXTRACT_MAX_CHARS = 200_000  # ~50K tokens, safe for context budgets


def _check_markitdown() -> bool:
    """Lazy check: is uvx markitdown available?"""
    global _markitdown_available
    if _markitdown_available is not None:
        return _markitdown_available
    try:
        subprocess.run(
            ["uvx", "markitdown", "--help"],
            capture_output=True, timeout=15,
        )
        _markitdown_available = True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        _markitdown_available = False
        log.warning("markitdown not available (uvx markitdown --help failed), "
                    "document text extraction disabled")
    return _markitdown_available


def _is_extractable(path: str, mime: str) -> bool:
    """Check if this file type is worth attempting extraction."""
    if mime and any(mime.startswith(m) for m in _EXTRACTABLE_MIMES):
        return True
    ext = Path(path).suffix.lower()
    return ext in _EXTRACTABLE_EXTS


def _postprocess_markdown(text: str) -> str:
    """Clean markitdown output for LLM consumption."""
    # 1. Compress 3+ consecutive blank lines → 2
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 2. Strip trailing whitespace per line
    text = "\n".join(line.rstrip() for line in text.split("\n"))

    # 3. Remove repeated headers/footers (same line appearing 5+ times)
    lines = text.split("\n")
    if len(lines) > 30:
        from collections import Counter
        counts = Counter(line for line in lines if len(line.strip()) > 3)
        repeats = {line for line, c in counts.items()
                   if c >= 5 and not line.startswith("|") and line.strip() != "---"}
        if repeats:
            seen = set()
            filtered = []
            for line in lines:
                if line in repeats:
                    if line not in seen:
                        seen.add(line)
                        filtered.append(line)
                    # else: skip duplicate
                else:
                    filtered.append(line)
            text = "\n".join(filtered)

    # 4. Truncate if over budget
    if len(text) > EXTRACT_MAX_CHARS:
        text = text[:EXTRACT_MAX_CHARS] + f"\n\n[... truncated, original ~{len(text)} chars]"

    return text.strip()


def extract_document_text(path: str, mime: str = "") -> str:
    """Extract text from a document file using markitdown.

    Returns extracted markdown text, or empty string on failure.
    Never raises — failures are logged and gracefully degraded.
    """
    if not _is_extractable(path, mime):
        return ""
    if not Path(path).exists():
        return ""
    if not _check_markitdown():
        return ""

    try:
        result = subprocess.run(
            ["uvx", "markitdown", path],
            capture_output=True, text=True,
            timeout=EXTRACT_TIMEOUT,
        )
        if result.returncode != 0:
            log.warning(f"markitdown failed for {path}: {result.stderr[:200]}")
            return ""

        raw = result.stdout
        if not raw or not raw.strip():
            return ""

        return _postprocess_markdown(raw)

    except subprocess.TimeoutExpired:
        log.warning(f"markitdown timed out for {path} ({EXTRACT_TIMEOUT}s)")
        return ""
    except Exception as e:
        log.warning(f"document extraction failed for {path}: {e}")
        return ""


def _ext_from_url(url: str) -> str:
    from urllib.parse import urlparse
    path = urlparse(url).path
    if "." in path.split("/")[-1]:
        return "." + path.split(".")[-1][:5]
    return ".bin"
