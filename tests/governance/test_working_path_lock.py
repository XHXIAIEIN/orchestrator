"""Tests for src.governance.working_path_lock — DB row-level path locking."""
import pytest
from src.governance.working_path_lock import WorkingPathLock


class TestWorkingPathLock:
    def test_acquire_and_release(self, tmp_path):
        lock = WorkingPathLock(db_path=str(tmp_path / "test.db"))
        result = lock.acquire("task-1", "/test/path", agent_id="agent-1")
        assert result.acquired is True
        released = lock.release("task-1")
        assert released is True

    def test_double_acquire_same_task(self, tmp_path):
        lock = WorkingPathLock(db_path=str(tmp_path / "test.db"))
        lock.acquire("task-1", "/test/path", agent_id="agent-1")
        # Same task re-acquiring should succeed (upsert)
        result = lock.acquire("task-1", "/test/path", agent_id="agent-1")
        assert result.acquired is True

    def test_acquire_conflict_different_task(self, tmp_path):
        lock = WorkingPathLock(db_path=str(tmp_path / "test.db"))
        lock.acquire("task-1", "/test/path", agent_id="agent-1")
        # Different task on same path should fail
        result = lock.acquire("task-2", "/test/path", agent_id="agent-2")
        assert result.acquired is False

    def test_release_nonexistent_is_safe(self, tmp_path):
        lock = WorkingPathLock(db_path=str(tmp_path / "test.db"))
        released = lock.release("nonexistent-task")
        assert released is False
