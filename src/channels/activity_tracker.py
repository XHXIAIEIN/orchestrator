"""R48 (Hermes v0.8): Activity-Based Timeout.

Tracks last tool/API call time per task. Timeout based on inactivity, not wall-clock.
A task actively making tool calls won't be killed even if it runs long.

Usage:
    tracker = ActivityTracker()
    tracker.touch("task-5")           # record activity
    summary = tracker.get_summary("task-5")  # check activity
    stale = tracker.get_stale(timeout=300)    # find idle tasks
"""
import threading
import time
from typing import Dict, List, Optional


class ActivityTracker:
    """Thread-safe in-memory tracker for per-task activity timestamps."""

    def __init__(self):
        self._lock = threading.Lock()
        # task_id -> {"started_at": float, "last_activity": float, "total_touches": int}
        self._records: Dict[str, dict] = {}

    def touch(self, task_id: str) -> None:
        """Record activity for task_id. Creates a new record if first touch."""
        now = time.time()
        with self._lock:
            if task_id not in self._records:
                self._records[task_id] = {
                    "started_at": now,
                    "last_activity": now,
                    "total_touches": 1,
                }
            else:
                self._records[task_id]["last_activity"] = now
                self._records[task_id]["total_touches"] += 1

    def get_summary(self, task_id: str) -> Optional[dict]:
        """Return activity summary for task_id, or None if unknown.

        Returns:
            dict with keys:
                seconds_since_activity: float
                total_touches: int
                started_at: float (unix timestamp)
        """
        now = time.time()
        with self._lock:
            rec = self._records.get(task_id)
            if rec is None:
                return None
            return {
                "seconds_since_activity": now - rec["last_activity"],
                "total_touches": rec["total_touches"],
                "started_at": rec["started_at"],
            }

    def get_stale(self, timeout_seconds: float = 300) -> List[str]:
        """Return list of task_ids that have been idle beyond timeout_seconds."""
        now = time.time()
        stale = []
        with self._lock:
            for task_id, rec in self._records.items():
                if now - rec["last_activity"] >= timeout_seconds:
                    stale.append(task_id)
        return stale

    def is_active(self, task_id: str, timeout_seconds: float = 300) -> bool:
        """Return True if task has had activity within timeout_seconds."""
        now = time.time()
        with self._lock:
            rec = self._records.get(task_id)
            if rec is None:
                return False
            return (now - rec["last_activity"]) < timeout_seconds

    def remove(self, task_id: str) -> None:
        """Remove a task record when no longer needed."""
        with self._lock:
            self._records.pop(task_id, None)


# Module-level singleton — callers import get_activity_tracker() to share state.
_tracker: Optional[ActivityTracker] = None
_tracker_lock = threading.Lock()


def get_activity_tracker() -> ActivityTracker:
    """Return the module-level singleton ActivityTracker."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = ActivityTracker()
    return _tracker


def propagate_heartbeat(child_task_id: str, parent_task_id: str) -> None:
    """Child agent heartbeat propagates to parent to prevent timeout."""
    tracker = get_activity_tracker()
    tracker.touch(child_task_id)
    if parent_task_id:
        tracker.touch(parent_task_id)
