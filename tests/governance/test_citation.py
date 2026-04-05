"""Tests for Citation Tracker (I8)."""
import os
import sqlite3
import tempfile
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from src.governance.context.citation import (
    CitationTracker,
    citation_score,
    CitationStats,
    SOURCE_LEARNING,
    SOURCE_STRUCTURED,
)
from src.governance.context.confidence_ranker import compute_confidence


# ── Scoring tests ─────────────────────────────────────────────────────

def test_citation_score_zero():
    assert citation_score(0) == 0.0


def test_citation_score_increases_with_count():
    s1 = citation_score(1)
    s3 = citation_score(3)
    s6 = citation_score(6)
    assert 0 < s1 < s3 < s6


def test_citation_score_caps_at_one():
    s = citation_score(100, datetime.now(timezone.utc).isoformat())
    assert s <= 1.0


def test_citation_score_recency_boost():
    now = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    recent = citation_score(3, now)
    stale = citation_score(3, old)
    assert recent > stale


# ── confidence_ranker with cite_count ─────────────────────────────────

def test_compute_confidence_with_citations():
    base = compute_confidence(apply_count=1, recurrence=1, days_since_access=5)
    boosted = compute_confidence(apply_count=1, recurrence=1, days_since_access=5, cite_count=5)
    assert boosted > base


def test_compute_confidence_citation_cap():
    # cite_count capped at 0.3 boost (6 * 0.05 = 0.3)
    c6 = compute_confidence(cite_count=6)
    c100 = compute_confidence(cite_count=100)
    assert c6 == c100  # both capped at 0.3


# ── Tracker with real SQLite ──────────────────────────────────────────

