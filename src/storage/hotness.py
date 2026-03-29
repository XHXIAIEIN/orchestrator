"""Hotness Scorer -- stolen from OpenViking memory hot/cold separation.

Scores learnings by access frequency + recency decay.
Hot learnings get cached in Redis. Cold learnings get archived.

Score formula:
    hotness = hit_count * recency_weight
    recency_weight = max(0.1, 1.0 - (days_since_last_hit / 30))

Tiers:
    hot:  hotness >= 5.0  -> Redis cache + active
    warm: hotness >= 1.0  -> active (SQLite only)
    cold: hotness < 1.0   -> candidate for archival
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class HotnessResult:
    learning_id: int
    pattern_key: str
    score: float
    tier: str  # "hot", "warm", "cold"


HOT_THRESHOLD = 5.0
WARM_THRESHOLD = 1.0
RECENCY_WINDOW_DAYS = 30


def score_hotness(hit_count: int, last_hit_at: str | None, created_at: str | None = None) -> float:
    """Calculate hotness score for a learning."""
    if hit_count == 0:
        return 0.0

    # Recency weight: decays from 1.0 to 0.1 over RECENCY_WINDOW_DAYS
    if last_hit_at:
        try:
            last_hit = datetime.fromisoformat(last_hit_at.replace('Z', '+00:00'))
            days_ago = (datetime.now(timezone.utc) - last_hit).total_seconds() / 86400
            recency = max(0.1, 1.0 - (days_ago / RECENCY_WINDOW_DAYS))
        except (ValueError, TypeError):
            recency = 0.5
    else:
        recency = 0.5

    return round(hit_count * recency, 2)


def classify_tier(score: float) -> str:
    """Classify a hotness score into a tier."""
    if score >= HOT_THRESHOLD:
        return "hot"
    elif score >= WARM_THRESHOLD:
        return "warm"
    return "cold"


class HotnessScorer:
    """Score and classify all learnings by hotness."""

    def __init__(self, db):
        self.db = db

    def score_all(self) -> list[HotnessResult]:
        """Score all active learnings. Returns sorted by score descending."""
        with self.db._connect() as conn:
            rows = conn.execute(
                "SELECT id, pattern_key, COALESCE(hit_count, 0) as hit_count, "
                "last_hit_at, created_at "
                "FROM learnings WHERE status IN ('pending', 'promoted')"
            ).fetchall()

        results = []
        for row in rows:
            score = score_hotness(row["hit_count"], row["last_hit_at"], row["created_at"])
            results.append(HotnessResult(
                learning_id=row["id"],
                pattern_key=row["pattern_key"],
                score=score,
                tier=classify_tier(score),
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def get_tier_stats(self) -> dict:
        """Return count of learnings per tier."""
        all_scores = self.score_all()
        stats = {"hot": 0, "warm": 0, "cold": 0, "total": len(all_scores)}
        for r in all_scores:
            stats[r.tier] += 1
        return stats

    def archive_cold(self, min_age_days: int = 7) -> int:
        """Archive cold learnings older than min_age_days. Returns count archived."""
        all_scores = self.score_all()
        cold = [r for r in all_scores if r.tier == "cold"]

        if not cold:
            return 0

        cutoff = (datetime.now(timezone.utc) - timedelta(days=min_age_days)).isoformat()
        archived = 0
        now = datetime.now(timezone.utc).isoformat()

        with self.db._connect() as conn:
            for r in cold:
                # Only archive if old enough
                row = conn.execute(
                    "SELECT created_at FROM learnings WHERE id = ?", (r.learning_id,)
                ).fetchone()
                if row and row["created_at"] < cutoff:
                    conn.execute(
                        "UPDATE learnings SET status = 'archived', retired_at = ? WHERE id = ?",
                        (now, r.learning_id),
                    )
                    archived += 1

        if archived:
            log.info(f"hotness: archived {archived} cold learnings")
        return archived

    def cache_hot_to_redis(self, redis_cache) -> int:
        """Push hot learnings to Redis for fast access. Returns count cached."""
        if not redis_cache.available:
            return 0

        all_scores = self.score_all()
        hot = [r for r in all_scores if r.tier == "hot"]

        if not hot:
            return 0

        # Load full learning data for hot items
        hot_ids = [r.learning_id for r in hot]
        with self.db._connect() as conn:
            placeholders = ",".join("?" * len(hot_ids))
            rows = conn.execute(
                f"SELECT id, pattern_key, rule, area, department "
                f"FROM learnings WHERE id IN ({placeholders})",
                hot_ids,
            ).fetchall()

        cached = 0
        for row in rows:
            key = f"learning:hot:{row['id']}"
            data = dict(row)
            if redis_cache.set_json(key, data, ttl=3600):  # 1h TTL
                cached += 1

        # Also cache the hot ID list for quick lookup
        hot_index = [{"id": r.learning_id, "key": r.pattern_key, "score": r.score} for r in hot]
        redis_cache.set_json("learnings:hot_index", hot_index, ttl=3600)

        if cached:
            log.info(f"hotness: cached {cached} hot learnings to Redis")
        return cached
