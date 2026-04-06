"""
Multi-Pass Model Name Normalization — reconcile model names from different sources.

Source: agentlytics Multi-Pass Model Normalization (Round 32)

Problem: Same model gets called different things:
  - API response: "claude-3-5-sonnet-20241022"
  - User input: "sonnet"
  - Config: "claude-sonnet-4-6"
  - Billing: "claude-3.5-sonnet"

Solution: 4-pass normalization with early return.
"""
from __future__ import annotations

import re

CANONICAL_MODELS = {
    "claude-opus-4-6": ["opus", "opus-4", "opus-4.6", "claude-opus"],
    "claude-sonnet-4-6": ["sonnet", "sonnet-4", "sonnet-4.6", "claude-sonnet"],
    "claude-haiku-4-5": ["haiku", "haiku-4", "haiku-4.5", "claude-haiku"],
    "claude-3-5-sonnet": ["sonnet-3.5", "claude-3.5-sonnet", "claude-3-5-sonnet-20241022"],
    "claude-3-5-haiku": ["haiku-3.5", "claude-3.5-haiku", "claude-3-5-haiku-20241022"],
    "gemma4": ["gemma", "gemma-4", "gemma4:26b", "gemma-4-26b"],
    "gemma3": ["gemma-3", "gemma3:27b"],
}

_ALIAS_MAP: dict[str, str] = {}
for canonical, aliases in CANONICAL_MODELS.items():
    _ALIAS_MAP[canonical.lower()] = canonical
    for alias in aliases:
        _ALIAS_MAP[alias.lower()] = canonical


def normalize_model_name(raw: str) -> str:
    """Normalize a model name string to canonical form.

    4-pass strategy:
    1. Exact match (fastest)
    2. Strip provider prefix (anthropic/, openai/)
    3. Strip date suffix (-20241022, -20250301)
    4. Fuzzy prefix match
    """
    if not raw:
        return raw

    cleaned = raw.strip().lower()

    # Pass 1: Exact match
    if cleaned in _ALIAS_MAP:
        return _ALIAS_MAP[cleaned]

    # Pass 2: Strip provider prefix
    for prefix in ("anthropic/", "openai/", "google/", "ollama/"):
        if cleaned.startswith(prefix):
            stripped = cleaned[len(prefix):]
            if stripped in _ALIAS_MAP:
                return _ALIAS_MAP[stripped]

    # Pass 3: Strip date suffix (-YYYYMMDD)
    no_date = re.sub(r'-\d{8}$', '', cleaned)
    if no_date in _ALIAS_MAP:
        return _ALIAS_MAP[no_date]

    # Pass 4: Fuzzy prefix match
    for alias, canonical in _ALIAS_MAP.items():
        if alias.startswith(cleaned) or cleaned.startswith(alias):
            return canonical

    return raw