@pytest.fixture
def tracker_dbs(tmp_path):
    """Create temp events.db and memory.db for testing."""
    events_path = str(tmp_path / "events.db")
    memory_path = str(tmp_path / "memory.db")

    # Set up events.db with citation_log + learnings tables
    conn = sqlite3.connect(events_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE citation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            source_dim TEXT,
            task_id INTEGER,
            session_id TEXT,
            cited_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );
        CREATE INDEX idx_citation_source ON citation_log(source_type, source_id);

        CREATE TABLE learnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_key TEXT NOT NULL UNIQUE,
            area TEXT DEFAULT 'general',
            rule TEXT NOT NULL,
            context TEXT DEFAULT '',
            source_type TEXT DEFAULT 'error',
            status TEXT DEFAULT 'pending',
            recurrence INTEGER DEFAULT 1,
            hit_count INTEGER DEFAULT 0,
            last_hit_at TEXT,
            created_at TEXT NOT NULL
        );
    """)
    # Insert a test learning
    conn.execute(
        "INSERT INTO learnings (pattern_key, rule, created_at) VALUES (?, ?, ?)",
        ("test-pattern", "Don't do X", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    # Set up memory.db with a dimension table
    mconn = sqlite3.connect(memory_path)
    mconn.executescript("""
        CREATE TABLE identity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact TEXT NOT NULL,
            category TEXT DEFAULT '',
            subject TEXT DEFAULT '',
            confidence REAL DEFAULT 0.9,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            tags TEXT DEFAULT '[]'
        );
    """)
    mconn.execute(
        "INSERT INTO identity (fact, created_at, updated_at) VALUES (?, ?, ?)",
        ("test fact", datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
    )
    mconn.commit()
    mconn.close()

    # Create a mock events_db that provides _connect()
    mock_db = MagicMock()
    mock_db._connect.return_value.__enter__ = lambda s: sqlite3.connect(events_path, isolation_level=None)
    # Actually, we need a real connection manager
    class FakeEventsDB:
        def __init__(self, path):
            self._path = path
        def _connect(self):
            conn = sqlite3.connect(self._path)
            conn.row_factory = sqlite3.Row
            return conn

    fake_db = FakeEventsDB(events_path)
    tracker = CitationTracker(events_db=fake_db, memory_db_path=memory_path)
    return tracker, events_path, memory_path


class _ContextMgr:
    """Adapter to make FakeEventsDB._connect() work as context manager."""
    def __init__(self, conn):
        self._conn = conn
    def __enter__(self):
        return self._conn
    def __exit__(self, *args):
        self._conn.commit()


@pytest.fixture
def tracker(tmp_path):
    """Create a tracker with properly mocked DB."""
    events_path = str(tmp_path / "events.db")
    memory_path = str(tmp_path / "memory.db")

    # events.db
    conn = sqlite3.connect(events_path)
    conn.executescript("""
        CREATE TABLE citation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            source_dim TEXT,
            task_id INTEGER,
            session_id TEXT,
            cited_at TEXT NOT NULL
        );
        CREATE TABLE learnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_key TEXT NOT NULL UNIQUE,
            rule TEXT NOT NULL,
            hit_count INTEGER DEFAULT 0,
            last_hit_at TEXT,
            created_at TEXT NOT NULL
        );
    """)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO learnings (pattern_key, rule, created_at) VALUES (?, ?, ?)",
                 ("pk1", "rule1", now))
    conn.commit()
    conn.close()

    # memory.db
    mconn = sqlite3.connect(memory_path)
    mconn.executescript("""
        CREATE TABLE identity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact TEXT NOT NULL,
            confidence REAL DEFAULT 0.9,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            tags TEXT DEFAULT '[]'
        );
    """)
    mconn.execute("INSERT INTO identity (fact, created_at, updated_at) VALUES (?, ?, ?)",
                  ("user is dev", now, now))
    mconn.commit()
    mconn.close()

    class FakeDB:
        def __init__(self, path):
            self._path = path
        def _connect(self):
            return _ConnCtx(self._path)

    class _ConnCtx:
        def __init__(self, path):
            self._path = path
            self._conn = None
        def __enter__(self):
            self._conn = sqlite3.connect(self._path)
            self._conn.row_factory = sqlite3.Row
            return self._conn
        def __exit__(self, *args):
            if self._conn:
                self._conn.commit()
                self._conn.close()

    return CitationTracker(events_db=FakeDB(events_path), memory_db_path=memory_path)


def test_record_learning_citation(tracker):
    assert tracker.record(SOURCE_LEARNING, 1, task_id=42)


def test_record_structured_citation(tracker):
    assert tracker.record(SOURCE_STRUCTURED, 1, source_dim="identity", task_id=42)


def test_record_updates_learning_hit_count(tracker):
    tracker.record(SOURCE_LEARNING, 1, task_id=10)
    tracker.record(SOURCE_LEARNING, 1, task_id=11)
    # Check hit_count was incremented
    db = tracker._get_events_db()
    with db._connect() as conn:
        row = conn.execute("SELECT hit_count FROM learnings WHERE id = 1").fetchone()
        assert row["hit_count"] == 2


def test_record_creates_cite_columns_on_structured(tracker):
    tracker.record(SOURCE_STRUCTURED, 1, source_dim="identity")
    # Check cite_count column was added and incremented
    conn = sqlite3.connect(tracker._memory_db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT cite_count, last_cited_at FROM identity WHERE id = 1").fetchone()
    conn.close()
    assert row["cite_count"] == 1
    assert row["last_cited_at"] is not None


def test_record_batch(tracker):
    records = [
        {"source_type": SOURCE_LEARNING, "source_id": 1},
        {"source_type": SOURCE_STRUCTURED, "source_id": 1, "source_dim": "identity"},
    ]
    count = tracker.record_batch(records, task_id=99)
    assert count == 2


def test_get_stats(tracker):
    tracker.record(SOURCE_LEARNING, 1)
    tracker.record(SOURCE_LEARNING, 1)
    stats = tracker.get_stats(SOURCE_LEARNING, 1)
    assert stats is not None
    assert stats.cite_count == 2


def test_get_stats_empty(tracker):
    stats = tracker.get_stats(SOURCE_LEARNING, 999)
    assert stats is None


def test_top_cited(tracker):
    for _ in range(5):
        tracker.record(SOURCE_LEARNING, 1)
    tracker.record(SOURCE_STRUCTURED, 1, source_dim="identity")

    top = tracker.top_cited(limit=10)
    assert len(top) >= 1
    assert top[0]["cite_count"] == 5  # learning cited 5 times


def test_summary(tracker):
    tracker.record(SOURCE_LEARNING, 1)
    tracker.record(SOURCE_STRUCTURED, 1, source_dim="identity")
    s = tracker.summary()
    assert s["total"] == 2
    assert SOURCE_LEARNING in s["by_type"]
    assert SOURCE_STRUCTURED in s["by_type"]
