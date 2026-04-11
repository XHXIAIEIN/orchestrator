"""R48 (Hermes v0.8): reasoning_effort levels for delegation cost control.

Parent tasks use xhigh/high, child tasks use low/minimal — same task,
different cognitive investment by role.

Usage::

    model, max_tokens = resolve_reasoning_effort("low", base_model="sonnet", base_tokens=4096)
    # → ("haiku", 2457)

Levels (6):
    xhigh   — opus,   100% tokens  (architect / planner)
    high    — sonnet, 100% tokens  (primary worker)
    medium  — sonnet,  80% tokens  (routine sub-task)
    low     — haiku,   60% tokens  (delegated child)
    minimal — haiku,   40% tokens  (fanout leaf)
    none    — haiku, minimal (256) (routing / triage only)
"""
from __future__ import annotations

# Map each level to (model_hint, token_fraction).
# model_hint is a simple keyword checked against the base_model string;
# if the base already satisfies the tier, it stays — we never upgrade.
_LEVELS: dict[str, tuple[str, float]] = {
    "xhigh":   ("opus",   1.00),
    "high":    ("sonnet", 1.00),
    "medium":  ("sonnet", 0.80),
    "low":     ("haiku",  0.60),
    "minimal": ("haiku",  0.40),
    "none":    ("haiku",  0.00),  # token fraction 0 → use _NONE_MAX_TOKENS floor
}

_NONE_MAX_TOKENS = 256  # hard floor for "none" level

# Model name fragments used to determine tier rank (higher index = stronger)
_MODEL_RANK = ["haiku", "sonnet", "opus"]


def _model_rank(name: str) -> int:
    """Return numeric rank for a model name. Unknown models → 1 (sonnet-tier)."""
    lower = name.lower()
    for i, fragment in enumerate(_MODEL_RANK):
        if fragment in lower:
            return i
    return 1  # default to sonnet-tier


def _apply_model_hint(hint: str, base_model: str) -> str:
    """Return a model string that satisfies hint without upgrading beyond base.

    Rules:
    - If base_model already matches or exceeds hint tier → keep base_model.
    - Otherwise → return a canonical model name built from hint keyword
      spliced into base_model's version suffix when possible.

    We don't hard-code full model IDs here; callers can post-process.
    The return value is a model *name fragment* (e.g. "haiku") when the
    base doesn't match, or the original base_model when it does.
    """
    hint_rank = _model_rank(hint)
    base_rank = _model_rank(base_model)

    if base_rank <= hint_rank:
        # base already at or below required tier (cheaper/equal) → keep it
        return base_model

    # base is stronger than hint → downgrade to hint tier
    # Try to preserve version suffix (e.g. "claude-3-5-sonnet-20241022" → swap "sonnet" → "haiku")
    lower = base_model.lower()
    for fragment in _MODEL_RANK:
        if fragment in lower:
            return base_model.lower().replace(fragment, hint)

    # Can't splice — return the hint keyword as-is; caller resolves full name
    return hint


def resolve_reasoning_effort(
    level: str,
    base_model: str,
    base_tokens: int,
) -> tuple[str, int]:
    """Map a reasoning_effort level to (model, max_tokens).

    Args:
        level: one of xhigh / high / medium / low / minimal / none.
               Unknown values are silently treated as "medium".
        base_model: the model the caller would otherwise use (e.g. "claude-sonnet-4-5").
        base_tokens: the token budget the caller would otherwise pass.

    Returns:
        (model, max_tokens) — model may be the same as base_model or downgraded.
    """
    if level not in _LEVELS:
        level = "medium"

    model_hint, fraction = _LEVELS[level]
    model = _apply_model_hint(model_hint, base_model)

    if level == "none":
        max_tokens = _NONE_MAX_TOKENS
    else:
        max_tokens = max(1, int(base_tokens * fraction))

    return model, max_tokens
