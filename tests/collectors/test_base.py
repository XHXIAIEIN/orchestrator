import pytest
from src.collectors.base import ICollector, CollectorMeta
from src.storage.events_db import EventsDB
from unittest.mock import MagicMock


class DummyCollector(ICollector):
    @classmethod
    def metadata(cls) -> CollectorMeta:
        return CollectorMeta(
            name="dummy", display_name="Dummy", category="core",
            env_vars=["DUMMY_PATH"], requires=["dummy_bin"],
            event_sources=["dummy"], default_enabled=True,
        )

    def collect(self) -> int:
        return 42


class TestICollector:
    def test_metadata(self):
        meta = DummyCollector.metadata()
        assert meta.name == "dummy"
        assert meta.category == "core"
        assert meta.default_enabled is True

    def test_collect(self):
        db = MagicMock(spec=EventsDB)
        c = DummyCollector(db=db)
        assert c.collect() == 42

    def test_collect_with_metrics(self):
        db = MagicMock(spec=EventsDB)
        c = DummyCollector(db=db)
        result = c.collect_with_metrics()
        assert result == 42
        assert db.write_log.called

    def test_preflight_default(self):
        db = MagicMock(spec=EventsDB)
        c = DummyCollector(db=db)
        ok, reason = c.preflight()
        assert ok is True
