"""Tests for manifest-driven department registry."""
from src.governance.registry import (
    DEPARTMENTS, INTENT_ENTRIES, VALID_DEPARTMENTS, DEPT_TAGS,
    get_department, get_tags_for_prompt, get_intents_for_prompt,
)


def test_all_six_departments_discovered():
    assert len(DEPARTMENTS) == 6
    expected = {"engineering", "operations", "protocol", "security", "quality", "personnel"}
    assert VALID_DEPARTMENTS == expected


def test_department_has_required_fields():
    for key, dept in DEPARTMENTS.items():
        assert "name" in dept, f"{key} missing name"
        assert "tools" in dept, f"{key} missing tools"
        assert "prompt_prefix" in dept, f"{key} missing prompt_prefix"
        assert "skill_path" in dept, f"{key} missing skill_path"


def test_all_intents_have_department():
    assert len(INTENT_ENTRIES) == 15
    for name, entry in INTENT_ENTRIES.items():
        assert entry.department in VALID_DEPARTMENTS, f"intent {name} has invalid dept {entry.department}"


def test_tags_not_empty():
    for dept, tags in DEPT_TAGS.items():
        assert len(tags) > 0, f"{dept} has no tags"


def test_get_department_fallback():
    dept = get_department("nonexistent")
    assert dept == DEPARTMENTS.get("engineering", {})


def test_tags_for_prompt_format():
    output = get_tags_for_prompt()
    assert "engineering" in output
    assert "tags:" in output


def test_intents_for_prompt_format():
    output = get_intents_for_prompt()
    assert "code_fix" in output
