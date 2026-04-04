"""Growth Loops DB mixin — decisions, curiosity, and pattern queries."""
import json
import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

_DEFAULT_FOLLOWUP_DAYS = 7


class GrowthMixin:
    """Mixed into EventsDB. Provides growth_decisions + growth_curiosity CRUD
    and pattern-recognition queries over the existing learnings table."""

    # ── Decisions ──────────────────────────────────────────────

    def add_decision(
        self,
        decision: str,
        *,
        context: str = "",
        alternatives: list[str] | None = None,
        followup_days: int = _DEFAULT_FOLLOWUP_DAYS,
        source_session: str = "",
    ) -> int:
        now = datetime.now(timezone.utc)
        followup_at = (now + timedelta(days=followup_days)).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO growth_decisions "
                "(decision, context, alternatives, followup_at, source_session, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    decision,
                    context,
                    json.dumps(alternatives or []),
                    followup_at,
                    source_session,
                    now.isoformat(),
                ),
            )
            return cur.lastrowid

    def get_decisions_due(self, now: datetime | None = None) -> list[dict]:
        """Return decisions whose followup_at <= now and status is pending."""
        now = now or datetime.now(timezone.utc)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, decision, context, alternatives, followup_at, "
                "source_session, created_at "
                "FROM growth_decisions "
                "WHERE status = 'pending' AND followup_at <= ? "
                "ORDER BY followup_at",
                (now.isoformat(),),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_decisions(self, days: int = 30, limit: int = 20) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, decision, context, status, followup_at, outcome, created_at "
                "FROM growth_decisions WHERE created_at >= ? "
                "ORDER BY created_at DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def followup_decision(self, decision_id: int, outcome: str, new_status: str = "followed_up") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE growth_decisions SET outcome = ?, status = ?, followed_up_at = ? "
                "WHERE id = ?",
                (outcome, new_status, now, decision_id),
            )

    # ── Curiosity ──────────────────────────────────────────────

    def add_curiosity_question(self, question: str, domain: str = "general") -> int | None:
        """Queue a curiosity question. Returns None if duplicate."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO growth_curiosity (question, domain, created_at) VALUES (?, ?, ?)",
                    (question, domain, now),
                )
                return cur.lastrowid
            except Exception:
                return None

    def get_pending_curiosity(self, limit: int = 3) -> list[dict]:
        """Get unanswered curiosity questions, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, question, domain, created_at "
                "FROM growth_curiosity WHERE status = 'pending' "
                "ORDER BY created_at LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def answer_curiosity(self, question_id: int, answer: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE growth_curiosity SET answer = ?, status = 'answered', answered_at = ? "
                "WHERE id = ?",
                (answer, now, question_id),
            )

    def mark_curiosity_asked(self, question_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE growth_curiosity SET status = 'asked', asked_at = ? WHERE id = ?",
                (now, question_id),
            )

    def get_curiosity_stats(self) -> dict:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM growth_curiosity GROUP BY status"
            ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    # ── Pattern Recognition (queries over learnings table) ────

    def get_request_patterns(self, threshold: int = 3) -> list[dict]:
        """Find learnings with entry_type='request_pattern' that recur >= threshold."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, pattern_key, rule, detail, recurrence, first_seen, last_seen, status "
                "FROM learnings "
                "WHERE entry_type = 'request_pattern' AND recurrence >= ? "
                "AND status IN ('pending', 'promoted') "
                "ORDER BY recurrence DESC",
                (threshold,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_automation_candidates(self, threshold: int = 3) -> list[dict]:
        """Patterns that recur enough to warrant automation, not yet actioned."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, pattern_key, rule, recurrence, first_seen, last_seen "
                "FROM learnings "
                "WHERE entry_type = 'request_pattern' AND recurrence >= ? "
                "AND status = 'pending' "
                "ORDER BY recurrence DESC LIMIT 10",
                (threshold,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Growth Dashboard ──────────────────────────────────────

    def get_growth_summary(self) -> dict:
        """One-shot summary of all three loops for SessionStart injection."""
        with self._connect() as conn:
            decisions_pending = conn.execute(
                "SELECT COUNT(*) as cnt FROM growth_decisions WHERE status = 'pending'"
            ).fetchone()["cnt"]
            decisions_due = conn.execute(
                "SELECT COUNT(*) as cnt FROM growth_decisions "
                "WHERE status = 'pending' AND followup_at <= datetime('now')"
            ).fetchone()["cnt"]
            curiosity_pending = conn.execute(
                "SELECT COUNT(*) as cnt FROM growth_curiosity WHERE status = 'pending'"
            ).fetchone()["cnt"]
            curiosity_answered = conn.execute(
                "SELECT COUNT(*) as cnt FROM growth_curiosity WHERE status = 'answered'"
            ).fetchone()["cnt"]
            patterns_hot = conn.execute(
                "SELECT COUNT(*) as cnt FROM learnings "
                "WHERE entry_type = 'request_pattern' AND recurrence >= 3 AND status = 'pending'"
            ).fetchone()["cnt"]

        return {
            "decisions": {"pending": decisions_pending, "due": decisions_due},
            "curiosity": {"pending": curiosity_pending, "answered": curiosity_answered},
            "patterns": {"automation_candidates": patterns_hot},
        }
