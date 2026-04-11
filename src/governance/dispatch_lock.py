"""R46 (career-ops): Lock File + State Resume for dispatch sessions.

Prevents concurrent dispatch sessions from conflicting.
Tracks task state for retry-failed capability on interrupted sessions.

Lock semantics:
  - PID-based lock file in tmp/dispatch.lock
  - Stale lock detection (if PID doesn't exist, lock is stale)
  - State file tracks task status per session for resume

Usage:
    lock = DispatchLock()
    with lock.acquire("session-123"):
        # dispatch tasks...
        lock.mark_task("session-123", task_id=5, status="completed")

    # After crash:
    failed = lock.get_failed_tasks("session-123")
    for task_id in failed:
        # re-dispatch
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent

_LOCK_DIR = _REPO_ROOT / "tmp"
_LOCK_FILE = _LOCK_DIR / "dispatch.lock"
_STATE_DIR = _LOCK_DIR / "dispatch-state"


class DispatchLockError(Exception):
    """Raised when lock cannot be acquired."""


class DispatchLock:
    """PID-based dispatch lock with state tracking."""

    def acquire(self, session_id: str) -> "DispatchLockContext":
        """Acquire dispatch lock. Raises DispatchLockError if already held."""
        return DispatchLockContext(session_id)

    def mark_task(self, session_id: str, task_id: int | str,
                  status: str, output: str = "") -> None:
        """Record task status in session state file."""
        state = self._load_state(session_id)
        state["tasks"][str(task_id)] = {
            "status": status,
            "output": output[:500] if output else "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_state(session_id, state)

    def get_failed_tasks(self, session_id: str) -> list[str]:
        """Get task IDs that failed or were interrupted in a session."""
        state = self._load_state(session_id)
        failed = []
        for task_id, info in state.get("tasks", {}).items():
            if info.get("status") in ("failed", "pending", "running"):
                failed.append(task_id)
        return failed

    def get_session_state(self, session_id: str) -> dict:
        """Get full state for a session."""
        return self._load_state(session_id)

    def list_sessions(self) -> list[dict]:
        """List all tracked sessions with summary."""
        if not _STATE_DIR.exists():
            return []
        sessions = []
        for f in sorted(_STATE_DIR.glob("session-*.json"), reverse=True):
            try:
                state = json.loads(f.read_text(encoding="utf-8"))
                tasks = state.get("tasks", {})
                sessions.append({
                    "session_id": state.get("session_id", f.stem),
                    "started_at": state.get("started_at", ""),
                    "total": len(tasks),
                    "completed": sum(1 for t in tasks.values() if t.get("status") == "completed"),
                    "failed": sum(1 for t in tasks.values() if t.get("status") == "failed"),
                    "pending": sum(1 for t in tasks.values() if t.get("status") in ("pending", "running")),
                })
            except Exception:
                continue
        return sessions

    def retry_failed(self, session_id: str) -> list[str]:
        """Mark failed tasks as pending for retry. Returns task IDs reset."""
        state = self._load_state(session_id)
        reset = []
        for task_id, info in state.get("tasks", {}).items():
            if info.get("status") in ("failed",):
                info["status"] = "pending"
                info["updated_at"] = datetime.now(timezone.utc).isoformat()
                reset.append(task_id)
        if reset:
            self._save_state(session_id, state)
        return reset

    def _load_state(self, session_id: str) -> dict:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        path = _STATE_DIR / f"session-{session_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "session_id": session_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "tasks": {},
        }

    def _save_state(self, session_id: str, state: dict) -> None:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        path = _STATE_DIR / f"session-{session_id}.json"
        try:
            path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("DispatchLock: failed to save state: %s", e)


class DispatchLockContext:
    """Context manager for dispatch lock."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    def __enter__(self):
        _LOCK_DIR.mkdir(parents=True, exist_ok=True)
        # Check for stale lock
        if _LOCK_FILE.exists():
            try:
                lock_data = json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
                pid = lock_data.get("pid", 0)
                # Check if PID is still alive
                try:
                    os.kill(pid, 0)  # signal 0 = check existence
                    raise DispatchLockError(
                        f"Dispatch lock held by PID {pid} "
                        f"(session: {lock_data.get('session_id', '?')}). "
                        f"If stale, delete {_LOCK_FILE}"
                    )
                except OSError:
                    # PID doesn't exist — stale lock
                    log.warning("DispatchLock: removing stale lock (PID %d dead)", pid)
                    _LOCK_FILE.unlink()
            except (json.JSONDecodeError, KeyError):
                _LOCK_FILE.unlink()

        # Write lock
        _LOCK_FILE.write_text(
            json.dumps({
                "pid": os.getpid(),
                "session_id": self.session_id,
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            }, indent=2),
            encoding="utf-8",
        )
        return self

    def __exit__(self, *args):
        try:
            _LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass
