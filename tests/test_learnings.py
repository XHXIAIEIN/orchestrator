import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.storage.events_db import EventsDB
from src.governance.audit.learnings import (
    LearningEntry, append_learning, append_error, append_feature,
    get_promotable_entries,
)


def _make_db(tmp_path):
    db = EventsDB(str(tmp_path / "test.db"))
    return db


def test_append_error_creates_entry(tmp_path):
    db = _make_db(tmp_path)
    entry = append_error(
        pattern_key="docker-rebuild-unnecessary",
        summary="Rebuilt Docker image when only config changed",
        detail="Task failed because full rebuild took 5 min.",
        area="operations",
        db=db,
    )
    assert isinstance(entry.entry_id, int)
    assert entry.pattern_key == "docker-rebuild-unnecessary"


def test_append_error_increments_occurrences(tmp_path):
    db = _make_db(tmp_path)
    append_error("timeout-on-large-query", "Query timed out", "SQL took >30s", "engineering", db=db)
    append_error("timeout-on-large-query", "Query timed out again", "Same pattern", "engineering", db=db)
    rows = db.get_learnings(area="engineering")
    assert rows[0]["recurrence"] == 2


def test_append_learning(tmp_path):
    db = _make_db(tmp_path)
    entry = append_learning(
        pattern_key="pnpm-not-npm",
        summary="Project uses pnpm, not npm",
        detail="Always check lockfile before assuming package manager.",
        area="config",
        db=db,
    )
    assert entry.entry_type == "learning"


def test_get_promotable_entries(tmp_path):
    db = _make_db(tmp_path)
    for _ in range(3):
        append_error("repeated-mistake", "Same error", "Details", "engineering", db=db)
    promotable = get_promotable_entries(db, threshold=3)
    assert len(promotable) == 1
    assert promotable[0].pattern_key == "repeated-mistake"
