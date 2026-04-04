# src/governance/stuck_detector.py
"""
StuckDetector — 9-pattern agent stuck detection.

Original 6 patterns from OpenHands/openhands/controller/stuck.py.
Patterns 7-9 stolen from OpenFang loop_guard.rs:
  - Result-aware detection (same call + same result = method isn't working)
  - Ping-pong detection (A-B-A-B-A-B in sliding window)
  - Poll tool recognition (docker ps / kubectl get get relaxed thresholds)
"""
from __future__ import annotations

import hashlib
import logging
from collections import Counter

log = logging.getLogger(__name__)

# Minimum events before detection kicks in
MIN_EVENTS = 6
# How many recent events to compare
WINDOW = 4

# ── OpenFang-style loop guard config ──
RESULT_WARN_THRESHOLD = 3       # 同 call+result 重复 N 次 → warn
RESULT_BLOCK_THRESHOLD = 5      # 同 call+result 重复 N 次 → block
GLOBAL_CIRCUIT_BREAKER = 30     # 总调用次数熔断
POLL_MULTIPLIER = 3             # 轮询工具阈值倍增
PINGPONG_WINDOW = 30            # ping-pong 检测的滑动窗口

# 轮询关键词 — 这些工具调用虽然重复但属于正常监控
POLL_KEYWORDS = frozenset({
    "status", "poll", "wait", "watch", "docker ps", "kubectl get",
    "git status", "nvidia-smi", "systemctl", "journalctl", "tail",
})


