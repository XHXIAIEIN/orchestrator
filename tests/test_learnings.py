import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.governance.audit.learnings import (
    LearningEntry, append_learning, append_error, append_feature,
    get_pattern_occurrences, get_promotable_entries,
)


def test_append_error_creates_entry(tmp_path):
    errors_md = tmp_path / "ERRORS.md"
    errors_md.write_text("# Errors\n\n<!-- entries below this line are auto-managed -->\n")
    entry = append_error(
        pattern_key="docker-rebuild-unnecessary",
        summary="Rebuilt Docker image when only config changed",
        detail="Task failed because full rebuild took 5 min.",
        area="operations",
        file_path=str(errors_md),
    )
    assert entry.entry_id.startswith("ERR-")
    assert entry.pattern_key == "docker-rebuild-unnecessary"
    assert entry.occurrences == 1
    assert "docker-rebuild-unnecessary" in errors_md.read_text()


def test_append_error_increments_occurrences(tmp_path):
    errors_md = tmp_path / "ERRORS.md"
    errors_md.write_text("# Errors\n\n<!-- entries below this line are auto-managed -->\n")
    append_error("timeout-on-large-query", "Query timed out", "SQL took >30s", "engineering", str(errors_md))
    append_error("timeout-on-large-query", "Query timed out again", "Same pattern", "engineering", str(errors_md))
    entry = append_error("timeout-on-large-query", "Third timeout", "Still happening", "engineering", str(errors_md))
    assert entry.occurrences == 3


def test_append_learning(tmp_path):
    learn_md = tmp_path / "LEARNINGS.md"
    learn_md.write_text("# Learnings\n\n<!-- entries below this line are auto-managed -->\n")
    entry = append_learning(
        pattern_key="pnpm-not-npm",
        summary="Project uses pnpm, not npm",
        detail="Always check lockfile before assuming package manager.",
        area="config",
        file_path=str(learn_md),
    )
    assert entry.entry_id.startswith("LRN-")
    assert entry.status == "active"


def test_get_promotable_entries(tmp_path):
    errors_md = tmp_path / "ERRORS.md"
    errors_md.write_text("# Errors\n\n<!-- entries below this line are auto-managed -->\n")
    for _ in range(3):
        append_error("repeated-mistake", "Same error", "Details", "engineering", str(errors_md))
    promotable = get_promotable_entries(str(errors_md), threshold=3)
    assert len(promotable) == 1
    assert promotable[0].pattern_key == "repeated-mistake"


def test_get_pattern_occurrences(tmp_path):
    errors_md = tmp_path / "ERRORS.md"
    errors_md.write_text("# Errors\n\n<!-- entries below this line are auto-managed -->\n")
    append_error("some-pattern", "Error A", "Detail", "ops", str(errors_md))
    append_error("some-pattern", "Error B", "Detail", "ops", str(errors_md))
    assert get_pattern_occurrences(str(errors_md), "some-pattern") == 2
    assert get_pattern_occurrences(str(errors_md), "nonexistent") == 0
