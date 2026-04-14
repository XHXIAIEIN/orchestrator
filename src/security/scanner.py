"""Security Scanner — R55.

Scans text content against the attack pattern library and returns matches.

scan_content(text)  → list[Match]
scan_file(path)     → list[Match]

Design goals:
- Fast: patterns are compiled once at module import, not per call
- No I/O side-effects in scan_content
- Returns structured Match objects; callers decide how to handle risk levels
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.security.patterns import PATTERNS, AttackPattern, RiskLevel


# ─────────────────────────────────────────────────────────────────────────────
# Compile patterns once at import time
# ─────────────────────────────────────────────────────────────────────────────

def _compile_patterns() -> None:
    """Attach compiled regex objects to each AttackPattern in-place."""
    for pattern in PATTERNS:
        pattern._compiled = [
            re.compile(kw, re.IGNORECASE | re.MULTILINE)
            for kw in pattern.detection_keywords
        ]


_compile_patterns()


# ─────────────────────────────────────────────────────────────────────────────
# Public types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Match:
    pattern_id: str
    risk_level: RiskLevel
    category: str
    matched_text: str       # the substring that triggered the match
    line_number: int        # 1-based; 0 if not determinable
    keyword: str            # the regex pattern that matched
    description: str        # human-readable summary of the threat


# ─────────────────────────────────────────────────────────────────────────────
# Core scanner
# ─────────────────────────────────────────────────────────────────────────────

def scan_content(text: str) -> list[Match]:
    """Scan arbitrary text against all attack patterns.

    Returns a list of Match objects (may be empty). The caller is responsible
    for deciding how to respond based on risk_level.

    Complexity: O(P * K * N) where P=patterns, K=keywords per pattern, N=lines.
    In practice <10 ms for files up to ~10 000 lines because most patterns
    fail the fast-path .search() before line enumeration.
    """
    if not text:
        return []

    lines = text.splitlines()
    matches: list[Match] = []

    for attack: AttackPattern in PATTERNS:
        for compiled, keyword in zip(attack._compiled, attack.detection_keywords):
            # Fast path: try the whole text first (avoids per-line loop)
            if not compiled.search(text):
                continue

            # Slow path: find which lines matched to report line numbers
            for lineno, line in enumerate(lines, start=1):
                m = compiled.search(line)
                if m:
                    matches.append(Match(
                        pattern_id=attack.id,
                        risk_level=attack.risk_level,
                        category=attack.category.value,
                        matched_text=m.group(0),
                        line_number=lineno,
                        keyword=keyword,
                        description=attack.description,
                    ))
                    break  # one match per pattern per scan; don't flood with dupes

            # One match per pattern is enough — stop checking more keywords
            # for this pattern once we've recorded a hit.
            if matches and matches[-1].pattern_id == attack.id:
                break

    return matches


def scan_file(path: str) -> list[Match]:
    """Read file at *path* and scan its contents.

    Returns an empty list if the file cannot be read.
    Binary files are skipped (UnicodeDecodeError → []).
    """
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    return scan_content(content)


# ─────────────────────────────────────────────────────────────────────────────
# Convenience helpers
# ─────────────────────────────────────────────────────────────────────────────

def highest_risk(matches: list[Match]) -> RiskLevel | None:
    """Return the highest RiskLevel across all matches, or None if no matches."""
    if not matches:
        return None
    order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.REJECT]
    return max(matches, key=lambda m: order.index(m.risk_level)).risk_level


def format_matches(matches: list[Match]) -> str:
    """Human-readable summary of matches (for hook stderr output)."""
    if not matches:
        return ""
    lines = []
    for m in matches:
        lines.append(
            f"[{m.risk_level.value}] {m.pattern_id} @ line {m.line_number}: "
            f"matched '{m.matched_text}'"
        )
    return "\n".join(lines)
