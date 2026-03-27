"""Wake session methods for EventsDB."""
from datetime import datetime, timezone


class WakeMixin:

    def create_wake_session(self, task_id: int, chat_id: str,
                            spotlight: str, mode: str = "silent",
                            status: str = "pending") -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO wake_sessions "
                "(task_id, chat_id, spotlight, mode, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, chat_id, spotlight, mode, status, now),
            )
            return cursor.lastrowid

    def get_wake_session(self, session_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM wake_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_wake_session_by_task(self, task_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM wake_sessions WHERE task_id = ?", (task_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_wake_sessions(self, status: str = None, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM wake_sessions WHERE status = ? "
                    "ORDER BY id DESC LIMIT ?", (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM wake_sessions ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_active_wake_session(self, chat_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM wake_sessions "
                "WHERE chat_id = ? AND status IN ('pending', 'approved', 'running') "
                "ORDER BY id DESC LIMIT 1",
                (chat_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_wake_session(self, session_id: int, **kwargs):
        allowed = {"status", "mode", "result", "started_at", "finished_at"}
        invalid = set(kwargs) - allowed
        if invalid:
            raise ValueError(f"Invalid wake_session columns: {invalid}")
        if kwargs.get("status") == "running" and "started_at" not in kwargs:
            kwargs["started_at"] = datetime.now(timezone.utc).isoformat()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [session_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE wake_sessions SET {sets} WHERE id = ?", vals,
            )

    def finish_wake_session(self, session_id: int, status: str,
                            result: str = ""):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE wake_sessions SET status = ?, result = ?, "
                "finished_at = ? WHERE id = ?",
                (status, result, now, session_id),
            )
