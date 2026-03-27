"""Fast Rule Scan — zero-LLM regex signal detection.

Before context compression, scan for critical signal patterns that must be
preserved. This runs at zero LLM cost using pure regex.

Rescued signals get pinned in context so the condenser can't drop them.
"""

import re
from dataclasses import dataclass


@dataclass
class Signal:
    """A detected signal that should be preserved."""
    category: str       # "safety", "constraint", "directive", "error"
    pattern_name: str   # which pattern matched
    text: str          # the matched text
    priority: int      # higher = more important to preserve


# Signal patterns: (name, regex, category, priority)
_SIGNAL_PATTERNS: list[tuple[str, str, str, int]] = [
    # Safety constraints
    ("forbidden_action", r"(?:NEVER|MUST NOT|FORBIDDEN|PROHIBITED|DO NOT)\s+.{10,80}", "safety", 100),
    ("immutable_rule", r"(?:IMMUTABLE|CANNOT BE CHANGED|HARDCODED)\s*[:：].{10,80}", "safety", 100),
    ("authority_ceiling", r"(?:APPROVE|HUMAN[- ]ONLY|REQUIRES APPROVAL)", "safety", 90),

    # Error signals
    ("error_marker", r"(?:ERROR|FAILED|EXCEPTION|TRACEBACK)\s*[:：].{10,80}", "error", 80),
    ("rollback_needed", r"(?:ROLLBACK|REVERT|UNDO)\s+.{10,50}", "error", 85),

    # Directives
    ("owner_directive", r"(?:主人说|owner said|user requested)\s*[:：].{10,80}", "directive", 70),
    ("task_constraint", r"(?:CONSTRAINT|REQUIREMENT|MUST)\s*[:：].{10,80}", "constraint", 75),
    ("deadline", r"(?:DEADLINE|BY|BEFORE|DUE)\s+\d{4}-\d{2}-\d{2}", "constraint", 70),

    # Budget/resource
    ("budget_warning", r"(?:BUDGET|TOKEN|COST)\s+(?:EXCEEDED|WARNING|LIMIT)", "constraint", 85),
    ("context_full", r"(?:CONTEXT|WINDOW)\s+(?:FULL|EXHAUSTED|85%)", "constraint", 90),
]


def scan_for_signals(text: str) -> list[Signal]:
    """Scan text for critical signals using regex (zero LLM cost).

    Returns signals sorted by priority (highest first).
    """
    signals = []
    for name, pattern, category, priority in _SIGNAL_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            signals.append(Signal(
                category=category,
                pattern_name=name,
                text=match.group(0)[:200],  # truncate long matches
                priority=priority,
            ))

    # Deduplicate by text (keep highest priority)
    seen = {}
    for sig in signals:
        key = sig.text[:50]
        if key not in seen or sig.priority > seen[key].priority:
            seen[key] = sig

    return sorted(seen.values(), key=lambda s: -s.priority)


def extract_rescue_lines(text: str, max_lines: int = 10) -> list[str]:
    """Extract lines that contain critical signals — to be pinned during compression.

    Returns up to max_lines of the most important lines.
    """
    signals = scan_for_signals(text)
    if not signals:
        return []

    # Get unique lines containing signals
    lines = text.split("\n")
    rescue = []
    rescued_indices = set()

    for sig in signals[:max_lines * 2]:  # scan more than needed
        for i, line in enumerate(lines):
            if sig.text[:30] in line and i not in rescued_indices:
                rescue.append((sig.priority, line.strip()))
                rescued_indices.add(i)
                break

    # Sort by priority, take top N
    rescue.sort(key=lambda x: -x[0])
    return [line for _, line in rescue[:max_lines]]
