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

    def test_log_writes_to_db(self):
        """log() 应该同时写 DB 和 stderr。"""
        db = MagicMock(spec=EventsDB)
        c = DummyCollector(db=db)
        c.log("test message", "WARNING")
        db.write_log.assert_called_once()
        call_args = db.write_log.call_args
        assert "test message" in call_args[0][0]
        assert call_args[0][1] == "WARNING"

    def test_log_survives_db_failure(self):
        """DB 写入失败时 log() 不应抛异常。"""
        db = MagicMock(spec=EventsDB)
        db.write_log.side_effect = Exception("DB is dead")
        c = DummyCollector(db=db)
        # 不应抛异常 — stderr 兜底
        c.log("this should not crash")

    def test_trace_writes_step(self):
        """trace() 应写入 step 字段。"""
        db = MagicMock(spec=EventsDB)
        c = DummyCollector(db=db)
        c._run_id = "test123"
        c.trace("scan", "found 3 repos")
        call_args = db.write_log.call_args
        assert call_args[1]["step"] == "scan"
        assert call_args[1]["run_id"] == "test123"

    def test_collect_with_metrics_sets_run_id(self):
        """collect_with_metrics() 应生成 run_id 并在完成后清除。"""
        db = MagicMock(spec=EventsDB)
        c = DummyCollector(db=db)
        assert c._run_id is None
        c.collect_with_metrics()
        # 完成后 run_id 应被清除
        assert c._run_id is None
        # 但 log 调用时应该有 run_id
        calls = db.write_log.call_args_list
        assert len(calls) >= 2  # start + done
        assert calls[0][1]["run_id"] is not None

    def test_preflight_default(self):
        db = MagicMock(spec=EventsDB)
        c = DummyCollector(db=db)
        ok, reason = c.preflight()
        assert ok is True
