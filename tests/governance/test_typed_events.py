"""Tests for typed governance events."""
from src.governance.events.types import (
    GovernanceEvent, AgentTurn, AgentResult, StuckDetected,
    DoomLoopDetected, EventSource,
)


def test_agent_turn_to_dict():
    evt = AgentTurn(
        task_id=1, source=EventSource.AGENT, turn=3,
        tools=["Read", "Edit"], text_preview="hello",
    )
    d = evt.to_dict()
    assert d["event_class"] == "AgentTurn"
    assert d["turn"] == 3
    assert d["source"] == "agent"
    assert d["tools"] == ["Read", "Edit"]


def test_agent_turn_from_dict():
    d = {"task_id": 1, "source": "agent", "turn": 5, "tools": ["Grep"]}
    evt = AgentTurn.from_dict(d)
    assert evt.task_id == 1
    assert evt.source == EventSource.AGENT
    assert evt.turn == 5


def test_agent_result_roundtrip():
    original = AgentResult(
        task_id=42, source=EventSource.AGENT,
        status="done", num_turns=10, cost_usd=0.05,
    )
    d = original.to_dict()
    restored = AgentResult.from_dict(d)
    assert restored.task_id == 42
    assert restored.status == "done"
    assert restored.cost_usd == 0.05


def test_doom_loop_detected():
    evt = DoomLoopDetected(
        task_id=7, source=EventSource.GOVERNOR,
        reason="same file edited 5 times", turn=12,
        details={"type": "repeated_edit"},
    )
    d = evt.to_dict()
    assert d["event_class"] == "DoomLoopDetected"
    assert d["reason"] == "same file edited 5 times"


def test_from_dict_ignores_unknown_fields():
    d = {"task_id": 1, "source": "system", "unknown_field": "ignored", "turn": 3}
    evt = AgentTurn.from_dict(d)
    assert evt.task_id == 1
    assert evt.turn == 3
    assert not hasattr(evt, "unknown_field")


def test_stuck_detected():
    evt = StuckDetected(
        task_id=5, source=EventSource.GOVERNOR,
        pattern="empty_response_loop", turn=9,
    )
    d = evt.to_dict()
    assert d["pattern"] == "empty_response_loop"
