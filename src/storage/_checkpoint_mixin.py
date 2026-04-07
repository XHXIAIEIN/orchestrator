"""CheckpointMixin — structured checkpoint storage for EventsDB (R43).

Implements the checkpoint portion of StorageProtocol using SQLite.
Also provides generic key-value put/get/list/delete for conformance.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

log = logging.getLogger(__name__)


class CheckpointMixin:
    """Mixin adding StorageProtocol methods to EventsDB."""

    def _ensure_checkpoint_table(self):
        """Create checkpoint and kv tables if they don't exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS structured_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    channel_values TEXT NOT NULL DEFAULT '{}',
                    channel_versions TEXT NOT NULL DEFAULT '{}',
                    pending_writes TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    timestamp TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ckpt_task ON structured_checkpoints(task_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ckpt_ts ON structured_checkpoints(timestamp)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

    # ── Key-Value operations ──────────────────────────────────

    def put(self, key: str, value: Any) -> None:
        self._ensure_checkpoint_table()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
                (key, json.dumps(value, default=str)),
            )

    def get(self, key: str) -> Any:
        self._ensure_checkpoint_table()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM kv_store WHERE key = ?", (key,)
            ).fetchone()
            if not row:
                raise KeyError(key)
            return json.loads(row["value"])

    def list(self, prefix: str = "") -> list[str]:
        self._ensure_checkpoint_table()
        with self._connect() as conn:
            if prefix:
                rows = conn.execute(
                    "SELECT key FROM kv_store WHERE key LIKE ? ORDER BY key",
                    (f"{prefix}%",),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key FROM kv_store ORDER BY key"
                ).fetchall()
            return [row["key"] for row in rows]

    def delete(self, key: str) -> None:
        self._ensure_checkpoint_table()
        with self._connect() as conn:
            conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))

    # ── Checkpoint operations ─────────────────────────────────

    def put_checkpoint(self, cp) -> None:
        """Store a StructuredCheckpoint."""
        self._ensure_checkpoint_table()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO structured_checkpoints
                   (task_id, channel_values, channel_versions, pending_writes, metadata, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    cp.task_id,
                    json.dumps(cp.channel_values, default=str),
                    json.dumps(cp.channel_versions, default=str),
                    json.dumps(cp.pending_writes, default=str),
                    json.dumps(cp.metadata, default=str),
                    cp.timestamp,
                ),
            )

    def get_checkpoint(self, task_id: str):
        """Get the latest checkpoint for a task."""
        from src.governance.checkpoint_recovery import StructuredCheckpoint

        self._ensure_checkpoint_table()
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM structured_checkpoints
                   WHERE task_id = ?
                   ORDER BY timestamp DESC LIMIT 1""",
                (task_id,),
            ).fetchone()
            if not row:
                return None
            return StructuredCheckpoint(
                task_id=row["task_id"],
                channel_values=json.loads(row["channel_values"]),
                channel_versions=json.loads(row["channel_versions"]),
                pending_writes=json.loads(row["pending_writes"]),
                metadata=json.loads(row["metadata"]),
                timestamp=row["timestamp"],
            )

    def list_checkpoints(self, task_id: str | None = None):
        """List structured_checkpoints, ordered by timestamp desc."""
        from src.governance.checkpoint_recovery import StructuredCheckpoint

        self._ensure_checkpoint_table()
        with self._connect() as conn:
            if task_id:
                rows = conn.execute(
                    "SELECT * FROM structured_checkpoints WHERE task_id = ? ORDER BY timestamp DESC",
                    (task_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM structured_checkpoints ORDER BY timestamp DESC"
                ).fetchall()
            return [
                StructuredCheckpoint(
                    task_id=r["task_id"],
                    channel_values=json.loads(r["channel_values"]),
                    channel_versions=json.loads(r["channel_versions"]),
                    pending_writes=json.loads(r["pending_writes"]),
                    metadata=json.loads(r["metadata"]),
                    timestamp=r["timestamp"],
                )
                for r in rows
            ]

    def delete_checkpoints(self, task_id: str) -> None:
        """Delete all structured_checkpoints for a task."""
        self._ensure_checkpoint_table()
        with self._connect() as conn:
            conn.execute("DELETE FROM structured_checkpoints WHERE task_id = ?", (task_id,))
