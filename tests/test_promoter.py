import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.storage.events_db import EventsDB
from src.governance.audit.learnings import append_error
from src.governance.audit.promoter import promote_to_boot, scan_and_promote


def _make_db(tmp_path):
    return EventsDB(str(tmp_path / "test.db"))


def _setup_errors_with_repeats(tmp_path, pattern_key, count):
    db = _make_db(tmp_path)
    for i in range(count):
        append_error(pattern_key, f"Error #{i+1}", "Same issue repeating", "engineering", db=db)
    return db


def test_promote_to_boot(tmp_path):
    boot_md = tmp_path / "boot.md"
    boot_md.write_text(
        "# Boot\n\n## Learnings\n\n"
        "Hard-won rules from past mistakes.\n\n"
        "- Existing learning [engineering]\n"
    )
    promote_to_boot(
        boot_path=str(boot_md),
        pattern_key="docker-rebuild-unnecessary",
        summary="Don't rebuild Docker image for config-only changes; restart is enough",
        area="operations",
    )
    text = boot_md.read_text()
    assert "docker-rebuild-unnecessary" in text or "Don't rebuild Docker" in text
    assert "Existing learning" in text
    assert text.count("## Learnings") == 1


def test_scan_and_promote(tmp_path):
    db = _setup_errors_with_repeats(tmp_path, "repeated-timeout", 4)
    boot_md = tmp_path / "boot.md"
    boot_md.write_text("# Boot\n\n## Learnings\n\n- Old learning [misc]\n")
    promoted = scan_and_promote(
        db=db,
        boot_path=str(boot_md),
        threshold=3,
    )
    assert len(promoted) == 1
    assert promoted[0] == "repeated-timeout"
    assert "repeated-timeout" in boot_md.read_text() or "Error #" in boot_md.read_text()


def test_no_double_promotion(tmp_path):
    db = _setup_errors_with_repeats(tmp_path, "already-done", 5)
    boot_md = tmp_path / "boot.md"
    boot_md.write_text("# Boot\n\n## Learnings\n\n")
    scan_and_promote(db, str(boot_md), threshold=3)
    first_text = boot_md.read_text()
    promoted = scan_and_promote(db, str(boot_md), threshold=3)
    assert len(promoted) == 0
    assert boot_md.read_text() == first_text
