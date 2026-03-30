"""Tests for division discovery in registry."""
import pytest
from src.governance.registry import _build_department, DepartmentEntry


def _make_manifest_with_divisions():
    return {
        "key": "engineering",
        "name_zh": "工部",
        "description": "Code engineering",
        "prompt_prefix": "You are Engineering.",
        "skill_path": "departments/engineering/SKILL.md",
        "divisions": {
            "implement": {"name_zh": "实现", "description": "Core code implementation", "exam_dimension": "execution"},
            "scaffold": {"name_zh": "搭建", "description": "Project scaffolding, CI/CD"},
            "integrate": {"name_zh": "集成", "description": "Dependency management"},
            "orchestrate": {"name_zh": "编排", "description": "Pipeline, data flow"},
        },
    }


class TestDivisionDiscovery:
    def test_department_entry_has_divisions(self):
        raw = _make_manifest_with_divisions()
        dept = _build_department(raw)
        assert hasattr(dept, "divisions")
        assert len(dept.divisions) == 4
        assert "implement" in dept.divisions

    def test_division_has_exam_dimension(self):
        raw = _make_manifest_with_divisions()
        dept = _build_department(raw)
        assert dept.divisions["implement"]["exam_dimension"] == "execution"
        assert dept.divisions["scaffold"].get("exam_dimension") is None

    def test_no_divisions_backward_compatible(self):
        raw = {"key": "security", "name_zh": "兵部", "description": "Security"}
        dept = _build_department(raw)
        assert dept.divisions == {}
