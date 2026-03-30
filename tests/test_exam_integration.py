"""Integration smoke test — full Coach pipeline with mock agent."""
import pytest
from pathlib import Path

from src.exam.coach import ExamCoach
from src.exam.runner import ExamRunner
from src.exam.dimension_map import load_dimension_map, DIMENSION_MAP, _DEFAULT_YAML


def mock_answer_fn(prompt: str, question: dict) -> str:
    """Mock agent that returns dimension-appropriate answers."""
    dim = question.get("dimension", "")
    qid = question.get("id", "")
    prompt_text = question.get("prompt", "")

    # For multiple choice, pick A
    if "A)" in prompt_text and "B)" in prompt_text:
        return "A"

    # For open-ended, return a reasonably long answer
    return (
        f"Answer for {qid} ({dim}):\n\n"
        f"This is a comprehensive response covering the key points. "
        f"The analysis considers multiple perspectives and provides concrete recommendations. "
        f"{'x' * 800}\n\n"
        f"| Requirement | Coverage |\n|---|---|\n| 1 | Covered above |"
    )


class TestExamIntegration:
    def test_coach_builds_prompt_for_all_dimensions(self):
        """Verify Coach can build prompts for all 8 dimensions."""
        dim_map = load_dimension_map(_DEFAULT_YAML) if _DEFAULT_YAML else DIMENSION_MAP
        coach = ExamCoach.__new__(ExamCoach)
        coach._dim_map = dim_map
        coach._all_learnings = {}
        coach._global_learnings = []

        for dim in dim_map:
            question = {"id": f"test-{dim}", "dimension": dim, "prompt": f"Test question for {dim}"}
            prompt = coach.build_prompt(question)
            assert len(prompt) > 50, f"Prompt for {dim} too short"
            assert f"test-{dim}" in prompt

    def test_coach_process_batch(self):
        """Verify full batch processing pipeline."""
        coach = ExamCoach(runner=None)
        batch = [
            {"id": "ref-43", "dimension": "reflection", "prompt": "A) Over-engineered\nB) Future-proof\nC) Add GraphQL\nD) Remove Kafka"},
            {"id": "ref-32", "dimension": "reflection", "prompt": "Evaluate 8 best practices..."},
        ]
        answers = coach.process_batch(batch, mock_answer_fn)
        assert len(answers) == 2
        assert answers[0]["questionId"] == "ref-43"
        assert answers[1]["questionId"] == "ref-32"

    def test_all_exam_md_files_load(self):
        """Verify all 8 exam.md files exist and are non-empty."""
        repo_root = Path(__file__).resolve().parent.parent
        dim_map = load_dimension_map(_DEFAULT_YAML) if _DEFAULT_YAML else DIMENSION_MAP
        for dim, route in dim_map.items():
            exam_path = repo_root / "departments" / route.department / route.division / "exam.md"
            assert exam_path.exists(), f"Missing exam.md for {dim}: {exam_path}"
            content = exam_path.read_text(encoding="utf-8")
            assert len(content) > 100, f"exam.md for {dim} too short ({len(content)} chars)"

    def test_all_prompt_md_files_load(self):
        """Verify all 8 exam-dimension divisions have prompt.md."""
        repo_root = Path(__file__).resolve().parent.parent
        dim_map = load_dimension_map(_DEFAULT_YAML) if _DEFAULT_YAML else DIMENSION_MAP
        for dim, route in dim_map.items():
            prompt_path = repo_root / "departments" / route.department / route.division / "prompt.md"
            assert prompt_path.exists(), f"Missing prompt.md for {dim}: {prompt_path}"
