"""Lifecycle Hooks — 16-event registry (R38: Inspect AI steal).

Unified hook system covering the full Orchestrator execution lifecycle:

  Batch layer:    on_batch_start, on_batch_end
  Task layer:     on_task_start, on_task_end
  Rollout layer:  on_rollout_start, on_rollout_end
  Attempt layer:  on_attempt_start, on_attempt_end
  Context layer:  on_context_build, on_context_inject
  LLM layer:      on_pre_llm, on_post_llm
  Review layer:   on_review_start, on_review_end
  Cross-cutting:  on_error, on_limit_exceeded

Design stolen from Inspect AI `src/inspect_ai/hooks/_hooks.py`:
  - Every hook gets independent try/except fault isolation
  - LimitExceededError is the ONLY exception that pierces isolation
  - HookSpec wraps callbacks with enabled() + priority for self-determination
  - Fire-and-forget: a failing hook never blocks the main flow

Replaces both the old 6-point global registry (Hermes) and the 4-point
LifecycleHooks dataclass in executor.py. One system, one truth.

Usage:
    hooks = get_lifecycle_hooks()
    hooks.register("on_pre_llm", my_audit_fn, priority=10)
    hooks.register("on_post_llm", my_cost_tracker)

    hooks.fire("on_pre_llm", model=model, prompt=prompt[:200])
    result = llm_call(...)
    hooks.fire("on_post_llm", model=model, cost=0.01, latency_ms=500)

    # Hook with enabled() self-check:
    hooks.register("on_attempt_start", my_hook, enabled=lambda: config.debug)
"""

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger(__name__)


# ── LimitExceededError: the only exception that pierces hook isolation ──

class LimitExceededError(Exception):
    """Raised when a hard limit is hit (token budget, time, cost).

    This is the ONLY exception type that pierces hook fault isolation.
    When a hook raises LimitExceededError, it propagates to the caller
    because limits MUST be enforced — silent swallowing would defeat
    the purpose of the limit.
    """

    def __init__(self, limit_type: str, message: str = "", current: float = 0, maximum: float = 0):
        self.limit_type = limit_type
        self.current = current
        self.maximum = maximum
        super().__init__(message or f"{limit_type} exceeded: {current}/{maximum}")


# ── 16 Hook Points ──

HOOK_POINTS = frozenset({
    # Batch layer — multiple tasks dispatched together
    "on_batch_start",
    "on_batch_end",
    # Task layer — single task lifecycle
    "on_task_start",       # was on_task_dispatch
    "on_task_end",
    # Rollout layer — retry envelope around attempts
    "on_rollout_start",
    "on_rollout_end",
    # Attempt layer — single execution attempt
    "on_attempt_start",
    "on_attempt_end",
    # Context layer — prompt assembly and chain injection
    "on_context_build",
    "on_context_inject",
    # LLM layer — individual model calls
    "on_pre_llm",          # was pre_llm_call
    "on_post_llm",         # was post_llm_call
    # Review layer — council/scrutiny review
    "on_review_start",
    "on_review_end",
    # Cross-cutting
    "on_error",
    "on_limit_exceeded",
})

# Backwards-compat aliases: old name → new name
_ALIASES = {
    "pre_llm_call": "on_pre_llm",
    "post_llm_call": "on_post_llm",
    "on_session_start": "on_task_start",
    "on_session_end": "on_task_end",
    "on_task_dispatch": "on_task_start",
}


# ── HookEntry: wraps a callback with metadata ──

@dataclass
class HookEntry:
    """A registered hook with metadata for self-determination."""
    name: str
    callback: Callable
    priority: int = 0           # higher = fires first
    _enabled: Callable[[], bool] | None = None

    @property
    def enabled(self) -> bool:
        if self._enabled is None:
            return True
        try:
            return self._enabled()
        except Exception:
            return False  # broken enabled() = disabled


# ── Unified Registry ──

