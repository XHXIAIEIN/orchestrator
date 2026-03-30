"""
三分类 learnings — DB 是唯一数据源。

所有读写走 EventsDB.add_learning()，不再有 markdown 文件。
entry_type: 'error' | 'learning' | 'feature'
"""
from __future__ import annotations

import re
from dataclasses import dataclass


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


def append_error(pattern_key, summary, detail, area, db):
    """Record an error pattern to DB."""
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
