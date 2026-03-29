"""Plugin Lifecycle Hooks — stolen from Hermes.

Registry for callbacks at key lifecycle points:
  - pre_llm_call: Before any LLM API call (audit, rate limiting, context injection)
  - post_llm_call: After LLM response (cost logging, output validation)
  - on_session_start: When an agent session begins
  - on_session_end: When an agent session completes
  - on_task_dispatch: When a task is dispatched to a department
  - on_error: When an error occurs

Hooks are fire-and-forget — a failing hook never blocks the main flow.

Usage:
    hooks = get_lifecycle_hooks()
    hooks.register("pre_llm_call", my_audit_fn)
    hooks.register("post_llm_call", my_cost_tracker)

    # In LLM call:
    hooks.fire("pre_llm_call", model=model, prompt=prompt[:200])
    result = llm_call(...)
    hooks.fire("post_llm_call", model=model, cost=0.01, latency_ms=500)
"""

import logging
from typing import Callable, Optional

log = logging.getLogger(__name__)

# Valid hook points
HOOK_POINTS = {
    "pre_llm_call",
    "post_llm_call",
    "on_session_start",
    "on_session_end",
    "on_task_dispatch",
    "on_error",
}


class LifecycleHookRegistry:
    """Registry for lifecycle hook callbacks."""

    def __init__(self):
        self._hooks: dict[str, list[tuple[str, Callable]]] = {p: [] for p in HOOK_POINTS}
        self._stats: dict[str, int] = {p: 0 for p in HOOK_POINTS}
        self._errors: int = 0

    def register(self, point: str, callback: Callable, name: str = ""):
        """Register a callback at a lifecycle point.

        Args:
            point: One of HOOK_POINTS
            callback: Callable(**kwargs) — receives keyword args specific to each hook point
            name: Optional name for logging/debugging
        """
        if point not in HOOK_POINTS:
            raise ValueError(f"Unknown hook point: {point}. Valid: {HOOK_POINTS}")
        hook_name = name or getattr(callback, "__name__", "anonymous")
        self._hooks[point].append((hook_name, callback))
        log.debug(f"lifecycle: registered {hook_name} at {point}")

    def unregister(self, point: str, name: str):
        """Remove a named hook."""
        if point in self._hooks:
            self._hooks[point] = [(n, cb) for n, cb in self._hooks[point] if n != name]

    def fire(self, point: str, **kwargs):
        """Fire all hooks at a point. Failures are logged but never block.

        Returns list of results from hooks that returned non-None values.
        """
        if point not in self._hooks:
            return []

        self._stats[point] += 1
        results = []

        for hook_name, callback in self._hooks[point]:
            try:
                result = callback(**kwargs)
                if result is not None:
                    results.append(result)
            except Exception as e:
                self._errors += 1
                log.debug(f"lifecycle: hook {hook_name}@{point} failed: {e}")

        return results

    def get_registered(self, point: str = None) -> dict[str, list[str]]:
        """Return registered hook names, optionally filtered by point."""
        if point:
            return {point: [n for n, _ in self._hooks.get(point, [])]}
        return {p: [n for n, _ in hooks] for p, hooks in self._hooks.items() if hooks}

    def get_stats(self) -> dict:
        active = {p: len(hooks) for p, hooks in self._hooks.items() if hooks}
        return {
            "registered": active,
            "fire_counts": {p: c for p, c in self._stats.items() if c > 0},
            "total_errors": self._errors,
        }

    def clear(self):
        """Remove all hooks (for testing)."""
        self._hooks = {p: [] for p in HOOK_POINTS}


# Singleton
_instance: Optional[LifecycleHookRegistry] = None


def get_lifecycle_hooks() -> LifecycleHookRegistry:
    global _instance
    if _instance is None:
        _instance = LifecycleHookRegistry()
    return _instance
