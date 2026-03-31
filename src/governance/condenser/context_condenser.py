# src/governance/condenser/context_condenser.py
"""Thin orchestrator that chains condenser strategies on assembled prompt text.

Bridges the string-based executor_prompt world to the View/Event-based
condenser subsystem. Configurable per-department via manifest.yaml.

Usage in executor_prompt.py:
    prompt = condense_context(prompt, dept_key, manifest_config)
"""
from __future__ import annotations

import logging
from typing import Optional

from .base import Event, View
from .amortized_forgetting import AmortizedForgettingCondenser
from .llm_summarizing import LLMSummarizingCondenser
from .water_level import WaterLevelCondenser
from .pipeline import CondenserPipeline

log = logging.getLogger(__name__)

# ── Defaults ──
DEFAULT_MAX_TOKENS = 128_000
DEFAULT_HIGH_WATER = 0.85
DEFAULT_LOW_WATER = 0.60
DEFAULT_AMORTIZED_MAX_EVENTS = 100
DEFAULT_AMORTIZED_KEEP_HEAD = 10
DEFAULT_AMORTIZED_KEEP_TAIL = 30
DEFAULT_LLM_THRESHOLD = 60
DEFAULT_LLM_KEEP_HEAD = 8
DEFAULT_LLM_KEEP_TAIL = 20


def _prompt_to_view(prompt: str) -> View:
    """Split a prompt string into section-based Events for condenser processing.

    Splits on markdown H2 headers (## ...) to create logical sections.
    Each section becomes an Event. This preserves structure while giving
    the condenser meaningful units to compress.
    """
    import re
    sections = re.split(r'(?=^## )', prompt, flags=re.MULTILINE)
    events = []
    for i, section in enumerate(sections):
        section = section.strip()
        if not section:
            continue
        events.append(Event(
            id=i,
            event_type="context",
            source="prompt_section",
            content=section,
            metadata={"section_index": i},
        ))
    # If no sections were found (no ## headers), treat as single event
    if not events and prompt.strip():
        events.append(Event(
            id=0,
            event_type="context",
            source="prompt_full",
            content=prompt.strip(),
        ))
    return View(events)


def _view_to_prompt(view: View) -> str:
    """Reassemble a View back into a prompt string."""
    parts = [e.content for e in view.events]
    return "\n\n".join(parts)


def _build_pipeline(config: dict) -> WaterLevelCondenser:
    """Build the condenser pipeline from config dict.

    The pipeline is:
      WaterLevel gate → (AmortizedForgetting → LLMSummarizing)

    WaterLevel acts as the outer gate: if context is under threshold,
    nothing happens. If over, the inner pipeline runs:
      1. AmortizedForgetting to drop stale middle sections
      2. LLMSummarizing to compress the longest remaining sections
    """
    amortized = AmortizedForgettingCondenser(
        max_events=config.get("amortized_max_events", DEFAULT_AMORTIZED_MAX_EVENTS),
        keep_head=config.get("amortized_keep_head", DEFAULT_AMORTIZED_KEEP_HEAD),
        keep_tail=config.get("amortized_keep_tail", DEFAULT_AMORTIZED_KEEP_TAIL),
    )

    llm_fn = config.get("llm_fn", None)
    llm_summarizer = LLMSummarizingCondenser(
        llm_fn=llm_fn,
        threshold=config.get("llm_threshold", DEFAULT_LLM_THRESHOLD),
        keep_head=config.get("llm_keep_head", DEFAULT_LLM_KEEP_HEAD),
        keep_tail=config.get("llm_keep_tail", DEFAULT_LLM_KEEP_TAIL),
    )

    inner = CondenserPipeline([amortized, llm_summarizer])

    return WaterLevelCondenser(
        inner=inner,
        max_tokens=config.get("max_tokens", DEFAULT_MAX_TOKENS),
        high_water=config.get("high_water", DEFAULT_HIGH_WATER),
        low_water=config.get("low_water", DEFAULT_LOW_WATER),
    )


def condense_context(
    prompt: str,
    dept_key: str = "",
    config: Optional[dict] = None,
) -> str:
    """Run the condenser pipeline on an assembled prompt string.

    Args:
        prompt: The fully assembled execution prompt.
        dept_key: Department key (for logging).
        config: Optional condenser config from manifest.yaml.
            Keys: enabled, max_tokens, high_water, low_water,
                  amortized_max_events, amortized_keep_head, amortized_keep_tail,
                  llm_threshold, llm_keep_head, llm_keep_tail, llm_fn

    Returns:
        The (possibly compressed) prompt string.
    """
    config = config or {}

    # Check if condenser is enabled (default: True)
    if not config.get("enabled", True):
        return prompt

    try:
        pipeline = _build_pipeline(config)
        view = _prompt_to_view(prompt)
        result = pipeline.condense(view)

        # If condensed (view changed), log it
        if len(result) != len(view):
            log.info(
                f"Condenser[{dept_key}]: {len(view)} sections → {len(result)} sections "
                f"(tokens: {view.token_estimate()} → {result.token_estimate()})"
            )

        return _view_to_prompt(result)

    except Exception as e:
        log.warning(f"Condenser[{dept_key}]: failed ({e}), returning original prompt")
        return prompt
