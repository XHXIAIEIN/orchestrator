"""
Content chunking strategies for vector store ingestion.

Two modes:
    1. Exchange-pair chunking (R44 P1#7): for conversation-like content,
       keeps Q+A pairs as atomic units. Never splits a question from its answer.
    2. Fixed-size chunking: for prose/docs, splits at paragraph boundaries
       with configurable size and overlap.

Auto-detection: if content has >= 3 turn markers, use exchange-pair mode.
"""

import re

# ---------------------------------------------------------------------------
# Turn detection
# ---------------------------------------------------------------------------

# Patterns that indicate a conversation turn boundary
_TURN_PATTERNS = [
    r"^>\s*\*?\*?(?:主人|user|human|用户)\*?\*?\s*[:：]",  # > **主人**: ...
    r"^>\s*\*?\*?(?:你|assistant|ai|orchestrator)\*?\*?\s*[:：]",
    r"^(?:主人|user|human|用户)\s*[:：]",
    r"^(?:你|assistant|ai|orchestrator)\s*[:：]",
    r"^Q\s*[:：]",
    r"^A\s*[:：]",
]
_TURN_RE = re.compile("|".join(_TURN_PATTERNS), re.IGNORECASE | re.MULTILINE)


def _is_conversation(text: str) -> bool:
    """Detect if text looks like a conversation transcript."""
    return len(_TURN_RE.findall(text)) >= 3


# ---------------------------------------------------------------------------
# Exchange-pair chunking
# ---------------------------------------------------------------------------

def _chunk_exchanges(text: str) -> list[str]:
    """Split conversation text into Q+A exchange pairs.

    Each chunk contains one user message + the following assistant response.
    If a message has no pair, it becomes its own chunk.
    """
    lines = text.split("\n")
    chunks = []
    current_chunk: list[str] = []
    turn_count_in_chunk = 0

    for line in lines:
        is_turn = bool(_TURN_RE.match(line))

        if is_turn:
            # New turn detected
            if turn_count_in_chunk >= 2:
                # Already have a Q+A pair — flush
                chunks.append("\n".join(current_chunk).strip())
                current_chunk = []
                turn_count_in_chunk = 0

            current_chunk.append(line)
            turn_count_in_chunk += 1
        else:
            current_chunk.append(line)

    # Flush remaining
    if current_chunk:
        text = "\n".join(current_chunk).strip()
        if text:
            chunks.append(text)

    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# Fixed-size chunking
# ---------------------------------------------------------------------------

def _chunk_fixed(
    text: str,
    max_chars: int = 800,
    overlap: int = 100,
) -> list[str]:
    """Split text into fixed-size chunks at paragraph boundaries.

    Prefers splitting at double-newlines (paragraph breaks), falls back
    to single newlines, then hard splits at max_chars.
    """
    if len(text) <= max_chars:
        return [text]

    # Split into paragraphs first
    paragraphs = re.split(r"\n\n+", text)
    chunks = []
    current = ""

    for para in paragraphs:
        if not para.strip():
            continue

        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current.strip())
                # Overlap: keep tail of previous chunk
                if overlap > 0 and len(current) > overlap:
                    current = current[-overlap:] + "\n\n" + para
                else:
                    current = para
            else:
                # Single paragraph exceeds max — hard split
                for i in range(0, len(para), max_chars - overlap):
                    chunk = para[i : i + max_chars]
                    if chunk.strip():
                        chunks.append(chunk.strip())
                current = ""

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    max_chars: int = 800,
    overlap: int = 100,
    force_mode: str | None = None,
) -> list[str]:
    """Auto-detect content type and chunk accordingly.

    Args:
        text: Content to chunk.
        max_chars: Max chars per chunk (fixed mode only).
        overlap: Overlap chars between chunks (fixed mode only).
        force_mode: 'exchange' or 'fixed' to skip auto-detection.

    Returns:
        List of text chunks, each suitable for embedding.
    """
    if not text or not text.strip():
        return []

    if force_mode == "exchange" or (force_mode is None and _is_conversation(text)):
        return _chunk_exchanges(text)
    else:
        return _chunk_fixed(text, max_chars=max_chars, overlap=overlap)
