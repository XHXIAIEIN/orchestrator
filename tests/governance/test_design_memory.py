"""Tests for Design Memory."""
import json
from src.governance.design_memory import DesignMemory, VALID_CATEGORIES


def test_record_decision():
    dm = DesignMemory()
    d = dm.record_decision("color", "Use slate-800 for text", reason="Less harsh than black")
    assert d.category == "color"
    assert d.approved is True
    assert d.confidence == 1.0


def test_record_anti_pattern():
    dm = DesignMemory()
    d = dm.record_anti_pattern("Never use pure #000000 black", reason="Too harsh")
    assert d.is_anti_pattern
    assert d.category == "anti-pattern"


def test_get_by_category():
    dm = DesignMemory()
    dm.record_decision("color", "Use blue-600 for links")
    dm.record_decision("layout", "16px card padding")
    dm.record_decision("color", "Slate-100 for backgrounds")
    colors = dm.get_decisions(category="color")
    assert len(colors) == 2


def test_approved_only_filter():
    dm = DesignMemory()
    dm.record_decision("color", "Blue for links", approved=True)
    dm.record_decision("color", "Red for links", approved=False)
    approved = dm.get_decisions(category="color", approved_only=True)
    assert len(approved) == 1


def test_contradict_reduces_confidence():
    dm = DesignMemory()
    d = dm.record_decision("layout", "Use 12px gaps")
    dm.contradict(d.id, "Actually 8px looks better")
    assert d.confidence == 0.7


def test_min_confidence_filter():
    dm = DesignMemory()
    d1 = dm.record_decision("color", "High confidence", confidence=0.9)
    d2 = dm.record_decision("color", "Low confidence", confidence=0.2)
    results = dm.get_decisions(min_confidence=0.5)
    assert len(results) == 1
    assert results[0].decision == "High confidence"


def test_to_prompt_context():
    dm = DesignMemory()
    dm.record_decision("color", "Slate-800 for text")
    dm.record_anti_pattern("No pure black")
    ctx = dm.to_prompt_context(categories=["color", "anti-pattern"])
    assert "Design Memory" in ctx
    assert "Slate-800" in ctx
    assert "pure black" in ctx


def test_to_prompt_context_empty():
    dm = DesignMemory()
    ctx = dm.to_prompt_context()
    assert ctx == ""


def test_save_and_load(tmp_path):
    dm = DesignMemory()
    dm.record_decision("color", "Blue links", reason="Brand color")
    dm.record_decision("layout", "16px padding")

    path = tmp_path / "design_memory.json"
    dm.save_to_file(path)

    dm2 = DesignMemory()
    dm2.load_from_file(path)
    assert len(dm2.get_decisions()) == 2
    assert dm2.get_decisions()[0].decision == "Blue links"


def test_invalid_category_defaults_general():
    dm = DesignMemory()
    d = dm.record_decision("invalid_cat", "Something")
    assert d.category == "general"


def test_get_stats():
    dm = DesignMemory()
    dm.record_decision("color", "Blue", approved=True)
    dm.record_decision("layout", "Grid", approved=True)
    dm.record_anti_pattern("No shadows")
    stats = dm.get_stats()
    assert stats["total"] == 3
    assert stats["approved"] == 2
    assert stats["anti_patterns"] == 1
    assert stats["by_category"]["color"] == 1