class StuckDetector:
    """Detect when an agent is stuck in a loop.

    Nine patterns:
    1. REPEATED_ACTION_OBSERVATION — same action+observation pair repeats
    2. REPEATED_ACTION_ERROR — same action keeps producing same error
    3. MONOLOGUE — agent talks to itself without tool use
    4. ACTION_OBSERVATION_CYCLE — alternating pattern repeats (basic A-B-A-B)
    5. CONTEXT_WINDOW_LOOP — keeps hitting context limit errors
    6. SIGNATURE_REPEAT — same tool with identical input parameters 3+ times
    7. RESULT_AWARE_REPEAT — same call + same result (method isn't working) [OpenFang]
    8. PINGPONG_CYCLE — A-B-A-B or A-B-C-A-B-C in sliding window [OpenFang]
    9. CIRCUIT_BREAKER — total tool calls exceed global limit [OpenFang]
    """

    def __init__(self, window: int = WINDOW):
        self.window = window
        self._events: list[dict] = []
        # OpenFang-style: track (call_hash, result_hash) pairs
        self._call_result_pairs: list[tuple[str, str]] = []
        # Total tool call count for circuit breaker
        self._total_tool_calls: int = 0
        # Persistent counters — survive reset()
        self._persistent_failures: dict[str, int] = {}  # pattern_name → cumulative count
        self._persistent_signatures: set[str] = set()   # tool signatures that have failed before

    def record(self, event: dict, tool_result: str = "") -> None:
        """Record an agent event.

        Args:
            event: Agent event dict with data.tools, data.text, data.error etc.
            tool_result: The actual tool output text (for result-aware detection).
        """
        self._events.append(event)

        # Track call+result pairs for result-aware detection
        data = event.get("data", {})
        tools = data.get("tools", [])
        if tools:
            self._total_tool_calls += len(tools)
            call_sig = _hash_sig(str(sorted(tools)) + str(data.get("tools_detail", ""))[:200])
            result_sig = _hash_sig(tool_result[:2000]) if tool_result else _hash_sig(str(data.get("text", ""))[:500])
            self._call_result_pairs.append((call_sig, result_sig))

    def is_stuck(self) -> tuple[bool, str]:
        """Check if agent is stuck. Returns (is_stuck, pattern_name)."""
        if len(self._events) < MIN_EVENTS:
            return False, ""

        recent = self._events[-self.window * 2:]

        # ── Pattern 9: Circuit breaker (check first — cheapest) ──
        if self._check_circuit_breaker():
            self._record_persistent("CIRCUIT_BREAKER")
            return True, "CIRCUIT_BREAKER"

        # ── Pattern 7: Result-aware repeat [OpenFang] ──
        stuck, is_poll = self._check_result_aware_repeat()
        if stuck:
            self._record_persistent("RESULT_AWARE_REPEAT")
            return True, "RESULT_AWARE_REPEAT"

        # ── Pattern 8: Ping-pong cycle [OpenFang] ──
        if self._check_pingpong_cycle():
            self._record_persistent("PINGPONG_CYCLE")
            return True, "PINGPONG_CYCLE"

        # ── Original patterns ──

        # Pattern 1: Repeated action+observation
        if self._check_repeated_action_observation(recent):
            self._record_persistent("REPEATED_ACTION_OBSERVATION")
            return True, "REPEATED_ACTION_OBSERVATION"

        # Pattern 2: Repeated action+error
        if self._check_repeated_action_error(recent):
            self._record_persistent("REPEATED_ACTION_ERROR")
            return True, "REPEATED_ACTION_ERROR"

        # Pattern 3: Monologue (no tool use for N turns)
        if self._check_monologue(recent):
            self._record_persistent("MONOLOGUE")
            return True, "MONOLOGUE"

        # Pattern 4: Action-observation cycle (basic)
        if self._check_cycle(recent):
            self._record_persistent("ACTION_OBSERVATION_CYCLE")
            return True, "ACTION_OBSERVATION_CYCLE"

        # Pattern 5: Context window errors
        if self._check_context_window_loop(recent):
            self._record_persistent("CONTEXT_WINDOW_LOOP")
            return True, "CONTEXT_WINDOW_LOOP"

        # Pattern 6: Signature repeat (same tool + same input)
        if self._check_signature_repeat(recent):
            self._record_persistent("SIGNATURE_REPEAT")
            return True, "SIGNATURE_REPEAT"

        return False, ""

    def _record_persistent(self, pattern_name: str) -> None:
        """Increment persistent failure counter for a pattern."""
        self._persistent_failures[pattern_name] = self._persistent_failures.get(pattern_name, 0) + 1

    # ── New patterns from OpenFang ──

    def _check_result_aware_repeat(self) -> tuple[bool, bool]:
        """Pattern 7: Same call + same result = method isn't working.

        Key insight from OpenFang: if the RESULT is also the same, the agent is
        repeating a failed approach. If results differ (e.g. polling docker ps),
        that's legitimate monitoring.

        Returns (is_stuck, is_poll_tool).
        """
        if len(self._call_result_pairs) < 3:
            return False, False

        recent_pairs = self._call_result_pairs[-RESULT_BLOCK_THRESHOLD:]
        pair_counts = Counter(recent_pairs)
        if not pair_counts:
            return False, False

        (top_call, top_result), top_count = pair_counts.most_common(1)[0]

        # Check if this is a poll tool (relaxed threshold)
        is_poll = self._is_poll_tool(top_call)
        threshold = RESULT_BLOCK_THRESHOLD * POLL_MULTIPLIER if is_poll else RESULT_BLOCK_THRESHOLD

        # Same call + same result N times = stuck
        if top_count >= threshold:
            return True, is_poll

        # Same call but different results = not stuck (legitimate polling)
        call_only_counts = Counter(c for c, r in self._call_result_pairs[-RESULT_BLOCK_THRESHOLD:])
        top_call_sig, call_count = call_only_counts.most_common(1)[0]
        if call_count >= RESULT_BLOCK_THRESHOLD:
            # Same call many times, but are results varying?
            results_for_call = [r for c, r in self._call_result_pairs if c == top_call_sig]
            unique_results = len(set(results_for_call[-RESULT_BLOCK_THRESHOLD:]))
            if unique_results == 1:
                # All same results = stuck
                return True, is_poll
            # Different results = probably polling, allow it
            pass

        return False, is_poll

    def _check_pingpong_cycle(self) -> bool:
        """Pattern 8: Detect A-B-A-B or A-B-C-A-B-C alternating patterns.

        OpenFang searches the last PINGPONG_WINDOW calls for repeating subsequences
        of length 2 or 3, requiring 3+ full repetitions to trigger.
        """
        if len(self._call_result_pairs) < 6:
            return False

        recent_calls = [c for c, r in self._call_result_pairs[-PINGPONG_WINDOW:]]

        # Check period-2 (A-B-A-B-A-B)
        if self._find_repeating_pattern(recent_calls, period=2, min_repeats=3):
            return True

        # Check period-3 (A-B-C-A-B-C-A-B-C)
        if self._find_repeating_pattern(recent_calls, period=3, min_repeats=3):
            return True

        return False

    def _find_repeating_pattern(self, seq: list[str], period: int, min_repeats: int) -> bool:
        """Find a repeating subsequence of given period length."""
        if len(seq) < period * min_repeats:
            return False

        # Slide a window and check if the pattern repeats
        for start in range(len(seq) - period * min_repeats + 1):
            pattern = tuple(seq[start:start + period])
            repeats = 1
            pos = start + period
            while pos + period <= len(seq):
                if tuple(seq[pos:pos + period]) == pattern:
                    repeats += 1
                    pos += period
                else:
                    break
            if repeats >= min_repeats and len(set(pattern)) > 1:
                return True
        return False

    def _check_circuit_breaker(self) -> bool:
        """Pattern 9: Total tool calls exceed global limit."""
        return self._total_tool_calls >= GLOBAL_CIRCUIT_BREAKER

    def _is_poll_tool(self, call_hash: str) -> bool:
        """Check if a call looks like a polling/monitoring operation."""
        # Check against recent events for poll keywords
        for e in reversed(self._events[-5:]):
            data = e.get("data", {})
            for td in (data.get("tools_detail") or []):
                preview = str(td.get("input_preview", "")).lower()
                tool = str(td.get("tool", "")).lower()
                if any(kw in preview or kw in tool for kw in POLL_KEYWORDS):
                    return True
        return False

    # ── Original patterns (unchanged) ──

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
        """A-B-A-B pattern detection (basic — Pattern 8 is the advanced version)."""
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
        """Same tool with same input parameters repeating 3+ times.

        Poll-aware: monitoring tools (docker ps, kubectl get, etc.) get
        POLL_MULTIPLIER × the normal threshold.
        """
        signatures = []
        for e in events:
            data = e.get("data", {})
            for tool_detail in (data.get("tools_detail") or []):
                sig = f"{tool_detail.get('tool', '')}:{tool_detail.get('input_preview', '')[:100]}"
                signatures.append(sig)
        if len(signatures) < 3:
            return False
        counts = Counter(signatures)
        top_sig, top_count = counts.most_common(1)[0]
        # Poll tools get relaxed threshold
        threshold = 3
        if any(kw in top_sig.lower() for kw in POLL_KEYWORDS):
            threshold = 3 * POLL_MULTIPLIER
        return top_count >= threshold

    def reset(self) -> None:
        """Reset transient state for new attempt. Persistent counters survive."""
        self._events.clear()
        self._call_result_pairs.clear()
        self._total_tool_calls = 0
        # NOTE: _persistent_failures and _persistent_signatures are NOT cleared

    def should_escalate(self) -> tuple[bool, str]:
        """Check if persistent failures warrant strategy escalation.

        Returns (should_escalate, reason).
        Thresholds: 3× same pattern → NUDGE, 5× → STRATEGY_SWITCH.
        """
        for pattern, count in self._persistent_failures.items():
            if count >= 5:
                return True, f"{pattern} failed {count}× — force strategy switch"
            if count >= 3:
                return True, f"{pattern} failed {count}× — nudge"
        return False, ""

    def record_failed_signature(self, signature: str) -> None:
        """Record a tool call signature that led to failure."""
        self._persistent_signatures.add(signature)

    def has_failed_before(self, signature: str) -> bool:
        """Check if this exact tool call has failed in a previous attempt."""
        return signature in self._persistent_signatures

    def get_failure_summary(self) -> dict:
        """Return persistent failure stats for logging/debugging."""
        return {
            "pattern_counts": dict(self._persistent_failures),
            "known_bad_signatures": len(self._persistent_signatures),
        }


