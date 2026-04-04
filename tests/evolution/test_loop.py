"""Tests for EvolutionEngine — the core detect->classify->act->evaluate->learn loop."""
import pytest
from unittest.mock import MagicMock, patch
from src.evolution.loop import EvolutionEngine, CycleResult
from src.evolution.risk import RiskLevel, ActionType
from src.evolution.actions import ActionStatus
from src.proactive.signals import Signal


def _make_signal(sid="S1", tier="A", severity="high"):
    return Signal(id=sid, tier=tier, title="test", severity=severity, data={"collector": "git"})


@pytest.fixture
def engine():
    db = MagicMock()
    db.log_evolution = MagicMock(return_value=1)
    db.get_evolution_history = MagicMock(return_value=[])
    channel_registry = MagicMock()
    return EvolutionEngine(db=db, channel_registry=channel_registry)


class TestRunCycle:
    def test_no_signals_returns_empty(self, engine):
        with patch.object(engine._detector, "detect_all", return_value=[]):
            results = engine.run_cycle()
        assert results == []

    def test_actionable_signal_gets_processed(self, engine):
        sig = _make_signal("S1")
        with patch.object(engine._detector, "detect_all", return_value=[sig]), \
             patch("src.jobs.collectors.run_collectors"):
            results = engine.run_cycle()
        assert len(results) == 1
        assert results[0].signal_id == "S1"
        assert results[0].action_type == ActionType.COLLECTOR_HEAL
        assert results[0].executed

    def test_informational_signal_skipped(self, engine):
        sig = _make_signal("S6", tier="C", severity="low")
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            results = engine.run_cycle()
        assert results == []

    def test_block_signal_not_executed(self, engine):
        sig = _make_signal("S2", tier="A", severity="high")
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            results = engine.run_cycle()
        assert len(results) == 1
        assert results[0].risk == RiskLevel.BLOCK
        assert not results[0].executed

    def test_review_signal_executed_and_notified(self, engine):
        sig = _make_signal("S4", tier="A", severity="high")
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            results = engine.run_cycle()
        assert len(results) == 1
        assert results[0].risk == RiskLevel.REVIEW
        assert results[0].executed
        engine._channel_registry.broadcast.assert_called()

    def test_failed_action_logged(self, engine):
        sig = _make_signal("S1")
        with patch.object(engine._detector, "detect_all", return_value=[sig]), \
             patch("src.jobs.collectors.run_collectors", side_effect=Exception("broken")):
            results = engine.run_cycle()
        assert len(results) == 1
        engine._db.log_evolution.assert_called()

    def test_dry_run_does_not_execute(self, engine):
        engine._dry_run = True
        sig = _make_signal("S1")
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            results = engine.run_cycle()
        assert len(results) == 1
        assert not results[0].executed
        assert results[0].detail.get("reason") == "dry_run"


class TestCycleResult:
    def test_score_delta(self):
        r = CycleResult(
            signal_id="S4", action_type=ActionType.PROMPT_TUNE,
            risk=RiskLevel.REVIEW, executed=True,
            action_status=ActionStatus.SUCCESS,
            score_before=0.82, score_after=0.87,
        )
        assert r.score_delta == pytest.approx(0.05)

    def test_score_delta_none_when_no_scores(self):
        r = CycleResult(
            signal_id="S1", action_type=ActionType.COLLECTOR_HEAL,
            risk=RiskLevel.AUTO, executed=True,
            action_status=ActionStatus.SUCCESS,
        )
        assert r.score_delta is None
