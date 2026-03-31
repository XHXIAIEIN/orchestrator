"""Tests for ContextWriter — populates context_store before dispatch."""
import pytest
from src.storage.events_db import EventsDB
from src.governance.context.writer import ContextWriter

@pytest.fixture
def db(tmp_path):
    return EventsDB(str(tmp_path / "test.db"))

@pytest.fixture
def writer(db):
    return ContextWriter(db, "sess-test")

class TestContextWriter:
    def test_write_layer0_creates_identity(self, writer, db):
        task = {"action": "test task", "spec": {"problem": "test problem"}}
        writer.write_layer0(task, "engineering")
        row = db.get_context("sess-test", "identity:briefing")
        assert row is not None
        assert len(row["content"]) > 0

    def test_write_layer0_creates_catalog(self, writer, db):
        task = {"action": "test task", "spec": {}}
        writer.write_layer0(task, "engineering")
        row = db.get_context("sess-test", "catalog")
        assert row is not None
        assert "ctx_read" in row["content"]

    def test_write_layer1_session_state(self, writer, db):
        writer.write_layer1(conversation_summary="User asked to fix a bug.")
        row = db.get_context("sess-test", "session:conversation_summary")
        assert row["content"] == "User asked to fix a bug."
        assert row["layer"] == 1

    def test_write_layer1_git_diff(self, writer, db):
        writer.write_layer1(git_diff="diff --git a/main.py")
        row = db.get_context("sess-test", "session:git_diff")
        assert "main.py" in row["content"]

    def test_write_chain_output(self, writer, db):
        writer.write_chain_output(42, "task 42 output with nextBatch")
        row = db.get_context("sess-test", "chain:42")
        assert row["content"] == "task 42 output with nextBatch"
        assert row["layer"] == 1

    def test_write_layer2_file(self, writer, db):
        writer.write_file("src/main.py", "print('hello')")
        row = db.get_context("sess-test", "file:src/main.py")
        assert row["layer"] == 2
        assert row["content"] == "print('hello')"

    def test_write_layer2_memory(self, writer, db):
        writer.write_memory("guidelines", "Always use type hints.")
        row = db.get_context("sess-test", "memory:guidelines")
        assert row["layer"] == 2

    def test_catalog_lists_all_keys(self, writer, db):
        writer.write_layer1(conversation_summary="summary here")
        writer.write_file("src/main.py", "code")
        # Rebuild catalog
        writer.write_layer0({"action": "test", "spec": {}}, "engineering")
        catalog = db.get_context("sess-test", "catalog")
        assert "session:conversation_summary" in catalog["content"]
        assert "file:src/main.py" in catalog["content"]
