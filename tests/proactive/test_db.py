"""Tests for ProactiveMixin and proactive_log schema."""

import pytest
from src.storage.events_db import EventsDB


@pytest.fixture
def db(tmp_path):
    return EventsDB(str(tmp_path / "test.db"))


def test_log_proactive_returns_positive_rowid_sent(db):
    row_id = db.log_proactive(
        signal_id="sig-001",
        tier="T1",
        severity="high",
        data={"key": "value"},
        message="Test sent",
        action="sent",
        reason="threshold exceeded",
    )
    assert isinstance(row_id, int)
    assert row_id > 0


def test_log_proactive_returns_positive_rowid_throttled(db):
    row_id = db.log_proactive(
        signal_id="sig-002",
        tier="T2",
        severity="low",
        data=None,
        message="Throttled",
        action="throttled",
    )
    assert isinstance(row_id, int)
    assert row_id > 0


def test_recent_proactive_logs_count_and_order(db):
    # Insert 3 entries
    db.log_proactive("s1", "T1", "high", None, "msg1", "sent")
    db.log_proactive("s2", "T1", "medium", None, "msg2", "throttled")
    db.log_proactive("s3", "T2", "low", None, "msg3", "sent")

    logs = db.recent_proactive_logs(limit=10)
    assert len(logs) == 3
    # Most recent first — row ids should be descending
    assert logs[0]["signal_id"] == "s3"
    assert logs[1]["signal_id"] == "s2"
    assert logs[2]["signal_id"] == "s1"


def test_recent_proactive_logs_respects_limit(db):
    for i in range(5):
        db.log_proactive(f"s{i}", "T1", "high", None, f"msg{i}", "sent")

    logs = db.recent_proactive_logs(limit=3)
    assert len(logs) == 3


def test_proactive_log_table_exists(db):
    tables = db.get_tables()
    assert "proactive_log" in tables


def test_proactive_log_stats_counts(db):
    db.log_proactive("s1", "T1", "high", None, "m1", "sent")
    db.log_proactive("s2", "T1", "high", None, "m2", "sent")
    db.log_proactive("s3", "T1", "low", None, "m3", "throttled")

    stats = db.proactive_log_stats(hours=24)
    assert stats["sent"] == 2
    assert stats["throttled"] == 1
    assert stats["period_hours"] == 24


def test_proactive_log_stats_empty(db):
    stats = db.proactive_log_stats(hours=24)
    assert stats["sent"] == 0
    assert stats["throttled"] == 0
