"""Integration test — full evolution cycle with real DB."""
import pytest
from src.storage.events_db import EventsDB
from src.evolution.loop import EvolutionEngine
from src.evolution.risk import RiskLevel, ActionType
from unittest.mock import MagicMock, patch
from src.proactive.signals import Signal


@pytest.fixture
def db(tmp_path):
    return EventsDB(str(tmp_path / "test.db"))


def test_full_cycle_collector_heal(db):
    """S1 signal → AUTO → CollectorHeal → logged to evolution_log."""
    engine = EvolutionEngine(db=db, channel_registry=MagicMock())

    signal = Signal(
        id="S1", tier="A", title="git collector failing",
        severity="high", data={"collector": "git", "count": 3, "error": "path not found"},
    )

    with patch.object(engine._detector, "detect_all", return_value=[signal]), \
         patch("src.jobs.collectors.run_collectors"):
        results = engine.run_cycle()

    assert len(results) == 1
    r = results[0]
    assert r.signal_id == "S1"
    assert r.action_type == ActionType.COLLECTOR_HEAL
    assert r.risk == RiskLevel.AUTO
    assert r.executed

    # Verify logged to DB
    history = db.get_evolution_history(limit=10)
    assert len(history) >= 1
    assert history[0]["signal_id"] == "S1"
    assert history[0]["action_type"] == "collector_heal"
    assert history[0]["risk_level"] == "AUTO"
    assert history[0]["status"] == "success"


def test_full_cycle_block_not_executed(db):
    """S2 signal → BLOCK → not executed, logged as blocked."""
    engine = EvolutionEngine(db=db, channel_registry=MagicMock())

    signal = Signal(
        id="S2", tier="A", title="container unhealthy",
        severity="high", data={"name": "orchestrator", "status": "exited"},
    )

    with patch.object(engine._detector, "detect_all", return_value=[signal]):
        results = engine.run_cycle()

    assert len(results) == 1
    assert not results[0].executed

    history = db.get_evolution_history(limit=10)
    assert history[0]["status"] == "blocked"


def test_full_cycle_multiple_signals(db):
    """Multiple signals in one cycle — each processed independently."""
    engine = EvolutionEngine(db=db, channel_registry=MagicMock())

    signals = [
        Signal(id="S1", tier="A", title="collector fail", severity="high",
               data={"collector": "git", "count": 3, "error": "x"}),
        Signal(id="S3", tier="B", title="db large", severity="medium",
               data={"size_mb": 55, "delta_mb": 5}),
        Signal(id="S6", tier="C", title="late night", severity="low", data={}),
    ]

    with patch.object(engine._detector, "detect_all", return_value=signals), \
         patch("src.jobs.collectors.run_collectors"), \
         patch("src.governance.learning.experience_cull.run_cull") as mock_cull:
        mock_cull.return_value = MagicMock(
            retired=[], at_risk=[], promoted=[], total_active=40,
            format=MagicMock(return_value="ok"),
        )
        results = engine.run_cycle()

    # S1 → AUTO executed, S3 → AUTO executed, S6 → no routing (skipped)
    assert len(results) == 2
    assert {r.signal_id for r in results} == {"S1", "S3"}

    # Both logged
    history = db.get_evolution_history(limit=10)
    assert len(history) == 2
