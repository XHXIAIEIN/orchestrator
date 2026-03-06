import pytest
from src.storage.events_db import EventsDB


def test_creates_tables(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    tables = db.get_tables()
    assert "events" in tables
    assert "daily_summaries" in tables
    assert "user_profile" in tables


def test_insert_and_query_event(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    db.insert_event(
        source="claude", category="coding",
        title="orchestrator 设计对话",
        duration_minutes=45, score=0.8,
        tags=["python", "agent"], metadata={"tokens": 3200}
    )
    events = db.get_recent_events(days=1)
    assert len(events) == 1
    assert events[0]["source"] == "claude"
    assert events[0]["score"] == 0.8


def test_dedup_prevents_duplicate(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    db.insert_event("claude", "coding", "同一个对话", 30, 0.5, [], {}, dedup_key="abc123")
    db.insert_event("claude", "coding", "同一个对话", 30, 0.5, [], {}, dedup_key="abc123")
    events = db.get_recent_events(days=1)
    assert len(events) == 1


def test_get_storage_size(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    size = db.get_size_bytes()
    assert isinstance(size, int)
    assert size >= 0
