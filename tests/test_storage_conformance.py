"""Storage Conformance Test Suite (R43 — LangGraph steal).

Contract tests that any StorageProtocol implementation must pass.
Subclass StorageConformanceSuite and set `storage` in setUp to test your backend.
"""

import tempfile
import time
from pathlib import Path

import pytest

from src.governance.checkpoint_recovery import StructuredCheckpoint
from src.storage.storage_protocol import StorageProtocol


class StorageConformanceSuite:
    """Base class for storage conformance tests.

    Subclasses must set `self.storage` to an instance implementing StorageProtocol.
    """

    storage = None  # set in subclass

    # ── Key-Value: put / get / list / delete ──────────────────

    def test_put_get_roundtrip(self):
        self.storage.put("test:key1", {"hello": "world", "n": 42})
        result = self.storage.get("test:key1")
        assert result == {"hello": "world", "n": 42}

    def test_put_overwrite(self):
        self.storage.put("test:overwrite", "v1")
        self.storage.put("test:overwrite", "v2")
        assert self.storage.get("test:overwrite") == "v2"

    def test_get_missing_raises_keyerror(self):
        with pytest.raises(KeyError):
            self.storage.get("nonexistent:key")

    def test_list_prefix_filtering(self):
        self.storage.put("alpha:1", "a")
        self.storage.put("alpha:2", "b")
        self.storage.put("beta:1", "c")

        alpha_keys = self.storage.list("alpha:")
        assert set(alpha_keys) == {"alpha:1", "alpha:2"}

        beta_keys = self.storage.list("beta:")
        assert beta_keys == ["beta:1"]

    def test_list_all(self):
        self.storage.put("listall:a", 1)
        self.storage.put("listall:b", 2)
        keys = self.storage.list("listall:")
        assert len(keys) >= 2

    def test_delete_removes(self):
        self.storage.put("test:delete", "gone")
        self.storage.delete("test:delete")
        with pytest.raises(KeyError):
            self.storage.get("test:delete")

    def test_delete_nonexistent_noop(self):
        # Should not raise
        self.storage.delete("test:never_existed")

    # ── Checkpoints ───────────────────────────────────────────

    def test_put_checkpoint_get_checkpoint(self):
        cp = StructuredCheckpoint(
            task_id="conform-1",
            channel_values={"output": "hello", "status": "done"},
            channel_versions={"output": 1},
            metadata={"dept": "engineering"},
        )
        self.storage.put_checkpoint(cp)
        result = self.storage.get_checkpoint("conform-1")
        assert result is not None
        assert result.task_id == "conform-1"
        assert result.channel_values["output"] == "hello"
        assert result.channel_versions["output"] == 1

    def test_get_checkpoint_missing_returns_none(self):
        result = self.storage.get_checkpoint("nonexistent-task")
        assert result is None

    def test_get_checkpoint_returns_latest(self):
        cp1 = StructuredCheckpoint(
            task_id="latest-test",
            channel_values={"v": 1},
            timestamp="2024-01-01T00:00:00Z",
        )
        cp2 = StructuredCheckpoint(
            task_id="latest-test",
            channel_values={"v": 2},
            timestamp="2024-01-02T00:00:00Z",
        )
        self.storage.put_checkpoint(cp1)
        self.storage.put_checkpoint(cp2)
        result = self.storage.get_checkpoint("latest-test")
        assert result.channel_values["v"] == 2

    def test_list_checkpoints_ordering(self):
        for i in range(3):
            self.storage.put_checkpoint(StructuredCheckpoint(
                task_id="order-test",
                channel_values={"i": i},
                timestamp=f"2024-01-0{i+1}T00:00:00Z",
            ))
        cps = self.storage.list_checkpoints("order-test")
        assert len(cps) == 3
        # Should be desc by timestamp
        assert cps[0].timestamp > cps[-1].timestamp

    def test_list_checkpoints_filter_by_task(self):
        self.storage.put_checkpoint(StructuredCheckpoint(
            task_id="filter-a", channel_values={"x": 1},
        ))
        self.storage.put_checkpoint(StructuredCheckpoint(
            task_id="filter-b", channel_values={"x": 2},
        ))
        a_cps = self.storage.list_checkpoints("filter-a")
        assert all(cp.task_id == "filter-a" for cp in a_cps)

    def test_delete_checkpoints_by_task(self):
        self.storage.put_checkpoint(StructuredCheckpoint(
            task_id="del-test", channel_values={"x": 1},
        ))
        self.storage.put_checkpoint(StructuredCheckpoint(
            task_id="del-test", channel_values={"x": 2},
        ))
        self.storage.delete_checkpoints("del-test")
        assert self.storage.get_checkpoint("del-test") is None
        assert self.storage.list_checkpoints("del-test") == []


# ── Concrete implementation: EventsDB ────────────────────────


class TestEventsDBConformance(StorageConformanceSuite):
    """Run conformance suite against real EventsDB (SQLite)."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path):
        from src.storage.events_db import EventsDB
        db_path = str(tmp_path / "test_conformance.db")
        self.storage = EventsDB(db_path=db_path)
