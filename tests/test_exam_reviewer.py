"""Tests for Coach answer reviewer."""
import pytest
from src.exam.reviewer import review_answer, ReviewResult


class TestReviewAnswer:
    def test_short_answer_flagged(self):
        result = review_answer(
            question={"id": "eq-18", "dimension": "eq", "prompt": "Write a Slack message..."},
            answer="Sorry, I can't help with that.",
            dimension="eq",
        )
        assert not result.passed
        assert "too_short" in result.issues

    def test_good_answer_passes(self):
        result = review_answer(
            question={"id": "ref-43", "dimension": "reflection", "prompt": "Over-engineering?"},
            answer="A) This is significantly over-engineered — a simple server-rendered form suffices." + "x" * 400,
            dimension="reflection",
        )
        assert result.passed

    def test_multiple_choice_hedging_flagged(self):
        result = review_answer(
            question={"id": "ret-49", "dimension": "retrieval", "prompt": "XY Problem...\nA) ans1\nB) ans2\nC) ans3\nD) ans4"},
            answer="Either A or B could work depending on the context.",
            dimension="retrieval",
        )
        assert not result.passed
        assert "hedging" in result.issues

    def test_long_answer_missing_coverage_flagged(self):
        long_answer = "x" * 3000
        result = review_answer(
            question={"id": "exe-18", "dimension": "execution", "prompt": "Build OAuth with requirements"},
            answer=long_answer,
            dimension="execution",
        )
        assert "no_coverage_table" in result.issues

    def test_too_long_answer_flagged(self):
        """LRN-011: API truncates silently above ~4000 chars."""
        result = review_answer(
            question={"id": "exe-16", "dimension": "execution", "prompt": "Implement search"},
            answer="x" * 5000,
            dimension="execution",
        )
        assert not result.passed
        assert "too_long" in result.issues

    def test_near_truncation_warned(self):
        """LRN-011: Warn when approaching truncation zone."""
        result = review_answer(
            question={"id": "exe-16", "dimension": "execution", "prompt": "Implement search"},
            answer="x" * 3000,
            dimension="execution",
        )
        assert "near_truncation" in result.issues

    def test_bare_mc_letter_warned(self):
        """LRN-012: Bare letter on first line may be misread by grader."""
        result = review_answer(
            question={"id": "eq-41", "dimension": "eq", "prompt": "Frustration?\nA) ans1\nB) ans2\nC) ans3\nD) ans4"},
            answer="A\n\nA is correct because..." + "x" * 1000,
            dimension="eq",
        )
        assert "bare_mc_letter" in result.issues

    def test_mc_with_paren_no_warning(self):
        """LRN-012: 'A)' format should NOT trigger bare letter warning."""
        result = review_answer(
            question={"id": "eq-41", "dimension": "eq", "prompt": "Frustration?\nA) ans1\nB) ans2\nC) ans3\nD) ans4"},
            answer="A) This is the best response because..." + "x" * 1000,
            dimension="eq",
        )
        assert "bare_mc_letter" not in result.issues
