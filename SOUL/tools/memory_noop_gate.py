"""
Memory No-Op Gate — reject low-value memory writes before they pollute the archive.

Source: Codex CLI Memory No-Op Gate (Round 28c)

Problem: Memory systems accumulate noise. "User asked about X" is not worth storing.
Solution: Score each candidate memory against novelty + actionability criteria.
Only commit memories that would change future behavior.
"""
from __future__ import annotations

import re
from pathlib import Path

_NOISE_PATTERNS = [
    r"^user asked about",
    r"^user wants to",
    r"^user is working on",
    r"^the user mentioned",
    r"^conversation about",
    r"^discussed\b",
    r"^helped with",
    r"^session involved",
    r"debug(ged|ging) .{0,20}$",
    r"^ran (tests?|commands?)",
]

_SIGNAL_PATTERNS = [
    r"prefers?\b",
    r"always use|never use",
    r"broke|broken|bug|regression",
    r"workaround|fix was",
    r"incompatible|doesn't work with",
    r"path is|located at|lives in",
    r"api key|token|credential",
    r"deadline|due by|freeze",
]


def _score_novelty(candidate: str, existing: list[str]) -> float:
    """Score how novel this candidate is vs existing memories."""
    if not existing:
        return 1.0
    candidate_lower = candidate.lower().strip()
    candidate_words = set(candidate_lower.split())
    best_overlap = 0.0
    for mem in existing:
        mem_words = set(mem.lower().strip().split())
        if not candidate_words or not mem_words:
            continue
        overlap = len(candidate_words & mem_words) / max(len(candidate_words), len(mem_words))
        best_overlap = max(best_overlap, overlap)
    return 1.0 - best_overlap


def _score_actionability(candidate: str) -> float:
    """Score whether this memory would change future behavior."""
    text = candidate.lower()
    for pattern in _NOISE_PATTERNS:
        if re.search(pattern, text):
            return 0.1
    signal_count = sum(1 for p in _SIGNAL_PATTERNS if re.search(p, text))
    if signal_count >= 2:
        return 0.9
    elif signal_count == 1:
        return 0.6
    return 0.4


def should_store_memory(candidate: str, existing_memories: list[str] | None = None,
                         novelty_threshold: float = 0.3,
                         actionability_threshold: float = 0.3) -> bool:
    """Decide whether a candidate memory is worth storing."""
    if not candidate or len(candidate.strip()) < 10:
        return False
    existing = existing_memories or []
    novelty = _score_novelty(candidate, existing)
    actionability = _score_actionability(candidate)
    return novelty >= novelty_threshold and actionability >= actionability_threshold


def load_existing_memory_texts(memory_dir: Path) -> list[str]:
    """Load text content from all memory .md files for dedup comparison."""
    texts = []
    if not memory_dir.exists():
        return texts
    for f in memory_dir.iterdir():
        if f.suffix == ".md" and f.name != "MEMORY.md":
            try:
                texts.append(f.read_text(encoding="utf-8"))
            except Exception:
                continue
    return texts
