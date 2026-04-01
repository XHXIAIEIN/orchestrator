"""Gate Chain — reusable gate utilities for preflight and state tracking."""
import time
from pathlib import Path


class LockFileState:
    """Zero-dependency state tracking via file mtime.

    Source: Claude Code consolidationLock (Round 28a)

    Usage:
        state = LockFileState(Path("data/.last_run"))
        if state.hours_since() >= 24:
            do_work()
            state.touch()
    """

    def __init__(self, path: Path):
        self.path = path

    def hours_since(self) -> float:
        """Hours since last touch. Returns float('inf') if never touched."""
        if not self.path.exists():
            return float('inf')
        return (time.time() - self.path.stat().st_mtime) / 3600

    def minutes_since(self) -> float:
        """Minutes since last touch."""
        if not self.path.exists():
            return float('inf')
        return (time.time() - self.path.stat().st_mtime) / 60

    def touch(self):
        """Mark current time."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch()

    def is_stale(self, max_hours: float = 24.0) -> bool:
        """Check if state is older than max_hours."""
        return self.hours_since() >= max_hours
