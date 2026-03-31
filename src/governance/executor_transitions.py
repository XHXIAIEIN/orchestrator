"""Executor Transition State Machine — continue sites for execution loop.

Stolen from Claude Code v2.1.88's 9 "continue sites" pattern:
Instead of a flat retry loop with two outcomes (success/retry), the executor
loop checks state.transition at each iteration. Each transition type maps to
a well-defined recovery path, making error recovery auditable, testable, and
extensible.

Before this module, executor.py had:
  - success → break
  - retryable failure → backoff + continue
  - non-retryable → break

After this module, the loop can express 9 distinct transitions, each with
its own recovery action. The old _classify_failure() output maps cleanly
to the new Transition enum (see CLASSIFY_FAILURE_MAP below).

Integration: this module is standalone. executor.py integration comes later.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


# ── Transition Enum ──────────────────────────────────────────────────────


class Transition(Enum):
    """Execution state transitions — stolen from Claude Code v2.1.88 continue sites.

    Instead of nested try-catch, the executor loop checks state.transition
    at each iteration. Each transition type has a well-defined recovery path.
    This makes error recovery auditable, testable, and extensible.

    The 9 transitions cover the full space of execution outcomes:
      NORMAL            — success, exit loop
      RETRY             — transient failure, backoff and retry
      ESCALATE          — non-recoverable, hand off to Governor/human
      REACTIVE_COMPACT  — context overflow, compress and retry (circuit-breaker gated)
      PERMISSION_DENIED — tool blocked, degrade to read-only
      BUDGET_EXCEEDED   — cost/token limit hit, downgrade model or stop
      STUCK             — agent not making progress, inject nudge prompt
      DRIFT             — agent drifting from task, refocus
      REWORK            — quality review failed, retry with feedback
    """
    NORMAL = "normal"
    RETRY = "retry"
    ESCALATE = "escalate"
    REACTIVE_COMPACT = "reactive_compact"
    PERMISSION_DENIED = "permission_denied"
    BUDGET_EXCEEDED = "budget_exceeded"
    STUCK = "stuck"
    DRIFT = "drift"
    REWORK = "rework"


# ── Bridge: _classify_failure output → Transition ────────────────────────
# executor.py's _classify_failure returns strings like "timeout", "stuck",
# "cost_limit", etc. This map bridges old classification to new transitions.

CLASSIFY_FAILURE_MAP: dict[str, Transition] = {
    "timeout": Transition.RETRY,
    "stuck": Transition.STUCK,
    "cost_limit": Transition.BUDGET_EXCEEDED,
    "unresponsive": Transition.RETRY,
    "rate_limited": Transition.RETRY,
    "transient_server_error": Transition.RETRY,
    "unknown": Transition.ESCALATE,
}


def transition_from_failure_type(failure_type: str) -> Transition:
    """Convert _classify_failure() output to a Transition.

    Falls back to ESCALATE for unknown failure types — the safe default
    is to escalate rather than silently retry.
    """
    return CLASSIFY_FAILURE_MAP.get(failure_type, Transition.ESCALATE)


# ── Execution State ──────────────────────────────────────────────────────


@dataclass
class ExecutionState:
    """Mutable state carried across loop iterations.

    Each field tracks a different concern. The transition field
    determines which branch the loop takes on the next iteration.
    """
    transition: Transition = Transition.NORMAL
    attempt: int = 0
    max_attempts: int = 2

    # Retry tracking
    consecutive_failures: int = 0
    last_failure_type: str = ""
    backoff_seconds: float = 5.0

    # ── Compaction tracking (Circuit Breaker — Claude Code pattern) ──
    # When context overflows, the executor compresses and retries. But if
    # compaction itself keeps failing (e.g., the task inherently needs more
    # context than the model supports), we need a circuit breaker to stop
    # the compress-retry-compress loop.
    #
    # Circuit breaker states:
    #   compaction_failures < max_compaction_failures → CLOSED (allow compaction)
    #   compaction_failures >= max_compaction_failures → OPEN (escalate instead)
    #
    # The breaker is one-way per execution: once tripped, it stays open.
    # A new task execution starts with a fresh state (breaker reset).
    compaction_failures: int = 0
    max_compaction_failures: int = 3

    # Budget tracking
    total_cost: float = 0.0
    cost_limit: float = 0.0

    # Drift tracking
    drift_score: float = 0.0

    # Rework feedback (from quality review)
    rework_feedback: str = ""

    # Output from last attempt
    last_output: str = ""
    last_exception: BaseException | None = field(default=None, repr=False)


# ── Transition Resolver ──────────────────────────────────────────────────


class TransitionResolver:
    """Classifies execution outcomes into transitions and returns recovery actions.

    Replaces the flat _classify_failure() → retry_conditions check with a richer
    classification that maps to specific recovery paths. Each transition has a
    well-defined recovery action returned by get_recovery_action().
    """

    def resolve(
        self,
        output: str,
        exc: BaseException | None = None,
        state: ExecutionState | None = None,
        response: Any = None,
    ) -> Transition:
        """Determine the next transition based on execution outcome.

        Priority order (higher priority wins):
          1. Success → NORMAL (break loop)
          2. Budget exceeded → BUDGET_EXCEEDED
          3. Permission denied → PERMISSION_DENIED
          4. Context overflow → REACTIVE_COMPACT (if circuit breaker allows)
          5. Stuck/doom loop → STUCK
          6. Drift detected → DRIFT
          7. Rework requested → REWORK
          8. Transient error → RETRY (if attempts remain)
          9. All else → ESCALATE

        Args:
            output: Text output from the agent execution.
            exc: Exception raised during execution, if any.
            state: Current execution state for context-aware decisions.
            response: Raw agent response object, if available.

        Returns:
            The Transition to take on the next loop iteration.
        """
        if state is None:
            state = ExecutionState()

        lower = output.lower() if output else ""

        # 1. Success — agent produced usable output without error
        if exc is None and response is not None:
            status = getattr(response, "status", None)
            if status == "done":
                return Transition.NORMAL

        # 2. Budget exceeded
        if state.total_cost >= state.cost_limit > 0:
            return Transition.BUDGET_EXCEEDED
        if "cost limit" in lower:
            return Transition.BUDGET_EXCEEDED
        if exc is not None and type(exc).__name__ == "CostLimitExceededError":
            return Transition.BUDGET_EXCEEDED

        # 3. Permission denied
        if "permission denied" in lower or "tool blocked" in lower:
            return Transition.PERMISSION_DENIED

        # 4. Context overflow → REACTIVE_COMPACT (circuit breaker gated)
        if "context" in lower and ("overflow" in lower or "too large" in lower or "exceeded" in lower):
            if state.compaction_failures < state.max_compaction_failures:
                return Transition.REACTIVE_COMPACT
            else:
                # Circuit breaker tripped — compaction loop detected
                log.warning(
                    "TransitionResolver: compaction circuit breaker OPEN "
                    f"({state.compaction_failures}/{state.max_compaction_failures}), escalating"
                )
                return Transition.ESCALATE

        # 5. Stuck / doom loop
        if "[STUCK:" in output or "[DOOM LOOP:" in output:
            return Transition.STUCK
        if state.consecutive_failures >= 3:
            return Transition.STUCK

        # 6. Drift detected
        if state.drift_score > 0.6:
            return Transition.DRIFT

        # 7. Rework (quality review injected feedback)
        if state.rework_feedback:
            return Transition.REWORK

        # 8. Transient errors → RETRY
        if "timeout" in lower or "[WATCHDOG:" in output:
            return Transition.RETRY
        if "rate limit" in lower:
            return Transition.RETRY
        if "unresponsive" in lower:
            return Transition.RETRY
        if exc is not None:
            type_name = type(exc).__name__
            if "Timeout" in type_name or "Connection" in type_name:
                return Transition.RETRY

        # 9. Unknown failure → escalate (safe default)
        if exc is not None or (output and "error" in lower):
            return Transition.ESCALATE

        # No failure detected — treat as success
        return Transition.NORMAL

    def get_recovery_action(self, transition: Transition, state: ExecutionState) -> dict:
        """Return the recovery action for a transition.

        Returns:
            dict with keys:
              - action: str (e.g., "backoff", "compress", "degrade", "nudge", "escalate")
              - params: dict (transition-specific parameters)
              - description: str (human-readable explanation for audit log)
        """
        actions: dict[Transition, dict] = {
            Transition.NORMAL: {
                "action": "none",
                "params": {},
                "description": "Execution succeeded",
            },
            Transition.RETRY: {
                "action": "backoff",
                "params": {
                    "seconds": state.backoff_seconds * (2 ** state.consecutive_failures),
                },
                "description": (
                    f"Transient failure ({state.last_failure_type}), "
                    f"retrying after backoff"
                ),
            },
            Transition.REACTIVE_COMPACT: {
                "action": "compress",
                "params": {"strategy": "session_memory_first"},
                "description": (
                    f"Context overflow, compacting "
                    f"(attempt {state.compaction_failures + 1}/{state.max_compaction_failures})"
                ),
            },
            Transition.PERMISSION_DENIED: {
                "action": "degrade",
                "params": {"new_tier": "BASIC"},
                "description": "Tool blocked by permission gate, degrading to read-only",
            },
            Transition.BUDGET_EXCEEDED: {
                "action": "downgrade_or_stop",
                "params": {"remaining": state.cost_limit - state.total_cost},
                "description": "Budget exceeded, downgrading model or stopping",
            },
            Transition.STUCK: {
                "action": "nudge",
                "params": {"inject_prompt": True},
                "description": (
                    f"Agent stuck (consecutive_failures={state.consecutive_failures}), "
                    f"injecting nudge"
                ),
            },
            Transition.DRIFT: {
                "action": "refocus",
                "params": {"drift_score": state.drift_score},
                "description": (
                    f"Agent drifting (score={state.drift_score:.2f}), "
                    f"refocusing on original task"
                ),
            },
            Transition.REWORK: {
                "action": "retry_with_feedback",
                "params": {"feedback": state.rework_feedback},
                "description": "Quality review failed, retrying with rework feedback",
            },
            Transition.ESCALATE: {
                "action": "escalate",
                "params": {},
                "description": f"Non-recoverable failure: {state.last_failure_type}",
            },
        }
        return actions.get(transition, {
            "action": "unknown",
            "params": {},
            "description": f"Unknown transition: {transition.value}",
        })

    def should_continue(self, state: ExecutionState) -> bool:
        """Whether the executor loop should continue iterating.

        Terminal conditions (return False):
          - NORMAL: success, exit loop
          - ESCALATE: non-recoverable, Governor handles
          - Attempts exhausted
          - REACTIVE_COMPACT with circuit breaker tripped

        All other transitions: continue loop.
        """
        if state.transition == Transition.NORMAL:
            return False
        if state.transition == Transition.ESCALATE:
            return False
        if state.attempt >= state.max_attempts:
            return False
        if state.transition == Transition.REACTIVE_COMPACT:
            # Circuit breaker: stop if compaction keeps failing
            return state.compaction_failures < state.max_compaction_failures
        return True

    def apply_transition(self, state: ExecutionState) -> dict:
        """Apply a transition to the state and return the recovery action.

        Updates state counters (attempt, consecutive_failures, compaction_failures)
        based on the current transition, then returns get_recovery_action().

        This is the main entry point for the executor loop:
            action = resolver.apply_transition(state)
            if not resolver.should_continue(state):
                break
            # ... execute action["action"]
        """
        state.attempt += 1

        if state.transition == Transition.NORMAL:
            state.consecutive_failures = 0
            return self.get_recovery_action(state.transition, state)

        # All non-NORMAL transitions are failures
        state.consecutive_failures += 1

        if state.transition == Transition.REACTIVE_COMPACT:
            state.compaction_failures += 1

        action = self.get_recovery_action(state.transition, state)

        log.info(
            "ExecutorTransition: attempt=%d transition=%s action=%s — %s",
            state.attempt, state.transition.value, action["action"], action["description"],
        )

        return action
