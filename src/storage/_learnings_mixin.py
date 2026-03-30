"""Learnings-related methods for EventsDB — DB is the single source of truth."""
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
        detail: str = "",
        context: str = "",
        source_type: str = "error",
        entry_type: str = "learning",
        related_keys: list[str] | None = None,
        department: str = None,
        task_id: int = None,
        ttl_days: int = 0,
    ) -> int:
        """Record a learning. If pattern_key exists, bump recurrence and append detail."""
        now = datetime.now(timezone.utc).isoformat()
        related_json = json.dumps(related_keys or [])

        expires_at = None
        if ttl_days > 0:
            expires_at = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, recurrence, status, detail FROM learnings WHERE pattern_key = ?",
                (pattern_key,),
            ).fetchone()
            if existing:
                new_count = existing["recurrence"] + 1
                # Append new detail evidence separated by ---
                old_detail = existing["detail"] or ""
                merged_detail = (old_detail + "\n---\n" + detail).strip("- \n") if detail and old_detail else (detail or old_detail)
                conn.execute(
                    "UPDATE learnings SET recurrence = ?, detail = ?, last_seen = ?, "
                    "context = CASE WHEN ? != '' THEN ? ELSE context END "
                    "WHERE id = ?",
                    (new_count, merged_detail, now, context, context, existing["id"]),
                )
                return existing["id"]

            # Contradiction check
            prefix = pattern_key.split(":")[0] if ":" in pattern_key else pattern_key
            conflicts = conn.execute(
                "SELECT id, pattern_key, rule FROM learnings "
                "WHERE pattern_key LIKE ? AND status IN ('pending', 'promoted') "
                "AND area = ? AND rule != ? LIMIT 5",
                (f"{prefix}:%", area, rule),
            ).fetchall()
            if conflicts:
                for c in conflicts:
                    log.info(
                        f"learnings: potential contradiction — new '{pattern_key}' vs existing '{c['pattern_key']}'"
                    )

            cursor = conn.execute(
                "INSERT INTO learnings (pattern_key, area, rule, detail, context, source_type, "
                "entry_type, related_keys, status, recurrence, department, task_id, "
                "created_at, first_seen, last_seen, ttl_days, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, ?, ?, ?, ?, ?, ?)",
                (pattern_key, area, rule, detail, context, source_type,
                 entry_type, related_json, department, task_id,
                 now, now, now, ttl_days, expires_at),
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

    def get_learnings(self, status: str = None, area: str = None,
                      department: str = None, entry_type: str = None,
                      limit: int = 50) -> list:
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
        if entry_type:
            clauses.append("entry_type = ?")
            params.append(entry_type)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id, pattern_key, area, rule, detail, context, source_type, "
                f"entry_type, related_keys, status, recurrence, department, task_id, "
                f"created_at, first_seen, last_seen, promoted_at "
                f"FROM learnings {where} ORDER BY recurrence DESC, created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_promoted_learnings(self) -> list:
        """Get all promoted learnings for boot.md compilation."""
        return self.get_learnings(status="promoted", limit=30)

    def get_learnings_for_compilation(self, entry_type: str = None,
                                       status: str = None) -> list[dict]:
        """Full learnings with detail and related_keys — for compiler context packs."""
        clauses, params = [], []
        if entry_type:
            clauses.append("entry_type = ?")
            params.append(entry_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        else:
            # Exclude retired by default
            clauses.append("status != 'retired'")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id, pattern_key, area, rule, detail, related_keys, "
                f"entry_type, status, recurrence, first_seen, last_seen "
                f"FROM learnings {where} ORDER BY recurrence DESC, created_at DESC",
                params,
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            # Parse related_keys JSON
            try:
                d["related_keys"] = json.loads(d.get("related_keys") or "[]")
            except (json.JSONDecodeError, TypeError):
                d["related_keys"] = []
            result.append(d)
        return result

    def get_learnings_summary(self) -> dict:
        """Quick overview: counts by entry_type + top 5 by recurrence."""
        with self._connect() as conn:
            counts = conn.execute(
                "SELECT entry_type, COUNT(*) as cnt FROM learnings "
                "WHERE status != 'retired' GROUP BY entry_type"
            ).fetchall()
            top5 = conn.execute(
                "SELECT pattern_key, rule, recurrence, entry_type FROM learnings "
                "WHERE status != 'retired' ORDER BY recurrence DESC LIMIT 5"
            ).fetchall()
        return {
            "counts": {r["entry_type"]: r["cnt"] for r in counts},
            "top5": [dict(r) for r in top5],
        }

    def get_promotable_learnings(self, threshold: int = 3) -> list[dict]:
        """Get learnings ready for promotion (recurrence >= threshold, still pending)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, pattern_key, rule, detail, area, entry_type, recurrence "
                "FROM learnings WHERE recurrence >= ? AND status = 'pending' "
                "ORDER BY recurrence DESC",
                (threshold,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_learnings_for_dispatch(self, department: str = None, area: str = None,
                                    record_hits: bool = True) -> list:
        """Get active+promoted learnings relevant to a dispatch context."""
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
