"""Query Sanitizer — prevent system prompt pollution in vector search.

Stolen from: MemPalace R67 P0.1 (query_sanitizer.py)
Problem: When the full conversation context (including system prompt) is passed
as a vector search query, the system prompt prefix dominates the embedding,
causing recall to drop from 89.8% to 1.0%.

Solution: Four-step cascading sanitization:
  1. Short query (≤200 chars) → passthrough (no pollution risk)
  2. Extract last question sentence (most likely the actual query)
  3. Extract last non-empty paragraph (conversation tail)
  4. Tail truncation fallback (last 250 chars)
"""
from __future__ import annotations

import re

SAFE_QUERY_LENGTH = 200     # Below this, no sanitization needed
MIN_QUERY_LENGTH = 5        # Minimum viable query segment (low for CJK density)
MAX_QUERY_LENGTH = 250      # Tail truncation cap

_QUESTION_MARK = re.compile(r"[?？]")


def sanitize_query(raw_query: str) -> dict:
    """Sanitize a raw query string for vector search.

    Returns dict with keys:
        clean_query: str  — the sanitized query
        was_sanitized: bool — whether sanitization was applied
        method: str — which strategy was used
    """
    if not raw_query or not raw_query.strip():
        return {"clean_query": "", "was_sanitized": False, "method": "empty"}

    raw_query = raw_query.strip()

    # Step 1: Short queries are safe
    if len(raw_query) <= SAFE_QUERY_LENGTH:
        return {"clean_query": raw_query, "was_sanitized": False, "method": "passthrough"}

    # Step 2: Find the last question sentence
    for seg in reversed(raw_query.split("\n")):
        seg = seg.strip()
        if _QUESTION_MARK.search(seg) and len(seg) >= MIN_QUERY_LENGTH:
            return {"clean_query": seg, "was_sanitized": True, "method": "question_extraction"}

    # Step 3: Last non-empty paragraph
    for seg in reversed(raw_query.split("\n\n")):
        seg = seg.strip()
        if len(seg) >= MIN_QUERY_LENGTH:
            if len(seg) <= MAX_QUERY_LENGTH:
                return {"clean_query": seg, "was_sanitized": True, "method": "paragraph_extraction"}
            break  # paragraph too long, fall through to truncation

    # Step 4: Tail truncation fallback
    return {
        "clean_query": raw_query[-MAX_QUERY_LENGTH:],
        "was_sanitized": True,
        "method": "tail_truncation",
    }
