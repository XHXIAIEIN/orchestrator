"""Tests for DigestBuilder — daily/weekly signal aggregation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.proactive.digest import DigestBuilder


@pytest.fixture
def db(tmp_path):
    """Isolated EventsDB with proactive_log table."""
    from src.storage.events_db import EventsDB
    _db = EventsDB(str(tmp_path / "test_digest.db"))
    return _db


@pytest.fixture
def builder(db):
    return DigestBuilder(db)


def _seed_logs(db, entries):
    """Insert proactive_log entries. Each entry: (signal_id, tier, severity, data, message, action, created_at)."""
    with db._connect() as conn:
        for e in entries:
            conn.execute(
                "INSERT INTO proactive_log (signal_id, tier, severity, data, message, action, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                e,
            )


class TestBuildDaily:
    def test_empty_returns_none(self, builder):
        result = builder.build_daily()
        assert result is None

    def test_returns_summary_with_sent_signals(self, db, builder):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(hours=2)).isoformat()
        _seed_logs(db, [
            ("S1", "A", "critical", '{"collector":"rss"}', "RSS挂了", "sent", recent),
            ("S3", "A", "high", '{"size_mb":55}', "DB大了", "sent", recent),
            ("S7", "B", "medium", '{"count":5}', "重复错误", "sent", recent),
            ("S11", "D", "low", '{}', "GitHub通知", "throttled", recent),
        ])
        result = builder.build_daily()
        assert result is not None
        assert "S1" in result or "RSS" in result  # Should contain signal references
        assert "3" in result  # 3 sent signals

    def test_excludes_old_logs(self, db, builder):
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        _seed_logs(db, [
            ("S1", "A", "critical", '{}', "旧信号", "sent", old),
        ])
        result = builder.build_daily()
        assert result is None


class TestBuildWeekly:
    def test_empty_returns_none(self, builder):
        result = builder.build_weekly()
        assert result is None

    def test_returns_trend_summary(self, db, builder):
        now = datetime.now(timezone.utc)
        for day_offset in range(5):
            ts = (now - timedelta(days=day_offset, hours=3)).isoformat()
            _seed_logs(db, [
                ("S1", "A", "critical", '{}', "采集器挂", "sent", ts),
            ])
        result = builder.build_weekly()
        assert result is not None
        assert "5" in result  # 5 total signals across the week
