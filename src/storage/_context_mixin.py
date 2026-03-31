"""Mixin for context_store table operations."""
from datetime import datetime, timezone


class ContextMixin:
    """DB operations for the context_store table (progressive disclosure)."""

    def upsert_context(self, session_id: str, layer: int, key: str,
                       content: str, token_est: int = 0,
                       expires_at: str | None = None):
        if token_est <= 0:
            token_est = max(1, len(content) // 4)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO context_store (session_id, layer, key, content, token_est, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, key) DO UPDATE SET
                    content = excluded.content,
                    token_est = excluded.token_est,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
            """, (session_id, layer, key, content, token_est, now, expires_at))

    def get_context(self, session_id: str, key: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM context_store WHERE session_id = ? AND key = ?",
                (session_id, key),
            ).fetchone()
            return dict(row) if row else None

    def get_context_by_layer(self, session_id: str, layer: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM context_store WHERE session_id = ? AND layer = ? ORDER BY key",
                (session_id, layer),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_context_keys(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT layer, key, token_est FROM context_store WHERE session_id = ? ORDER BY layer, key",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_context_total_tokens(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(token_est), 0) as total FROM context_store WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return row["total"]

    def delete_context_session(self, session_id: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM context_store WHERE session_id = ?", (session_id,))

    def delete_expired_context(self):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM context_store WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
