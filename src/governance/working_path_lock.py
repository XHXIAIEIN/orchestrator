"""R63 Archon: Working Path Lock — DB row-level distributed lock.

Problem: Two agent dispatches targeting the same working directory
can corrupt each other's code changes.

Solution: Use a DB table as a lock registry.
  - Each active task claims a working_path.
  - Status semantics: running/paused = lock held, terminal = released.
  - Conflict resolution: "older-wins" — the task that started first
    keeps the lock; the newer arrival gets a rejection message.
  - Stale detection: tasks in 'running' state for > STALE_TIMEOUT
    are treated as crashed orphans and their locks are released.

Integration: Called by executor.py / dispatch_lock.py before
starting an agent session on a specific path.

Source: Archon packages/core/src/db/workflows.ts (R63 deep steal)
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.storage.pool import get_pool

log = logging.getLogger(__name__)

_DEFAULT_DB = str(Path(__file__).resolve().parent.parent.parent / "data" / "events.db")

STALE_TIMEOUT_S = 5 * 60  # 5 minutes — matching Archon's STALE_PENDING_AGE_MS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS working_path_locks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    working_path TEXT NOT NULL,
    agent_id    TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'running',
    started_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(task_id)
);
CREATE INDEX IF NOT EXISTS idx_wpl_path ON working_path_locks(working_path, status);
CREATE INDEX IF NOT EXISTS idx_wpl_status ON working_path_locks(status);
"""


@dataclass
class LockResult:
    """Result of a lock acquisition attempt."""
    acquired: bool
    message: str
    holder_task_id: str | None = None
    holder_started_at: str | None = None


