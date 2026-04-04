"""Tests for evolution_log table and EvolutionMixin."""
import pytest
from src.storage.events_db import EventsDB


@pytest.fixture
def db(tmp_path):
    return EventsDB(str(tmp_path / "test.db"))


def test_log_evolution_and_retrieve(db):
    row_id = db.log_evolution(
        signal_id="S1",
        action_type="collector_heal",
        risk_level="AUTO",
        status="success",
        detail={"collector": "git", "fix": "restart"},
        score_before=None,
        score_after=None,
    )
    assert row_id > 0

    history = db.get_evolution_history(limit=10)
    assert len(history) == 1
    row = history[0]
    assert row["signal_id"] == "S1"
    assert row["action_type"] == "collector_heal"
    assert row["risk_level"] == "AUTO"
    assert row["status"] == "success"


def test_log_evolution_with_scores(db):
    row_id = db.log_evolution(
        signal_id="S4",
        action_type="prompt_tune",
        risk_level="REVIEW",
        status="kept",
        detail={"department": "engineering", "diff_lines": 12},
        score_before=0.82,
        score_after=0.87,
    )
    history = db.get_evolution_history(limit=1)
    assert history[0]["score_before"] == 0.82
    assert history[0]["score_after"] == 0.87


def test_get_evolution_history_filter_by_action(db):
    db.log_evolution("S1", "collector_heal", "AUTO", "success", {})
    db.log_evolution("S4", "prompt_tune", "REVIEW", "kept", {})
    db.log_evolution("S1", "collector_heal", "AUTO", "failed", {})

    heals = db.get_evolution_history(action_type="collector_heal")
    assert len(heals) == 2
    assert all(r["action_type"] == "collector_heal" for r in heals)
