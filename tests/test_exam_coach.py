"""Tests for ExamCoach."""
import pytest
from src.exam.coach import ExamCoach
from src.exam.dimension_map import DimensionRoute


@pytest.fixture
def mock_route():
    return DimensionRoute(dimension="reflection", department="quality", division="review")


class TestExamCoach:
    def test_route_question_to_correct_division(self, mock_route):
        coach = ExamCoach.__new__(ExamCoach)
        coach._dim_map = {"reflection": mock_route}
        route = coach._route_question({"id": "ref-43", "dimension": "reflection"})
        assert route.department == "quality"
        assert route.division == "review"

    def test_route_unknown_dimension_raises(self):
        coach = ExamCoach.__new__(ExamCoach)
        coach._dim_map = {}
        with pytest.raises(ValueError, match="Unknown dimension"):
            coach._route_question({"id": "xxx-01", "dimension": "unknown_dim"})

    def test_get_learnings_for_dimension(self):
        coach = ExamCoach.__new__(ExamCoach)
        coach._global_learnings = ["global tip"]
        coach._all_learnings = {
            "reflection": ["Don't use 'context-dependent' as a conclusion"],
        }
        result = coach._get_learnings("reflection")
        assert len(result) == 2
        assert "global tip" in result[0]
        assert "context-dependent" in result[1]

    def test_format_answers_for_submission(self):
        coach = ExamCoach.__new__(ExamCoach)
        answers = coach._format_answers([
            {"question_id": "ref-43", "answer": "A"},
            {"question_id": "ref-32", "answer": "Long analysis..."},
        ])
        assert answers == [
            {"questionId": "ref-43", "answer": "A"},
            {"questionId": "ref-32", "answer": "Long analysis..."},
        ]
