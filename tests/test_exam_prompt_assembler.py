"""Tests for exam prompt assembly."""
import pytest
from pathlib import Path
from unittest.mock import patch

from src.exam.prompt_assembler import assemble_exam_prompt


@pytest.fixture
def dept_tree(tmp_path):
    eng = tmp_path / "departments" / "engineering"
    eng.mkdir(parents=True)
    (eng / "SKILL.md").write_text("# Engineering\nYou write code.", encoding="utf-8")

    impl = eng / "implement"
    impl.mkdir()
    (impl / "prompt.md").write_text("# Implement Division\nFocus on execution.", encoding="utf-8")
    (impl / "exam.md").write_text("# Execution Exam\n- Breadth-first skeleton\n- Coverage table at end", encoding="utf-8")

    return tmp_path


class TestAssembleExamPrompt:
    def test_includes_all_layers(self, dept_tree):
        with patch("src.exam.prompt_assembler._REPO_ROOT", dept_tree):
            prompt = assemble_exam_prompt(
                department="engineering",
                division="implement",
                question={"id": "exe-18", "prompt": "Build OAuth PKCE", "dimension": "execution"},
                learnings=["Breadth-first output: skeleton first, detail second"],
            )
        assert "You write code" in prompt
        assert "Focus on execution" in prompt
        assert "Breadth-first skeleton" in prompt
        assert "Breadth-first output" in prompt
        assert "Build OAuth PKCE" in prompt

    def test_without_exam_mode(self, dept_tree):
        with patch("src.exam.prompt_assembler._REPO_ROOT", dept_tree):
            prompt = assemble_exam_prompt(
                department="engineering",
                division="implement",
                question={"id": "exe-18", "prompt": "Build OAuth PKCE", "dimension": "execution"},
                learnings=[],
                exam_mode=False,
            )
        assert "Execution Exam" not in prompt
        assert "Build OAuth PKCE" in prompt

    def test_question_appears_last(self, dept_tree):
        with patch("src.exam.prompt_assembler._REPO_ROOT", dept_tree):
            prompt = assemble_exam_prompt(
                department="engineering",
                division="implement",
                question={"id": "exe-18", "prompt": "Build OAuth PKCE", "dimension": "execution"},
                learnings=["test learning"],
            )
        learn_pos = prompt.index("test learning")
        q_pos = prompt.index("Build OAuth PKCE")
        assert q_pos > learn_pos
