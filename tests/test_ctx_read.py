"""Tests for ctx_read CLI — sub-agent context retrieval tool."""
import subprocess
import sys
import pytest
from src.storage.events_db import EventsDB

_WIN_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = EventsDB(db_path)
    db.upsert_context("sess-1", 0, "identity:briefing", "You are a test agent.", 10)
    db.upsert_context("sess-1", 1, "session:state", '{"practiceId": "prac-123"}', 20)
    db.upsert_context("sess-1", 2, "file:main.py", "print('hello')", 5)
    return db_path

def _run_ctx_read(db_path: str, *args) -> str:
    result = subprocess.run(
        [sys.executable, "scripts/ctx_read.py", "--db", db_path, *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL, text=True, cwd=".",
        creationflags=_WIN_FLAGS,
    )
    return result.stdout.strip()

class TestCtxRead:
    def test_read_specific_key(self, db):
        out = _run_ctx_read(db, "--session", "sess-1", "--key", "identity:briefing")
        assert "You are a test agent." in out

    def test_read_layer(self, db):
        out = _run_ctx_read(db, "--session", "sess-1", "--layer", "1")
        assert "practiceId" in out

    def test_list_keys(self, db):
        out = _run_ctx_read(db, "--session", "sess-1", "--list")
        assert "identity:briefing" in out
        assert "session:state" in out
        assert "file:main.py" in out

    def test_missing_key_returns_not_found(self, db):
        out = _run_ctx_read(db, "--session", "sess-1", "--key", "nonexistent")
        assert "not found" in out.lower()

    def test_budget_tracking(self, db):
        out = _run_ctx_read(db, "--session", "sess-1", "--key", "identity:briefing",
                            "--budget", "5")
        # 10 tokens exceeds budget of 5
        assert "budget" in out.lower()
