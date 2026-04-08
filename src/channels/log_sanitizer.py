"""
Secret sanitization filter for logging — prevents tokens, keys, and
passwords from leaking into log output.

Install once at startup via install(); all loggers under src.channels
(and optionally the root logger) will have secrets redacted.

Stolen from: Claude-to-IM-skill (R45a) — secret 脱敏日志模式。
"""
import logging
import re

# ── Patterns ────────────────────────────────────────────────────────────────
# Each pattern replaces the secret portion, keeping the last 4 chars visible.

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # 1. Key-value pairs: token=xxx, api_key="xxx", password: xxx
    (
        re.compile(
            r'(?i)((?:token|secret|password|api_key|apikey|api[-_]?secret|'
            r'authorization|auth_token|access_token|refresh_token)'
            r'\s*[=:]\s*["\']?)([^\s"\']{8,})',
        ),
        _KEY_VALUE := "kv",  # sentinel — handled in code
    ),
    # 2. Bearer tokens: Bearer eyJhbGci...
    (
        re.compile(r'(Bearer\s+)([A-Za-z0-9._\-]{12,})', re.IGNORECASE),
        "bearer",
    ),
    # 3. WeChat/Telegram bot tokens: digits:alphanums (e.g. 123456789:ABCdefGHI...)
    (
        re.compile(r'(\b\d{6,}:)([A-Za-z0-9_\-]{20,})'),
        "bot_token",
    ),
]


def _redact(value: str) -> str:
    """Keep last 4 chars, replace rest with ***."""
    if len(value) <= 4:
        return "***"
    return "***" + value[-4:]


def _sanitize(text: str) -> str:
    """Apply all redaction patterns to a string."""
    for pattern, kind in _PATTERNS:
        def _replacer(m: re.Match) -> str:
            prefix = m.group(1)
            secret = m.group(2)
            return prefix + _redact(secret)
        text = pattern.sub(_replacer, text)
    return text


class SecretFilter(logging.Filter):
    """Logging filter that redacts secrets from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Sanitize the message string
        if isinstance(record.msg, str):
            record.msg = _sanitize(record.msg)
        # Sanitize any string args (for %-style formatting)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: _sanitize(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _sanitize(a) if isinstance(a, str) else a
                    for a in record.args
                )
        return True


# ── Installation ────────────────────────────────────────────────────────────

_installed = False


def install(root: bool = False):
    """Install SecretFilter on all src.channels loggers.

    Args:
        root: If True, also install on the root logger (covers everything).
    """
    global _installed
    if _installed:
        return
    _installed = True

    sf = SecretFilter()

    # Always cover the channels namespace
    channels_logger = logging.getLogger("src.channels")
    channels_logger.addFilter(sf)

    if root:
        logging.getLogger().addFilter(sf)
