"""Multi-Dimensional Token Budget — control token usage across multiple axes.

Instead of a single global token limit, track budgets per:
- Department (engineering gets more than protocol)
- Task type (analysis gets more than formatting)
- Time window (hourly/daily limits)
- Model tier (limit expensive model usage)
"""

import time
import threading
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class BudgetAxis:
    """A single budget dimension."""
    name: str
    limit: int
    used: int = 0
    window_seconds: float | None = None  # None = no time window
    window_start: float = field(default_factory=time.time)

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def utilization(self) -> float:
        return self.used / self.limit if self.limit > 0 else 0.0

    def is_expired(self) -> bool:
        if self.window_seconds is None:
            return False
        return (time.time() - self.window_start) > self.window_seconds

    def reset_if_expired(self):
        if self.is_expired():
            self.used = 0
            self.window_start = time.time()


class MultiBudget:
    """Multi-axis token budget controller."""

    def __init__(self):
        self._axes: dict[str, dict[str, BudgetAxis]] = defaultdict(dict)
        self._lock = threading.Lock()

    def set_budget(
        self,
        dimension: str,    # "department", "task_type", "model", "time"
        key: str,          # "engineering", "analysis", "opus", "hourly"
        limit: int,
        window_seconds: float | None = None,
    ):
        """Set a budget for a specific axis."""
        with self._lock:
            self._axes[dimension][key] = BudgetAxis(
                name=f"{dimension}/{key}",
                limit=limit,
                window_seconds=window_seconds,
            )

    def can_spend(self, tokens: int, **axes) -> tuple[bool, str]:
        """Check if spending tokens is allowed across all specified axes.

        Args:
            tokens: number of tokens to spend
            **axes: dimension=key pairs, e.g. department="engineering", model="opus"

        Returns:
            (allowed, reason)
        """
        with self._lock:
            for dimension, key in axes.items():
                if dimension in self._axes and key in self._axes[dimension]:
                    axis = self._axes[dimension][key]
                    axis.reset_if_expired()
                    if axis.remaining < tokens:
                        return False, f"{axis.name} budget exhausted ({axis.used}/{axis.limit})"
            return True, "ok"

    def spend(self, tokens: int, **axes):
        """Record token spending across axes."""
        with self._lock:
            for dimension, key in axes.items():
                if dimension in self._axes and key in self._axes[dimension]:
                    axis = self._axes[dimension][key]
                    axis.reset_if_expired()
                    axis.used += tokens

    def get_utilization(self) -> dict:
        """Return utilization across all axes."""
        with self._lock:
            result = {}
            for dim, keys in self._axes.items():
                result[dim] = {}
                for key, axis in keys.items():
                    axis.reset_if_expired()
                    result[dim][key] = {
                        "used": axis.used,
                        "limit": axis.limit,
                        "remaining": axis.remaining,
                        "utilization": round(axis.utilization, 3),
                    }
            return result

    def get_warnings(self, threshold: float = 0.8) -> list[str]:
        """Return warnings for axes above utilization threshold."""
        warnings = []
        with self._lock:
            for dim, keys in self._axes.items():
                for key, axis in keys.items():
                    axis.reset_if_expired()
                    if axis.utilization >= threshold:
                        warnings.append(
                            f"{axis.name}: {axis.utilization:.0%} used ({axis.used}/{axis.limit})"
                        )
        return warnings
