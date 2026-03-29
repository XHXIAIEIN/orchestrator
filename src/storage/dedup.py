"""Learning Dedup Pipeline — stolen from OpenViking.

Before inserting a new learning, check for near-duplicates using text similarity.
If a close match is found, merge (bump recurrence + append context) instead of creating.

Stages:
1. Exact match on pattern_key (already in LearningsMixin)
2. Fuzzy match on rule text (new — this module)

OpenViking uses embedding similarity + LLM judgment. We use SequenceMatcher
(stdlib) for now — zero dependencies, good enough for <1000 learnings.
Upgrade path: swap in embedding similarity when volume grows.
"""
import logging
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# Similarity threshold for considering two learnings as duplicates
SIMILARITY_THRESHOLD = 0.75


@dataclass
class DedupDecision:
    """Result of dedup check."""
    action: str  # "create", "skip", "merge"
    existing_id: Optional[int] = None
    similarity: float = 0.0
    reason: str = ""


def text_similarity(a: str, b: str) -> float:
    """Compute similarity ratio between two strings. 0.0-1.0."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def check_duplicate(new_rule: str, new_area: str, existing_learnings: list[dict],
                     threshold: float = SIMILARITY_THRESHOLD) -> DedupDecision:
    """Check if a new learning is a duplicate of any existing one.

    Args:
        new_rule: The rule text of the new learning.
        new_area: The area of the new learning.
        existing_learnings: List of dicts with keys: id, rule, area, pattern_key, recurrence.
        threshold: Similarity threshold (0.0-1.0).

    Returns:
        DedupDecision with action and optional existing_id to merge into.
    """
    if not new_rule or not existing_learnings:
        return DedupDecision(action="create", reason="no existing learnings to compare")

    best_match = None
    best_sim = 0.0

    for existing in existing_learnings:
        # Only compare within same area
        if existing.get("area") != new_area:
            continue

        sim = text_similarity(new_rule, existing.get("rule", ""))
        if sim > best_sim:
            best_sim = sim
            best_match = existing

    if best_match is None:
        return DedupDecision(action="create", similarity=0.0, reason="no learnings in same area")

    if best_sim >= 0.95:
        # Near-identical — skip (don't even merge, it's the same thing)
        return DedupDecision(
            action="skip",
            existing_id=best_match["id"],
            similarity=best_sim,
            reason=f"near-identical to '{best_match.get('pattern_key', '?')}' ({best_sim:.0%})",
        )

    if best_sim >= threshold:
        # Similar enough to merge
        return DedupDecision(
            action="merge",
            existing_id=best_match["id"],
            similarity=best_sim,
            reason=f"similar to '{best_match.get('pattern_key', '?')}' ({best_sim:.0%})",
        )

    return DedupDecision(action="create", similarity=best_sim, reason="no close match found")


class DedupPipeline:
    """Wrap dedup check into a reusable pipeline."""

    def __init__(self, db, threshold: float = SIMILARITY_THRESHOLD):
        self.db = db
        self.threshold = threshold
        self._stats = {"created": 0, "merged": 0, "skipped": 0}

    def add_learning_deduped(
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
    ) -> tuple[str, int]:
        """Add a learning with dedup. Returns (action, learning_id).

        action is one of: "created", "merged", "skipped".
        """
        # Stage 1: exact pattern_key match (handled by add_learning itself)
        # Stage 2: fuzzy rule text match
        existing = self.db.get_learnings(area=area, limit=200)

        decision = check_duplicate(rule, area, existing, self.threshold)

        if decision.action == "skip":
            log.info(f"dedup: skipping '{pattern_key}' — {decision.reason}")
            self._stats["skipped"] += 1
            return ("skipped", decision.existing_id)

        if decision.action == "merge":
            log.info(f"dedup: merging '{pattern_key}' into #{decision.existing_id} — {decision.reason}")
            # Bump recurrence and append context on the existing learning
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            with self.db._connect() as conn:
                conn.execute(
                    "UPDATE learnings SET recurrence = recurrence + 1, "
                    "context = CASE WHEN ? != '' THEN context || '\\n' || ? ELSE context END, "
                    "last_hit_at = ? "
                    "WHERE id = ?",
                    (context, context, now, decision.existing_id),
                )
            self._stats["merged"] += 1
            return ("merged", decision.existing_id)

        # Create new
        learning_id = self.db.add_learning(
            pattern_key, rule, area=area, context=context,
            source_type=source_type, department=department,
            task_id=task_id, ttl_days=ttl_days,
        )
        self._stats["created"] += 1
        return ("created", learning_id)

    def get_stats(self) -> dict:
        return dict(self._stats)
