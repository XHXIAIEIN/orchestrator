"""Task Tier System — per-task pricing for context budget, model, and turns."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskTier:
    name: str
    context_budget: int    # max tokens for ctx_read
    model: str
    max_turns: int
    prompt_budget: int     # max tokens for L0 prompt injection


TIERS = {
    "light":    TaskTier("light",    4_000,   "haiku",  10, 1_000),
    "standard": TaskTier("standard", 24_000,  "sonnet", 25, 4_000),
    "heavy":    TaskTier("heavy",    128_000, "opus",   50, 16_000),
}

_HEAVY_KEYWORDS = re.compile(
    r"exam|practice|clawvard|analy[zs]e|refactor.*architect|design.*review|"
    r"threat.model|security.audit|comprehensive",
    re.IGNORECASE,
)
_LIGHT_KEYWORDS = re.compile(
    r"check|status|patrol|ping|health|list|count|简单|查看|巡检",
    re.IGNORECASE,
)


def classify_task_tier(action: str, spec: dict) -> TaskTier:
    """Classify a task into light/standard/heavy tier.

    Priority: spec["tier"] override > keyword match > default (standard).
    """
    explicit = spec.get("tier", "")
    if explicit in TIERS:
        return TIERS[explicit]

    text = f"{action} {spec.get('problem', '')} {spec.get('summary', '')}"
    if _HEAVY_KEYWORDS.search(text):
        return TIERS["heavy"]
    if _LIGHT_KEYWORDS.search(text):
        return TIERS["light"]

    return TIERS["standard"]
