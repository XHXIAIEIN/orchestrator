"""Tests for ProactiveEngine scan loop."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.proactive.engine import ProactiveEngine
from src.proactive.signals import Signal


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.log_proactive = MagicMock(return_value=1)
    db._connect = MagicMock()
    return db


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    reg.broadcast = MagicMock()
    return reg


@pytest.fixture
def engine(mock_db, mock_registry):
    return ProactiveEngine(db=mock_db, channel_registry=mock_registry, llm_router=None)


def _make_signal(sid="S1", tier="A", severity="critical"):
    return Signal(id=sid, tier=tier, title="test", severity=severity, data={"k": "v"})


class TestRunScan:
    def test_scan_with_no_signals(self, engine):
        with patch.object(engine._detector, "detect_all", return_value=[]):
            sent, throttled = engine.run_scan()
        assert sent == 0
        assert throttled == 0

    def test_scan_sends_passing_signal(self, engine, mock_db, mock_registry):
        sig = _make_signal()
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            sent, throttled = engine.run_scan()
        assert sent == 1
        assert throttled == 0
        mock_registry.broadcast.assert_called_once()
        mock_db.log_proactive.assert_called_once()
        assert mock_db.log_proactive.call_args.kwargs["action"] == "sent"

    def test_scan_throttles_blocked_signal(self, engine, mock_db, mock_registry):
        sig = _make_signal(sid="S3", tier="C", severity="low")
        with (
            patch.object(engine._detector, "detect_all", return_value=[sig]),
            patch.object(engine._throttle, "should_send", return_value=False),
        ):
            sent, throttled = engine.run_scan()
        assert sent == 0
        assert throttled == 1
        mock_registry.broadcast.assert_not_called()
        assert mock_db.log_proactive.call_args.kwargs["action"] == "throttled"

    def test_scan_records_sent_in_throttle(self, engine):
        sig = _make_signal()
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            engine.run_scan()
        assert any(sid == "S1" for sid, _ in engine._throttle._sent_log)

    def test_scan_handles_broadcast_failure(self, engine, mock_registry, mock_db):
        sig = _make_signal()
        mock_registry.broadcast.side_effect = Exception("network error")
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            sent, throttled = engine.run_scan()
        assert sent == 0
        assert mock_db.log_proactive.call_args.kwargs["action"] == "send_failed"

    def test_scan_drains_queued_signals(self, engine, mock_registry):
        sig = _make_signal(sid="S5", tier="B", severity="medium")
        engine._throttle._queued.append(sig)
        with patch.object(engine._detector, "detect_all", return_value=[]):
            with patch.object(engine._throttle, "should_send", return_value=True):
                sent, _ = engine.run_scan()
        assert sent == 1


class TestMapPriority:
    def test_tier_a_maps_to_critical(self, engine):
        assert engine._map_priority("A", "critical") == "CRITICAL"

    def test_tier_b_maps_to_high(self, engine):
        assert engine._map_priority("B", "high") == "HIGH"

    def test_tier_c_maps_to_normal(self, engine):
        assert engine._map_priority("C", "medium") == "NORMAL"

    def test_tier_d_maps_to_low(self, engine):
        assert engine._map_priority("D", "low") == "LOW"
