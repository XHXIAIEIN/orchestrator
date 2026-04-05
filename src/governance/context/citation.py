"""Citation Tracker (I8) — unified write-back scoring for memory retrieval.

Tracks which memories get cited (used) in tasks, accumulating usage data
across all memory types: learnings, structured memory (6 dims), extended.

Data pipeline: Provider retrieves memory → CitationTracker.record() →
  citation_log table (events.db) + cite_count/last_cited_at write-back.

Scoring formula feeds into confidence_ranker for priority ordering.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not (
    (_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()
):
    _REPO_ROOT = _REPO_ROOT.parent


# ── Source Types ──────────────────────────────────────────────────────

SOURCE_LEARNING = "learning"
SOURCE_STRUCTURED = "structured"
SOURCE_EXTENDED = "extended"
SOURCE_RAG = "rag"


@dataclass
class CitationRecord:
    """A single citation event."""
    source_type: str
    source_id: int
    source_dim: Optional[str] = None
    task_id: Optional[int] = None
    session_id: Optional[str] = None
    cited_at: str = ""


@dataclass
class CitationStats:
    """Aggregated citation statistics for a memory item."""
    source_type: str
    source_id: int
    cite_count: int
    first_cited: Optional[str]
    last_cited: Optional[str]


# ── Scoring ───────────────────────────────────────────────────────────

RECENCY_WINDOW_DAYS = 30


def citation_score(
    cite_count: int,
    last_cited_at: Optional[str] = None,
    age_days: int = 0,
) -> float:
    """Compute citation-weighted score for ranking.

    Formula:
        base = min(1.0, cite_count * 0.12)
        recency_boost = max(0, (30 - days_since_last_cite) / 30) * 0.25
        age_penalty = max(0.1, 1.0 - (age_days / 180)) * 0.1
        score = base + recency_boost + age_penalty

    Returns 0.0-1.0 range.
    """
    if cite_count == 0:
        return 0.0

    # Base: logarithmic-ish growth, caps at ~8 citations
    base = min(1.0, cite_count * 0.12)

    # Recency boost
    recency_boost = 0.0
    if last_cited_at:
        try:
            last_dt = datetime.fromisoformat(last_cited_at.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            days_since = max(0, (datetime.now(timezone.utc) - last_dt).total_seconds() / 86400)
            recency_boost = max(0.0, (RECENCY_WINDOW_DAYS - days_since) / RECENCY_WINDOW_DAYS) * 0.25
        except (ValueError, TypeError):
            pass

    # Age penalty (older memories are less relevant unless frequently cited)
    age_factor = max(0.1, 1.0 - (age_days / 180)) * 0.1

    return max(0.0, min(1.0, base + recency_boost + age_factor))


# ── Tracker ───────────────────────────────────────────────────────────

class CitationTracker:
    """Unified citation tracking across all memory types.

    Uses events.db for the citation_log table. Writes back cite_count
    to structured memory DB when source_type is 'structured'.
    """

    # Allowed dimension table names for SQL safety
    _VALID_DIMS = {"activity", "identity", "context", "preference", "experience", "persona"}

    def __init__(self, events_db=None, memory_db_path: Optional[str] = None):
        self._events_db = events_db
        self._memory_db_path = memory_db_path or str(_REPO_ROOT / "data" / "memory.db")

    def _get_events_db(self):
        if self._events_db is not None:
            return self._events_db
        try:
            from src.storage.events_db import EventsDB
            self._events_db = EventsDB()
            return self._events_db
        except Exception as e:
            log.debug(f"CitationTracker: events_db init failed: {e}")
            return None

    # ── Record ──

    def record(
        self,
        source_type: str,
        source_id: int,
        source_dim: Optional[str] = None,
        task_id: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """Record a single citation event.

        Writes to citation_log and updates source-specific counters.
        Returns True on success.
        """
        now = datetime.now(timezone.utc).isoformat()
        db = self._get_events_db()
        if not db:
            return False

        try:
            with db._connect() as conn:
                conn.execute(
                    "INSERT INTO citation_log "
                    "(source_type, source_id, source_dim, task_id, session_id, cited_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (source_type, source_id, source_dim, task_id, session_id, now),
                )
        except Exception as e:
            log.warning(f"citation: record failed: {e}")
            return False

        # Write-back to source-specific counters
        self._writeback(source_type, source_id, source_dim, now)
        return True

    def record_batch(
        self,
        records: list[dict],
        task_id: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """Record multiple citations in one transaction.

        Each dict in records: {source_type, source_id, source_dim?}
        Returns count of successfully recorded citations.
        """
        if not records:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        db = self._get_events_db()
        if not db:
            return 0

        count = 0
        try:
            with db._connect() as conn:
                for rec in records:
                    try:
                        conn.execute(
                            "INSERT INTO citation_log "
                            "(source_type, source_id, source_dim, task_id, session_id, cited_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                rec["source_type"],
                                rec["source_id"],
                                rec.get("source_dim"),
                                task_id,
                                session_id,
                                now,
                            ),
                        )
                        count += 1
                    except Exception:
                        continue
        except Exception as e:
            log.warning(f"citation: batch record failed: {e}")
            return count

        # Write-back for each unique source
        seen = set()
        for rec in records:
            key = (rec["source_type"], rec["source_id"], rec.get("source_dim"))
            if key not in seen:
                seen.add(key)
                self._writeback(rec["source_type"], rec["source_id"],
                                rec.get("source_dim"), now)

        log.info(f"citation: recorded {count} citations")
        return count

    def _writeback(
        self,
        source_type: str,
        source_id: int,
        source_dim: Optional[str],
        now: str,
    ):
        """Write-back cite_count to the source table."""
        try:
            if source_type == SOURCE_LEARNING:
                self._writeback_learning(source_id, now)
            elif source_type == SOURCE_STRUCTURED and source_dim:
                self._writeback_structured(source_id, source_dim, now)
        except Exception as e:
            log.debug(f"citation: writeback failed for {source_type}/{source_id}: {e}")

    def _writeback_learning(self, learning_id: int, now: str):
        """Increment hit_count on learnings table (events.db)."""
        db = self._get_events_db()
        if not db:
            return
        try:
            with db._connect() as conn:
                conn.execute(
                    "UPDATE learnings SET hit_count = COALESCE(hit_count, 0) + 1, "
                    "last_hit_at = ? WHERE id = ?",
                    (now, learning_id),
                )
        except Exception:
            pass

    def _writeback_structured(self, row_id: int, dimension: str, now: str):
        """Increment cite_count on structured memory table (memory.db).

        Adds cite_count/last_cited_at columns if they don't exist (migration).
        """
        if dimension not in self._VALID_DIMS:
            log.debug(f"citation: invalid dimension '{dimension}', skipping writeback")
            return
        conn = None
        try:
            conn = sqlite3.connect(self._memory_db_path)
            conn.row_factory = sqlite3.Row
            self._ensure_cite_columns(conn, dimension)
            conn.execute(
                f"UPDATE {dimension} SET "
                f"cite_count = COALESCE(cite_count, 0) + 1, "
                f"last_cited_at = ? WHERE id = ?",
                (now, row_id),
            )
            conn.commit()
        except Exception as e:
            log.debug(f"citation: structured writeback failed: {e}")
        finally:
            if conn:
                conn.close()

    @classmethod
    def _ensure_cite_columns(cls, conn: sqlite3.Connection, table: str):
        """Add cite_count/last_cited_at columns if missing (idempotent)."""
        if table not in cls._VALID_DIMS:
            return
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "cite_count" not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN cite_count INTEGER DEFAULT 0")
        if "last_cited_at" not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN last_cited_at TEXT")

    # ── Stats ──

    def get_stats(self, source_type: str, source_id: int) -> Optional[CitationStats]:
        """Get citation stats for a specific memory item."""
        db = self._get_events_db()
        if not db:
            return None

        try:
            with db._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt, MIN(cited_at) as first, MAX(cited_at) as last "
                    "FROM citation_log WHERE source_type = ? AND source_id = ?",
                    (source_type, source_id),
                ).fetchone()
                if row and row["cnt"] > 0:
                    return CitationStats(
                        source_type=source_type,
                        source_id=source_id,
                        cite_count=row["cnt"],
                        first_cited=row["first"],
                        last_cited=row["last"],
                    )
        except Exception:
            pass
        return None

    def top_cited(
        self,
        source_type: Optional[str] = None,
        limit: int = 20,
        days: int = 30,
    ) -> list[dict]:
        """Leaderboard: most-cited memories.

        Returns list of {source_type, source_id, source_dim, cite_count, last_cited}.
        """
        db = self._get_events_db()
        if not db:
            return []

        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        where = "WHERE cited_at >= ?"
        params: list = [cutoff]
        if source_type:
            where += " AND source_type = ?"
            params.append(source_type)

        try:
            with db._connect() as conn:
                rows = conn.execute(
                    f"SELECT source_type, source_id, source_dim, "
                    f"COUNT(*) as cite_count, MAX(cited_at) as last_cited "
                    f"FROM citation_log {where} "
                    f"GROUP BY source_type, source_id "
                    f"ORDER BY cite_count DESC LIMIT ?",
                    params + [limit],
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def summary(self) -> dict:
        """Overall citation stats for monitoring."""
        db = self._get_events_db()
        if not db:
            return {"total": 0}

        try:
            with db._connect() as conn:
                total = conn.execute("SELECT COUNT(*) FROM citation_log").fetchone()[0]
                by_type = conn.execute(
                    "SELECT source_type, COUNT(*) as cnt "
                    "FROM citation_log GROUP BY source_type"
                ).fetchall()
                return {
                    "total": total,
                    "by_type": {r["source_type"]: r["cnt"] for r in by_type},
                }
        except Exception:
            return {"total": 0}


# ── Module-level singleton ────────────────────────────────────────────

_tracker: Optional[CitationTracker] = None


def get_tracker() -> CitationTracker:
    """Get or create the module-level CitationTracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = CitationTracker()
    return _tracker
