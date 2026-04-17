"""Tests for R74 ChatDev BlackboardMemory."""
from src.governance.context.blackboard import (
    BlackboardMemory,
    create_reflexion_blackboard,
)


def test_write_denied_without_permission():
    bb = BlackboardMemory("test")
    bb.grant("reader", read=True, write=False)
    assert bb.write("reader", "hello") is False


def test_write_and_read_respects_permissions():
    bb = BlackboardMemory("test")
    bb.grant("writer", read=False, write=True)
    bb.grant("reader", read=True, write=False)
    assert bb.write("writer", "lesson one") is True
    entries = bb.read("reader", top_k=5)
    assert len(entries) == 1
    assert entries[0].content == "lesson one"
    assert bb.read("writer", top_k=5) == []  # writer lacks read


def test_dedup_suppresses_duplicate_content():
    bb = BlackboardMemory("test", dedup=True)
    bb.grant("w", read=True, write=True)
    assert bb.write("w", "same") is True
    assert bb.write("w", "same") is False
    assert len(bb.read("w")) == 1


def test_reflexion_factory_sets_expected_roles():
    bb = create_reflexion_blackboard()
    stats = bb.get_stats()
    assert set(stats["roles"].keys()) == {
        "actor", "evaluator", "reflection_writer", "synthesizer",
    }
    assert stats["roles"]["reflection_writer"] == {"read": False, "write": True}
