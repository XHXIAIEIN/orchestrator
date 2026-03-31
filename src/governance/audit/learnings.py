"""
三分类 learnings — DB 是唯一数据源。

所有读写走 EventsDB.add_learning()，不再有 markdown 文件。
entry_type: 'error' | 'learning' | 'feature'
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ── Dedup integration (stolen from OpenViking) ──
try:
    from src.storage.dedup import check_duplicate as _check_duplicate
    _DEDUP_AVAILABLE = True
except ImportError:
    _DEDUP_AVAILABLE = False


@dataclass
class LearningEntry:
    entry_id: int
    pattern_key: str
    summary: str
    detail: str
    area: str
    occurrences: int = 1
    status: str = "pending"
    entry_type: str = "learning"


def _infer_related_keys(pattern_key: str) -> list[str]:
    """Infer cross-references from naming conventions.

    e.g. 'agent-output-budget-fix' → relates to 'agent-output-budget'
    """
    related = []
    if pattern_key.endswith("-fix"):
        related.append(pattern_key[:-4])
    elif pattern_key.endswith("-systematic"):
        base = pattern_key.replace("-systematic", "")
        related.append(base)
        related.append(base + "-random")
    return related


def _dedup_check(pattern_key: str, summary: str, area: str, db) -> tuple[bool, str | None]:
    """Run dedup check if available. Returns (should_store, reason).

    If dedup says "skip" but the match is the same pattern_key, allow through
    — add_learning handles recurrence bumping for same-key entries.
    On any failure, defaults to allowing storage.
    """
    if not _DEDUP_AVAILABLE:
        return True, None
    try:
        existing = db.get_learnings(area=area, limit=200)
        decision = _check_duplicate(summary, area, existing)
        if decision.action == "skip":
            # If the duplicate is the same pattern_key, let add_learning
            # handle it (recurrence bump). Only block truly different entries.
            if decision.existing_id is not None:
                matched = next((e for e in existing if e.get("id") == decision.existing_id), None)
                if matched and matched.get("pattern_key") == pattern_key:
                    return True, None  # same key = recurrence, not duplicate
            log.info(f"dedup: skipping '{pattern_key}' in '{area}' — {decision.reason}")
            return False, decision.reason
        if decision.action == "merge":
            log.info(f"dedup: merge candidate for '{pattern_key}' in '{area}' — {decision.reason}")
            # Let add_learning handle the merge via pattern_key match;
            # just log the fuzzy match for visibility
        return True, None
    except Exception as e:
        log.warning(f"dedup check failed (non-fatal): {e}")
        return True, None


def append_error(pattern_key, summary, detail, area, db):
    """Record an error pattern to DB."""
    should_store, reason = _dedup_check(pattern_key, summary, area, db)
    if not should_store:
        return None

    row_id = db.add_learning(
        pattern_key=pattern_key,
        rule=summary,
        detail=detail,
        area=area,
        entry_type="error",
        source_type="error",
        related_keys=_infer_related_keys(pattern_key),
    )
    return LearningEntry(
        entry_id=row_id, pattern_key=pattern_key,
        summary=summary, detail=detail, area=area,
        entry_type="error",
    )


def append_learning(pattern_key, summary, detail, area, db):
    """Record a learning/fix strategy to DB."""
    should_store, reason = _dedup_check(pattern_key, summary, area, db)
    if not should_store:
        return None

    row_id = db.add_learning(
        pattern_key=pattern_key,
        rule=summary,
        detail=detail,
        area=area,
        entry_type="learning",
        source_type="lesson",
        related_keys=_infer_related_keys(pattern_key),
    )
    return LearningEntry(
        entry_id=row_id, pattern_key=pattern_key,
        summary=summary, detail=detail, area=area,
        entry_type="learning",
    )


def append_feature(pattern_key, summary, detail, area, db):
    """Record a feature gap to DB."""
    should_store, reason = _dedup_check(pattern_key, summary, area, db)
    if not should_store:
        return None

    row_id = db.add_learning(
        pattern_key=pattern_key,
        rule=summary,
        detail=detail,
        area=area,
        entry_type="feature",
        source_type="feature",
        related_keys=_infer_related_keys(pattern_key),
    )
    return LearningEntry(
        entry_id=row_id, pattern_key=pattern_key,
        summary=summary, detail=detail, area=area,
        entry_type="feature",
    )


def get_promotable_entries(db, threshold=3):
    """Get entries ready for promotion from DB."""
    rows = db.get_promotable_learnings(threshold)
    return [
        LearningEntry(
            entry_id=r["id"], pattern_key=r["pattern_key"],
            summary=r["rule"], detail=r.get("detail", ""),
            area=r.get("area", "general"),
            occurrences=r["recurrence"],
            entry_type=r.get("entry_type", "learning"),
        )
        for r in rows
    ]


def check_blast_radius(file_count, max_files):
    return file_count <= max_files
