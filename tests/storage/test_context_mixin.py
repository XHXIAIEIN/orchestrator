"""Tests for context_store DB operations."""
import pytest
from src.storage.events_db import EventsDB

@pytest.fixture
def db(tmp_path):
    return EventsDB(str(tmp_path / "test.db"))

class TestContextStore:
    def test_upsert_and_get(self, db):
        db.upsert_context("sess-1", layer=0, key="identity:briefing",
                          content="You are Orchestrator.", token_est=10)
        row = db.get_context("sess-1", "identity:briefing")
        assert row is not None
        assert row["content"] == "You are Orchestrator."
        assert row["layer"] == 0
        assert row["token_est"] == 10

    def test_upsert_overwrites(self, db):
        db.upsert_context("sess-1", 0, "identity:briefing", "v1", 5)
        db.upsert_context("sess-1", 0, "identity:briefing", "v2", 6)
        row = db.get_context("sess-1", "identity:briefing")
        assert row["content"] == "v2"
        assert row["token_est"] == 6

    def test_list_keys_by_session(self, db):
        db.upsert_context("sess-1", 0, "identity:briefing", "brief", 10)
        db.upsert_context("sess-1", 1, "session:state", "state", 50)
        db.upsert_context("sess-2", 0, "identity:briefing", "other", 10)
        keys = db.list_context_keys("sess-1")
        assert len(keys) == 2
        assert keys[0]["key"] == "identity:briefing"

    def test_get_context_by_layer(self, db):
        db.upsert_context("sess-1", 0, "identity:briefing", "brief", 10)
        db.upsert_context("sess-1", 1, "session:state", "state", 50)
        db.upsert_context("sess-1", 2, "file:main.py", "code", 200)
        rows = db.get_context_by_layer("sess-1", layer=1)
        assert len(rows) == 1
        assert rows[0]["key"] == "session:state"

    def test_get_context_total_tokens(self, db):
        db.upsert_context("sess-1", 0, "a", "x", 100)
        db.upsert_context("sess-1", 1, "b", "y", 200)
        total = db.get_context_total_tokens("sess-1")
        assert total == 300

    def test_delete_session_context(self, db):
        db.upsert_context("sess-1", 0, "a", "x", 10)
        db.upsert_context("sess-1", 1, "b", "y", 20)
        db.delete_context_session("sess-1")
        keys = db.list_context_keys("sess-1")
        assert len(keys) == 0

    def test_delete_expired(self, db):
        db.upsert_context("sess-1", 2, "old", "data", 10,
                          expires_at="2020-01-01T00:00:00")
        db.upsert_context("sess-1", 0, "fresh", "data", 10)
        db.delete_expired_context()
        keys = db.list_context_keys("sess-1")
        assert len(keys) == 1
        assert keys[0]["key"] == "fresh"