class LifecycleHookRegistry:
    """Registry for 16-event lifecycle hook callbacks.

    Fault isolation: every hook fires in its own try/except.
    LimitExceededError is the ONLY exception that pierces isolation.
    Hooks are sorted by priority (descending) at fire time.
    """

    def __init__(self):
        self._hooks: dict[str, list[HookEntry]] = {p: [] for p in HOOK_POINTS}
        self._stats: dict[str, int] = {p: 0 for p in HOOK_POINTS}
        self._errors: int = 0

    def _resolve(self, point: str) -> str:
        """Resolve aliases to canonical hook point names."""
        return _ALIASES.get(point, point)

    def register(self, point: str, callback: Callable, *,
                 name: str = "", priority: int = 0,
                 enabled: Callable[[], bool] | None = None):
        """Register a callback at a lifecycle point.

        Args:
            point: One of HOOK_POINTS (or a legacy alias)
            callback: Callable(**kwargs)
            name: For logging/debugging
            priority: Higher fires first (default 0)
            enabled: Optional callable returning bool — hook skipped when False
        """
        point = self._resolve(point)
        if point not in HOOK_POINTS:
            raise ValueError(f"Unknown hook point: {point}. Valid: {sorted(HOOK_POINTS)}")
        hook_name = name or getattr(callback, "__name__", "anonymous")
        entry = HookEntry(name=hook_name, callback=callback,
                          priority=priority, _enabled=enabled)
        self._hooks[point].append(entry)
        log.debug(f"lifecycle: registered {hook_name} at {point} (priority={priority})")

    def unregister(self, point: str, name: str):
        """Remove a named hook."""
        point = self._resolve(point)
        if point in self._hooks:
            self._hooks[point] = [e for e in self._hooks[point] if e.name != name]

    def fire(self, point: str, **kwargs):
        """Fire all hooks at a point. Failures are logged but never block.

        LimitExceededError is the ONLY exception that propagates — limits
        must be enforced, not silently swallowed.

        Returns list of results from hooks that returned non-None values.
        """
        point = self._resolve(point)
        if point not in self._hooks:
            return []

        self._stats[point] += 1
        results = []

        # Sort by priority descending (stable sort preserves registration order for ties)
        entries = sorted(self._hooks[point], key=lambda e: e.priority, reverse=True)

        for entry in entries:
            if not entry.enabled:
                continue
            try:
                result = entry.callback(**kwargs)
                if result is not None:
                    results.append(result)
            except LimitExceededError:
                # The ONLY exception that pierces isolation
                self._errors += 1
                log.warning(f"lifecycle: {entry.name}@{point} raised LimitExceededError — propagating")
                raise
            except Exception as e:
                self._errors += 1
                log.debug(f"lifecycle: hook {entry.name}@{point} failed: {e}")

        return results

    def get_registered(self, point: str = None) -> dict[str, list[str]]:
        """Return registered hook names, optionally filtered by point."""
        if point:
            point = self._resolve(point)
            return {point: [e.name for e in self._hooks.get(point, [])]}
        return {p: [e.name for e in entries]
                for p, entries in self._hooks.items() if entries}

    def get_stats(self) -> dict:
        active = {p: len(entries) for p, entries in self._hooks.items() if entries}
        return {
            "registered": active,
            "fire_counts": {p: c for p, c in self._stats.items() if c > 0},
            "total_errors": self._errors,
        }

    def clear(self):
        """Remove all hooks (for testing)."""
        self._hooks = {p: [] for p in HOOK_POINTS}
        self._stats = {p: 0 for p in HOOK_POINTS}
        self._errors = 0


# ── Singleton ──
_instance: Optional[LifecycleHookRegistry] = None


def get_lifecycle_hooks() -> LifecycleHookRegistry:
    global _instance
    if _instance is None:
        _instance = LifecycleHookRegistry()
    return _instance


def reset_lifecycle_hooks():
    """Reset singleton (for testing only)."""
    global _instance
    _instance = None
