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


def test_profile_analysis_table_exists(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    assert "profile_analysis" in db.get_tables()


def test_save_and_get_profile_analysis(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    data = {"overview": "测试概述", "strengths": ["专注"], "type": "periodic"}
    db.save_profile_analysis(data, "periodic")
    result = db.get_profile_analysis()
    assert result["overview"] == "测试概述"
    assert result["type"] == "periodic"


def test_profile_analysis_pruning(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    for i in range(55):
        db.save_profile_analysis({"overview": f"entry {i}"}, "periodic")
    with db._connect() as conn:
        count = conn.execute("SELECT COUNT(*) as c FROM profile_analysis").fetchone()["c"]
    assert count == 50


def test_get_events_by_day(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    db.insert_event("claude", "coding", "test", 10, 0.5, [], {})
    result = db.get_events_by_day(days=7)
    assert len(result) == 1
    assert "day" in result[0]
    assert "count" in result[0]
    assert result[0]["count"] == 1


def test_get_profile_analysis_by_type(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    db.save_profile_analysis({"overview": "periodic overview"}, "periodic")
    db.save_profile_analysis({"overview": "daily overview"}, "daily")
    daily = db.get_profile_analysis("daily")
    periodic = db.get_profile_analysis("periodic")
    assert daily["overview"] == "daily overview"
    assert periodic["overview"] == "periodic overview"


def test_get_events_by_category(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    db.insert_event("claude", "coding", "test1", 30, 0.5, [], {})
    db.insert_event("browser", "reading", "test2", 20, 0.5, [], {})
    result = db.get_events_by_category(days=7)
    categories = {r["category"] for r in result}
    assert "coding" in categories
    assert "reading" in categories