class NegativeFeedbackTracker:
    """Track failed approaches and apply negative weights (R14 steal).

    When the same error path repeats 3+ times, force strategy switch.
    Maintains a dict of approach_key -> failure_count.
    """

    def __init__(self, force_switch_threshold: int = 3):
        self._threshold = force_switch_threshold
        self._failures: dict[str, int] = {}
        self._error_summaries: dict[str, str] = {}

    def record_failure(self, approach_key: str, error_summary: str = "") -> int:
        """Record a failure for an approach. Returns new failure count."""
        self._failures[approach_key] = self._failures.get(approach_key, 0) + 1
        if error_summary:
            self._error_summaries[approach_key] = error_summary
        count = self._failures[approach_key]
        if count >= self._threshold:
            log.warning("negative_feedback: %s failed %d× (threshold=%d) — force switch",
                        approach_key, count, self._threshold)
        return count

    def record_success(self, approach_key: str) -> None:
        """Reset failure count for a successful approach."""
        self._failures.pop(approach_key, None)
        self._error_summaries.pop(approach_key, None)

    def should_force_switch(self, approach_key: str) -> bool:
        """True if failure count >= threshold."""
        return self._failures.get(approach_key, 0) >= self._threshold

    def get_failed_approaches(self) -> dict[str, int]:
        """Return all tracked failures {approach_key: count}."""
        return dict(self._failures)

    def suggest_alternative(self, current_approach: str) -> str:
        """Return a text suggestion for switching strategy."""
        approach_lower = current_approach.lower()
        if any(kw in approach_lower for kw in ("edit", "file", "write", "patch")):
            return "Try a different file or approach"
        if any(kw in approach_lower for kw in ("command", "cmd", "run", "exec", "bash")):
            return "Try a different command or tool"
        return "Switch to a fundamentally different strategy"

    def reset(self) -> None:
        """Clear all tracking."""
        self._failures.clear()
        self._error_summaries.clear()


def _hash_sig(text: str) -> str:
    """SHA-256 短哈希，用于去重比较。"""
    return hashlib.sha256(text.encode()).hexdigest()[:16]
