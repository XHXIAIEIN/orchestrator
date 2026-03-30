"""Tests for division prompt loading."""
import pytest
from pathlib import Path
from unittest.mock import patch

from src.governance.context.prompts import load_division


class TestLoadDivision:
    def test_loads_prompt_md(self, tmp_path):
        div_dir = tmp_path / "departments" / "engineering" / "implement"
        div_dir.mkdir(parents=True)
        (div_dir / "prompt.md").write_text("You are the implementation division.", encoding="utf-8")

        with patch("src.governance.context.prompts._REPO_ROOT", tmp_path):
            result = load_division("engineering", "implement")
        assert result == "You are the implementation division."

    def test_returns_none_if_no_prompt(self, tmp_path):
        with patch("src.governance.context.prompts._REPO_ROOT", tmp_path):
            result = load_division("engineering", "implement")
        assert result is None

    def test_loads_exam_md(self, tmp_path):
        div_dir = tmp_path / "departments" / "engineering" / "implement"
        div_dir.mkdir(parents=True)
        (div_dir / "exam.md").write_text("# Execution exam tips", encoding="utf-8")

        with patch("src.governance.context.prompts._REPO_ROOT", tmp_path):
            result = load_division("engineering", "implement", include_exam=True)
        assert "Execution exam tips" in result

    def test_combines_prompt_and_exam(self, tmp_path):
        div_dir = tmp_path / "departments" / "engineering" / "implement"
        div_dir.mkdir(parents=True)
        (div_dir / "prompt.md").write_text("Base prompt.", encoding="utf-8")
        (div_dir / "exam.md").write_text("Exam tips.", encoding="utf-8")

        with patch("src.governance.context.prompts._REPO_ROOT", tmp_path):
            result = load_division("engineering", "implement", include_exam=True)
        assert "Base prompt." in result
        assert "Exam tips." in result
