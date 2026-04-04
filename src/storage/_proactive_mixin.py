"""ProactiveMixin — persistence layer for proactive push history."""

import json
from datetime import datetime, timezone


class ProactiveMixin:
    def log_proactive(
        self,
        signal_id: str,
        tier: str,
        severity: str,
        data,
        message: str,
        action: str,
        reason: str = "",
    ) -> int:
        """Insert a proactive log entry and return the new row id."""
        created_at = datetime.now(timezone.utc).isoformat()
        data_str = json.dumps(data, ensure_ascii=False) if data is not None else None
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO proactive_log
                    (signal_id, tier, severity, data, message, action, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (signal_id, tier, severity, data_str, message, action, reason, created_at),
            )
            return cur.lastrowid

    def recent_proactive_logs(self, limit: int = 20) -> list[dict]:
        """Return the most recent proactive log entries, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM proactive_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def proactive_log_stats(self, hours: int = 24) -> dict:
        """Count sent/throttled actions in the last N hours."""
        since = datetime.now(timezone.utc).replace(microsecond=0)
        from datetime import timedelta
        cutoff = (since - timedelta(hours=hours)).isoformat()
        with self._connect() as conn:
            sent = conn.execute(
                "SELECT COUNT(*) FROM proactive_log WHERE action = 'sent' AND created_at >= ?",
                (cutoff,),
            ).fetchone()[0]
            throttled = conn.execute(
                "SELECT COUNT(*) FROM proactive_log WHERE action = 'throttled' AND created_at >= ?",
                (cutoff,),
            ).fetchone()[0]
        return {"sent": sent, "throttled": throttled, "period_hours": hours}
