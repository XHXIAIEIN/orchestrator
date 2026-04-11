"""R47 (Archon): Message Splitting + Markdown Fallback.

Two-pass splitting for platform message limits:
  Pass 1: Split by paragraphs (double newline)
  Pass 2: If any chunk still too long, split by single newlines

MarkdownV2 fallback: if formatting fails, strip to plain text.
"""
import logging
import re

log = logging.getLogger(__name__)

# Platform message limits
PLATFORM_LIMITS = {
    "telegram": 4096,
    "wechat": 2048,
    "discord": 2000,
    "slack": 40000,
    "default": 4096,
}


def split_message(text: str, platform: str = "telegram",
                  max_length: int | None = None) -> list[str]:
    """Split a message to fit platform limits.

    Pass 1: Split by paragraphs (\\n\\n).
    Pass 2: Split remaining oversized chunks by lines (\\n).
    Pass 3: Hard-split any still-oversized chunks by character limit.
    """
    limit = max_length or PLATFORM_LIMITS.get(platform, PLATFORM_LIMITS["default"])

    if len(text) <= limit:
        return [text]

    # Pass 1: paragraph split
    chunks = _split_by_separator(text, "\n\n", limit)

    # Pass 2: line split for oversized paragraphs
    result = []
    for chunk in chunks:
        if len(chunk) <= limit:
            result.append(chunk)
        else:
            result.extend(_split_by_separator(chunk, "\n", limit))

    # Pass 3: hard split for any remaining oversized chunks
    final = []
    for chunk in result:
        if len(chunk) <= limit:
            final.append(chunk)
        else:
            # Hard split at limit, trying to break at word boundary
            while chunk:
                if len(chunk) <= limit:
                    final.append(chunk)
                    break
                # Find last space before limit
                break_at = chunk.rfind(" ", 0, limit)
                if break_at <= 0:
                    break_at = limit
                final.append(chunk[:break_at])
                chunk = chunk[break_at:].lstrip()

    return [c for c in final if c.strip()]


def _split_by_separator(text: str, sep: str, limit: int) -> list[str]:
    """Split text by separator, merging small chunks to fill limit."""
    parts = text.split(sep)
    chunks = []
    current = ""

    for part in parts:
        candidate = current + sep + part if current else part
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = part

    if current:
        chunks.append(current)

    return chunks


def format_telegram_markdown(text: str) -> str:
    """Format text as Telegram MarkdownV2. Falls back to plain text on failure.

    Telegram MarkdownV2 requires escaping: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    try:
        return _escape_markdown_v2(text)
    except Exception:
        log.debug("MarkdownV2 formatting failed, falling back to plain text")
        return strip_markdown(text)


def strip_markdown(text: str) -> str:
    """Strip all markdown formatting to plain text."""
    # Remove code blocks
    text = re.sub(r"```[\s\S]*?```", lambda m: m.group(0).strip("`").strip(), text)
    # Remove inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove bold/italic
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    # Remove links
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    return text


_MARKDOWN_V2_ESCAPE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!])")


def _escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    # Don't escape inside code blocks
    parts = text.split("```")
    for i in range(0, len(parts), 2):  # even indices = outside code blocks
        if i < len(parts):
            parts[i] = _MARKDOWN_V2_ESCAPE.sub(r"\\\1", parts[i])
    return "```".join(parts)
