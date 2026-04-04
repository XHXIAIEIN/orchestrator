# src/governance/condenser/configurable.py
"""Configurable Summarization Triggers (R29 — stolen from bytedance/deer-flow).

Multiple trigger sources with OR logic:
  - token_count: compress when tokens exceed limit
  - message_count: compress when messages exceed limit
  - fraction: compress when context usage exceeds fraction of max

Configurable retention policies:
  - keep_recent_n: keep last N messages uncompressed
  - keep_recent_tokens: keep last T tokens uncompressed
  - keep_system: always keep system messages

Replaces hard-coded thresholds with YAML-configurable triggers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .base import Condenser, Event, View

log = logging.getLogger(__name__)


@dataclass
class ConfigurableTrigger:
    """A single trigger condition. Any one firing is enough to compress."""

    token_limit: int | None = None
    message_limit: int | None = None
    fraction_limit: float | None = None  # 0.0–1.0, fraction of max context
    max_context: int = 200_000  # for fraction calculation


@dataclass
class RetentionPolicy:
    """What to keep uncompressed during condensation."""

    keep_recent_n: int = 5
    keep_recent_tokens: int = 2000
    keep_system: bool = True


class ConfigurableCondenser(Condenser):
    """Context condenser with pluggable trigger/retention configuration.

    Triggers are evaluated with OR logic — if *any* trigger fires, condensation
    runs. Retention policy controls what survives compression.
    """

    def __init__(
        self,
        triggers: list[ConfigurableTrigger] | None = None,
        retention: RetentionPolicy | None = None,
        llm_fn=None,
    ):
        self.triggers = triggers or [ConfigurableTrigger(token_limit=100_000)]
        self.retention = retention or RetentionPolicy()
        self.llm_fn = llm_fn  # optional: fn(prompt) -> str
        self._compress_count = 0

    # ── Trigger evaluation ───────────────────────────────────────────

    def should_trigger(self, view: View) -> bool:
        """Return True if ANY trigger fires (OR logic)."""
        for t in self.triggers:
            if t.token_limit is not None and view.token_estimate() > t.token_limit:
                log.debug(
                    "ConfigurableCondenser: token trigger fired "
                    f"({view.token_estimate()} > {t.token_limit})"
                )
                return True
            if t.message_limit is not None and len(view) > t.message_limit:
                log.debug(
                    "ConfigurableCondenser: message trigger fired "
                    f"({len(view)} > {t.message_limit})"
                )
                return True
            if t.fraction_limit is not None:
                usage = view.token_estimate() / t.max_context
                if usage > t.fraction_limit:
                    log.debug(
                        "ConfigurableCondenser: fraction trigger fired "
                        f"({usage:.2%} > {t.fraction_limit:.0%})"
                    )
                    return True
        return False

    # ── Condense ─────────────────────────────────────────────────────

    def condense(self, view: View) -> View:
        """Compress if triggered, otherwise pass through unchanged."""
        if not self.should_trigger(view):
            return view

        events = view.events
        before_tokens = view.token_estimate()

        # Partition: system messages + retained tail + compressible middle
        system_events: list[Event] = []
        non_system: list[Event] = []
        for e in events:
            if self.retention.keep_system and e.event_type == "system":
                system_events.append(e)
            else:
                non_system.append(e)

        # Determine how many recent events to keep
        keep_n = self._resolve_keep_count(non_system)
        if keep_n >= len(non_system):
            # Nothing to compress — retention policy covers everything
            return view

        compressible = non_system[:-keep_n] if keep_n > 0 else non_system
        retained_tail = non_system[-keep_n:] if keep_n > 0 else []

        # Build summary
        summary_text = self._summarize(compressible)
        summary_event = Event(
            id=-1,
            event_type="system",
            source="condenser:configurable",
            content=summary_text,
            metadata={
                "condensed_count": len(compressible),
                "strategy": "configurable",
            },
            condensed=True,
        )

        result = View(system_events + [summary_event] + retained_tail)
        self._compress_count += 1

        log.info(
            f"ConfigurableCondenser: {len(events)} events / {before_tokens} tokens "
            f"→ {len(result)} events / {result.token_estimate()} tokens "
            f"(compressions: {self._compress_count})"
        )
        return result

    # ── Internals ────────────────────────────────────────────────────

    def _resolve_keep_count(self, events: list[Event]) -> int:
        """Determine how many trailing events to keep, respecting both N and token limits."""
        keep = min(self.retention.keep_recent_n, len(events))

        # Also respect token budget — walk backwards
        token_budget = self.retention.keep_recent_tokens
        token_acc = 0
        for i in range(len(events) - 1, -1, -1):
            est = int(len(events[i].content) / 3.5)
            if token_acc + est > token_budget:
                # keep at most (len - i - 1) by token budget
                token_keep = len(events) - i - 1
                keep = min(keep, token_keep)
                break
            token_acc += est

        return max(keep, 1)  # always keep at least 1

    def _summarize(self, events: list[Event]) -> str:
        """Delegate to LLM if available, otherwise truncation fallback."""
        if self.llm_fn:
            try:
                events_text = "\n".join(
                    f"[{e.event_type}:{e.source}] {e.content[:200]}" for e in events
                )
                prompt = (
                    "Compress these context events into a concise summary. "
                    "Keep key decisions, errors, and outcomes. Drop redundancy.\n\n"
                    f"{events_text[:4000]}"
                )
                result = self.llm_fn(prompt)
                if result and len(result) > 20:
                    return f"## Context Summary\n{result}\n---"
            except Exception as exc:
                log.warning(f"ConfigurableCondenser LLM failed, falling back: {exc}")

        # Fallback: truncation-based summary
        return self._truncation_summary(events)

    @staticmethod
    def _truncation_summary(events: list[Event]) -> str:
        """Mechanical fallback: keep first line of each event, cap total."""
        lines = [f"## Context Summary\n[{len(events)} events compressed]"]
        for e in events[:20]:
            first_line = e.content.split("\n", 1)[0][:120]
            lines.append(f"- [{e.event_type}] {first_line}")
        if len(events) > 20:
            lines.append(f"  ... and {len(events) - 20} more")
        lines.append("---")
        return "\n".join(lines)

    @property
    def compress_count(self) -> int:
        return self._compress_count
