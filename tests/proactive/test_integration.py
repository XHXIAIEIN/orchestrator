"""End-to-end smoke test for proactive engine."""
import pytest
from unittest.mock import MagicMock

from src.proactive.engine import ProactiveEngine
from src.storage.events_db import EventsDB


class TestProactiveIntegration:
    @pytest.fixture
    def db(self, tmp_path):
        return EventsDB(str(tmp_path / "test.db"))

    def test_full_scan_cycle_with_real_db(self, db):
        """Engine scans a real (empty) DB without crashing."""
        registry = MagicMock()
        engine = ProactiveEngine(db=db, registry=registry, llm_router=None)
        engine.scan_cycle()
        # May fire S9 (steal branch detection) from real git repo — that's fine
        # Key assertion: no crash

    def test_full_cycle_with_injected_signal(self, db):
        """Inject collector errors, verify S1 fires and gets logged."""
        for i in range(3):
            db.write_log(f"采集失败: timeout {i}", "ERROR", "collector")

        registry = MagicMock()
        engine = ProactiveEngine(db=db, registry=registry, llm_router=None)
        engine.scan_cycle()

        if registry.broadcast.called:
            msg = registry.broadcast.call_args[0][0]
            assert "proactive" in msg.event_type

        logs = db.recent_proactive_logs(limit=10)
        assert len(logs) >= 1

    def test_commands_registered(self):
        """All new commands are in the COMMANDS dict."""
        from src.channels.chat.commands import COMMANDS
        assert "/quiet" in COMMANDS
        assert "/loud" in COMMANDS
        assert "/proactive" in COMMANDS

    def test_schema_has_proactive_table(self, db):
        with db._connect() as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "proactive_log" in tables

    def test_singleton_accessors(self):
        from src.proactive.engine import get_proactive_engine, set_proactive_engine
        old = get_proactive_engine()
        mock_engine = MagicMock()
        set_proactive_engine(mock_engine)
        assert get_proactive_engine() is mock_engine
        set_proactive_engine(old)  # restore
