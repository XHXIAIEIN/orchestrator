# src/governance/stuck_detector.py
"""
StuckDetector — 5-pattern agent stuck detection.
Stolen from OpenHands/openhands/controller/stuck.py, adapted for Agent SDK events.
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)

# Minimum events before detection kicks in
MIN_EVENTS = 6
# How many recent events to compare
WINDOW = 4


class StuckDetector:
    """Detect when an agent is stuck in a loop.

    Six patterns:
    1. REPEATED_ACTION_OBSERVATION — same action+observation pair repeats
    2. REPEATED_ACTION_ERROR — same action keeps producing same error
    3. MONOLOGUE — agent talks to itself without tool use
    4. ACTION_OBSERVATION_CYCLE — alternating pattern repeats
    5. CONTEXT_WINDOW_LOOP — keeps hitting context limit errors
    6. SIGNATURE_REPEAT — same tool with identical input parameters 3+ times
    """

    def __init__(self, window: int = WINDOW):
        self.window = window
        self._events: list[dict] = []

    def record(self, event: dict) -> None:
        """Record an agent event (from agent_events table format)."""
        self._events.append(event)

    def is_stuck(self) -> tuple[bool, str]:
        """Check if agent is stuck. Returns (is_stuck, pattern_name)."""
        if len(self._events) < MIN_EVENTS:
            return False, ""

        recent = self._events[-self.window * 2:]

        # Pattern 1: Repeated action+observation
        if self._check_repeated_action_observation(recent):
            return True, "REPEATED_ACTION_OBSERVATION"

        # Pattern 2: Repeated action+error
        if self._check_repeated_action_error(recent):
            return True, "REPEATED_ACTION_ERROR"

        # Pattern 3: Monologue (no tool use for N turns)
        if self._check_monologue(recent):
            return True, "MONOLOGUE"

        # Pattern 4: Action-observation cycle
        if self._check_cycle(recent):
            return True, "ACTION_OBSERVATION_CYCLE"

        # Pattern 5: Context window errors
        if self._check_context_window_loop(recent):
            return True, "CONTEXT_WINDOW_LOOP"

        # Pattern 6: Signature repeat (same tool + same input)
        if self._check_signature_repeat(recent):
            return True, "SIGNATURE_REPEAT"

        return False, ""

    def _check_repeated_action_observation(self, events: list[dict]) -> bool:
        """Same tool call + same output repeating."""
        signatures = []
        for e in events:
            data = e.get("data", {})
            tools = tuple(sorted(data.get("tools", [])))
            text = data.get("text", [""])
            sig = (tools, str(text)[:200])
            signatures.append(sig)
        if len(signatures) < 3:
            return False
        return len(set(signatures[-3:])) == 1

    def _check_repeated_action_error(self, events: list[dict]) -> bool:
        """Same tool keeps producing same error."""
        errors = []
        for e in events:
            data = e.get("data", {})
            err = data.get("error")
            if err:
                tools = tuple(sorted(data.get("tools", [])))
                errors.append((tools, str(err)[:200]))
        if len(errors) < 3:
            return False
        return len(set(errors[-3:])) == 1

    def _check_monologue(self, events: list[dict]) -> bool:
        """Agent produces text without any tool calls for 4+ turns."""
        no_tool_count = 0
        for e in reversed(events):
            data = e.get("data", {})
            if data.get("tools"):
                break
            no_tool_count += 1
        return no_tool_count >= self.window

    def _check_cycle(self, events: list[dict]) -> bool:
        """A-B-A-B pattern detection."""
        if len(events) < 4:
            return False
        sigs = []
        for e in events[-4:]:
            data = e.get("data", {})
            tools = tuple(sorted(data.get("tools", [])))
            sigs.append(tools)
        return sigs[0] == sigs[2] and sigs[1] == sigs[3] and sigs[0] != sigs[1]

    def _check_context_window_loop(self, events: list[dict]) -> bool:
        """Repeated context window / token limit errors."""
        ctx_errors = 0
        for e in events[-self.window:]:
            data = e.get("data", {})
            err = str(data.get("error", "")).lower()
            if any(kw in err for kw in ("context", "token", "too long", "maximum")):
                ctx_errors += 1
        return ctx_errors >= 2

    def _check_signature_repeat(self, events: list[dict]) -> bool:
        """Same tool with same input parameters repeating 3+ times."""
        signatures = []
        for e in events:
            data = e.get("data", {})
            for tool_detail in (data.get("tools_detail") or []):
                sig = f"{tool_detail.get('tool', '')}:{tool_detail.get('input_preview', '')[:100]}"
                signatures.append(sig)
        if len(signatures) < 3:
            return False
        from collections import Counter
        counts = Counter(signatures)
        _, top_count = counts.most_common(1)[0]
        return top_count >= 3

    def reset(self) -> None:
        """Clear recorded events."""
        self._events.clear()
