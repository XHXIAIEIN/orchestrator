"""Learnings-related methods for EventsDB."""
import json
import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)


class LearningsMixin:

    def add_learning(
        self,
        pattern_key: str,
        rule: str,
        *,
        area: str = "general",
        context: str = "",
        source_type: str = "error",
        department: str = None,
        task_id: int = None,
        ttl_days: int = 0,
    ) -> int:
        """Record a learning. If pattern_key exists, bump recurrence instead.

        Args:
            ttl_days: Time-to-live in days. 0 = permanent. >0 = auto-expires.
                      Temporary facts (config values, perf numbers) should use TTL.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Compute expiry if TTL set
        expires_at = None
        if ttl_days > 0:
            expires_at = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, recurrence, status FROM learnings WHERE pattern_key = ?",
                (pattern_key,),
            ).fetchone()
            if existing:
                new_count = existing["recurrence"] + 1
                conn.execute(
                    "UPDATE learnings SET recurrence = ?, context = CASE WHEN ? != '' THEN ? ELSE context END WHERE id = ?",
                    (new_count, context, context, existing["id"]),
                )
                return existing["id"]

            # Contradiction check: find active learnings with similar pattern_key prefix
            # that might conflict (same area, same department, different rule)
            prefix = pattern_key.split(":")[0] if ":" in pattern_key else pattern_key
            conflicts = conn.execute(
                "SELECT id, pattern_key, rule FROM learnings "
                "WHERE pattern_key LIKE ? AND status IN ('pending', 'promoted') "
                "AND area = ? AND rule != ? LIMIT 5",
                (f"{prefix}:%", area, rule),
            ).fetchall()
            if conflicts:
                # Log contradiction but don't block — newer fact wins
                for c in conflicts:
                    log.info(
                        f"learnings: potential contradiction — new '{pattern_key}' vs existing '{c['pattern_key']}'"
                    )

            cursor = conn.execute(
                "INSERT INTO learnings (pattern_key, area, rule, context, source_type, "
                "status, recurrence, department, task_id, created_at, ttl_days, expires_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', 1, ?, ?, ?, ?, ?)",
                (pattern_key, area, rule, context, source_type, department, task_id,
                 now, ttl_days, expires_at),
            )
            return cursor.lastrowid

    def promote_learning(self, learning_id: int) -> None:
        """Promote a learning to boot.md-eligible status."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE learnings SET status = 'promoted', promoted_at = ? WHERE id = ?",
                (now, learning_id),
            )

    def retire_learning(self, learning_id: int) -> None:
        """Retire a learning (no longer relevant)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE learnings SET status = 'retired', retired_at = ? WHERE id = ?",
                (now, learning_id),
            )

    def get_learnings(self, status: str = None, area: str = None, department: str = None, limit: int = 50) -> list:
        """Query learnings with optional filters."""
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if area:
            clauses.append("area = ?")
            params.append(area)
        if department:
            clauses.append("department = ?")
            params.append(department)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id, pattern_key, area, rule, context, source_type, status, recurrence, department, task_id, created_at, promoted_at "
                f"FROM learnings {where} ORDER BY recurrence DESC, created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_promoted_learnings(self) -> list:
        """Get all promoted learnings for boot.md compilation."""
        return self.get_learnings(status="promoted", limit=30)

    def get_learnings_for_dispatch(self, department: str = None, area: str = None,
                                    record_hits: bool = True) -> list:
        """Get active+promoted learnings relevant to a dispatch context.

        If record_hits=True, bumps hit_count and last_hit_at for matched learnings
        (supports usage-based experience culling).
        """
        clauses = ["status IN ('pending', 'promoted')"]
        params = []
        if department:
            clauses.append("(department = ? OR department IS NULL)")
            params.append(department)
        if area:
            clauses.append("area = ?")
            params.append(area)
        where = "WHERE " + " AND ".join(clauses)
        params.append(20)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id, pattern_key, rule, recurrence, department FROM learnings {where} "
                f"ORDER BY recurrence DESC LIMIT ?",
                params,
            ).fetchall()
            result = [dict(r) for r in rows]

            if record_hits and result:
                now = datetime.now(timezone.utc).isoformat()
                ids = [r["id"] for r in result]
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"UPDATE learnings SET hit_count = COALESCE(hit_count, 0) + 1, "
                    f"last_hit_at = ? WHERE id IN ({placeholders})",
                    [now] + ids,
                )

        return result
