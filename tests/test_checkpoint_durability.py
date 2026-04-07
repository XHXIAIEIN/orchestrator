"""Tests for Checkpoint Durability modes (R43 — LangGraph steal)."""

import time
from unittest.mock import MagicMock, call

import pytest

from src.governance.checkpoint_recovery import (
    StructuredCheckpoint,
    _exit_buffer,
    flush_exit_buffer,
    save_checkpoint,
)


@pytest.fixture(autouse=True)
def _clear_exit_buffer():
    """Ensure exit buffer is clean before/after each test."""
    _exit_buffer.clear()
    yield
    _exit_buffer.clear()


def _make_cp(task_id: str = "test-1", **overrides) -> StructuredCheckpoint:
    defaults = {
        "task_id": task_id,
        "channel_values": {"output": "hello", "status": "done"},
        "channel_versions": {"output": 1},
        "metadata": {"attempt": 1},
    }
    defaults.update(overrides)
    return StructuredCheckpoint(**defaults)


# ── Sync mode ─────────────────────────────────────────────────


class TestSyncDurability:
    def test_writes_immediately(self):
        db = MagicMock()
        db.put_checkpoint = MagicMock()
        cp = _make_cp()
        save_checkpoint(cp, durability="sync", db=db)
        db.put_checkpoint.assert_called_once_with(cp)

    def test_fallback_to_write_log(self):
        db = MagicMock(spec=[])  # no put_checkpoint
        db.write_log = MagicMock()
        cp = _make_cp()
        save_checkpoint(cp, durability="sync", db=db)
        db.write_log.assert_called_once()

    def test_no_db_logs_warning(self, caplog):
        cp = _make_cp()
        save_checkpoint(cp, durability="sync", db=None)
        assert "no db provided" in caplog.text


# ── Async mode ────────────────────────────────────────────────


class TestAsyncDurability:
    def test_appears_eventually(self):
        db = MagicMock()
        db.put_checkpoint = MagicMock()
        cp = _make_cp()
        save_checkpoint(cp, durability="async", db=db)
        # Wait for thread pool
        time.sleep(0.5)
        db.put_checkpoint.assert_called_once_with(cp)


# ── Exit mode ─────────────────────────────────────────────────


class TestExitDurability:
    def test_not_in_db_mid_task(self):
        db = MagicMock()
        db.put_checkpoint = MagicMock()
        cp = _make_cp()
        save_checkpoint(cp, durability="exit", db=db)
        db.put_checkpoint.assert_not_called()

    def test_appears_after_flush(self):
        db = MagicMock()
        db.put_checkpoint = MagicMock()
        cp1 = _make_cp(task_id="flush-test")
        cp2 = _make_cp(task_id="flush-test", channel_values={"output": "world"})
        save_checkpoint(cp1, durability="exit", db=db)
        save_checkpoint(cp2, durability="exit", db=db)

        db.put_checkpoint.assert_not_called()

        count = flush_exit_buffer("flush-test", db=db)
        assert count == 2
        assert db.put_checkpoint.call_count == 2

    def test_flush_empty_returns_zero(self):
        db = MagicMock()
        assert flush_exit_buffer("no-such-task", db=db) == 0

    def test_flush_no_db_returns_zero(self):
        cp = _make_cp(task_id="no-db")
        save_checkpoint(cp, durability="exit", db=None)
        assert flush_exit_buffer("no-db", db=None) == 0

    def test_flush_clears_buffer(self):
        db = MagicMock()
        db.put_checkpoint = MagicMock()
        save_checkpoint(_make_cp(task_id="clear-test"), durability="exit")
        flush_exit_buffer("clear-test", db=db)
        # Second flush should find nothing
        assert flush_exit_buffer("clear-test", db=db) == 0


# ── StructuredCheckpoint ──────────────────────────────────────


class TestStructuredCheckpoint:
    def test_auto_timestamp(self):
        cp = _make_cp()
        assert cp.timestamp  # should be auto-filled

    def test_explicit_timestamp(self):
        cp = StructuredCheckpoint(
            task_id="t1",
            channel_values={},
            timestamp="2024-01-01T00:00:00Z",
        )
        assert cp.timestamp == "2024-01-01T00:00:00Z"

    def test_defaults(self):
        cp = StructuredCheckpoint(task_id="t1", channel_values={})
        assert cp.channel_versions == {}
        assert cp.pending_writes == []
        assert cp.metadata == {}