class WorkingPathLock:
    """DB row-level lock for working paths.

    Usage:
        lock = WorkingPathLock()

        result = lock.acquire("task-42", "/path/to/project", agent_id="agent-1")
        if not result.acquired:
            print(f"Blocked: {result.message}")
            return

        # ... do work ...

        lock.release("task-42")  # or mark terminal status
    """

    def __init__(self, db_path: str = _DEFAULT_DB):
        self._pool = get_pool(db_path, row_factory=sqlite3.Row, log_prefix="path_lock")
        with self._pool.connect() as conn:
            conn.executescript(_SCHEMA)

    def acquire(
        self,
        task_id: str,
        working_path: str,
        agent_id: str = "",
    ) -> LockResult:
        """Try to acquire a lock on the working path.

        Uses "older-wins" tiebreaker: if two tasks try to lock the same
        path, the one with the earlier started_at wins.

        Returns LockResult with acquired=True if lock granted.
        """
        now = datetime.now(tz=timezone.utc).isoformat()

        with self._pool.connect() as conn:
            # Clean up stale locks first
            self._cleanup_stale(conn)

            # Check for active lock on this path
            active = conn.execute(
                "SELECT task_id, agent_id, started_at, status "
                "FROM working_path_locks "
                "WHERE working_path = ? AND status IN ('running', 'paused') "
                "ORDER BY datetime(started_at) ASC "
                "LIMIT 1",
                (working_path,),
            ).fetchone()

            if active and active["task_id"] != task_id:
                # Conflict — older-wins: the existing holder keeps it
                return LockResult(
                    acquired=False,
                    message=(
                        f"Path '{working_path}' is locked by task {active['task_id']} "
                        f"(agent: {active['agent_id']}, started: {active['started_at']}, "
                        f"status: {active['status']}). "
                        f"Wait for it to complete or manually release it."
                    ),
                    holder_task_id=active["task_id"],
                    holder_started_at=active["started_at"],
                )

            # Grant lock: upsert our row
            conn.execute(
                "INSERT INTO working_path_locks "
                "(task_id, working_path, agent_id, status, started_at, updated_at) "
                "VALUES (?, ?, ?, 'running', ?, ?) "
                "ON CONFLICT(task_id) DO UPDATE SET "
                "working_path = excluded.working_path, "
                "agent_id = excluded.agent_id, "
                "status = 'running', "
                "updated_at = excluded.updated_at",
                (task_id, working_path, agent_id, now, now),
            )

            return LockResult(acquired=True, message="Lock acquired")

    def release(self, task_id: str, status: str = "completed") -> bool:
        """Release a lock by marking the task as terminal.

        Args:
            task_id: the task holding the lock
            status: terminal status (completed/failed/cancelled)

        Returns:
            True if lock was found and released.
        """
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._pool.connect() as conn:
            cur = conn.execute(
                "UPDATE working_path_locks SET status = ?, updated_at = ? "
                "WHERE task_id = ? AND status IN ('running', 'paused')",
                (status, now, task_id),
            )
            released = cur.rowcount > 0
            if released:
                log.info("path_lock: released %s (status=%s)", task_id, status)
            return released

    def pause(self, task_id: str) -> bool:
        """Pause a lock (still held, but not actively working)."""
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._pool.connect() as conn:
            cur = conn.execute(
                "UPDATE working_path_locks SET status = 'paused', updated_at = ? "
                "WHERE task_id = ? AND status = 'running'",
                (now, task_id),
            )
            return cur.rowcount > 0

    def resume(self, task_id: str) -> bool:
        """Resume a paused lock."""
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._pool.connect() as conn:
            cur = conn.execute(
                "UPDATE working_path_locks SET status = 'running', updated_at = ? "
                "WHERE task_id = ? AND status = 'paused'",
                (now, task_id),
            )
            return cur.rowcount > 0

    def heartbeat(self, task_id: str) -> bool:
        """Update the timestamp to prevent stale detection."""
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._pool.connect() as conn:
            cur = conn.execute(
                "UPDATE working_path_locks SET updated_at = ? "
                "WHERE task_id = ? AND status IN ('running', 'paused')",
                (now, task_id),
            )
            return cur.rowcount > 0

    def get_active_locks(self) -> list[dict]:
        """List all currently held locks."""
        with self._pool.connect() as conn:
            self._cleanup_stale(conn)
            rows = conn.execute(
                "SELECT * FROM working_path_locks "
                "WHERE status IN ('running', 'paused') "
                "ORDER BY started_at",
            ).fetchall()
            return [dict(r) for r in rows]

    def is_path_locked(self, working_path: str) -> dict | None:
        """Check if a path is currently locked. Returns holder info or None."""
        with self._pool.connect() as conn:
            self._cleanup_stale(conn)
            row = conn.execute(
                "SELECT * FROM working_path_locks "
                "WHERE working_path = ? AND status IN ('running', 'paused') "
                "LIMIT 1",
                (working_path,),
            ).fetchone()
            return dict(row) if row else None

    def force_release(self, task_id: str) -> bool:
        """Force-release a lock regardless of status. For manual cleanup."""
        with self._pool.connect() as conn:
            cur = conn.execute(
                "UPDATE working_path_locks SET status = 'force_released', "
                "updated_at = ? WHERE task_id = ?",
                (datetime.now(tz=timezone.utc).isoformat(), task_id),
            )
            released = cur.rowcount > 0
            if released:
                log.warning("path_lock: force-released %s", task_id)
            return released

    def _cleanup_stale(self, conn) -> int:
        """Remove locks that have been running/paused too long without heartbeat.

        Archon's approach: tasks in pending/running state for > 5 minutes
        without update are treated as crashed orphans.
        """
        cutoff = (
            datetime.now(tz=timezone.utc) - timedelta(seconds=STALE_TIMEOUT_S)
        ).isoformat()

        cur = conn.execute(
            "UPDATE working_path_locks SET status = 'stale_released' "
            "WHERE status IN ('running', 'paused') AND updated_at < ?",
            (cutoff,),
        )
        count = cur.rowcount
        if count > 0:
            log.warning("path_lock: cleaned up %d stale lock(s)", count)
        return count
