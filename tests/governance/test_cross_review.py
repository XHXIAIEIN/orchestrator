"""Tests for Cross-Model Review."""
from src.governance.cross_review import (
    detect_consensus, CrossModelReviewer, ReviewReport,
)


def test_detect_consensus_agree():
    consensus, conf = detect_consensus("yes", "yes", "Both models agree this is safe.")
    assert consensus == "agree"
    assert conf > 0.5


def test_detect_consensus_disagree():
    consensus, conf = detect_consensus("yes", "no", "The models disagree on approach.")
    assert consensus == "disagree"
    assert conf > 0.5


def test_detect_consensus_partial():
    consensus, conf = detect_consensus("maybe", "sort of", "No clear signal either way.")
    assert consensus == "partial"
    assert conf == 0.5


def test_detect_consensus_multiple_signals():
    consensus, conf = detect_consensus(
        "A", "B",
        "Both models agree and are consistent and aligned in their recommendation."
    )
    assert consensus == "agree"
    assert conf > 0.7  # multiple agree signals


def test_review_report_fields():
    """ReviewReport should have all required fields."""
    report = ReviewReport(
        question="test?",
        model_a="model-a",
        model_b="model-b",
        response_a="yes",
        response_b="yes",
        consensus="agree",
        recommendation="do it",
        confidence=0.8,
        latency_ms=100,
    )
    assert report.question == "test?"
    assert report.consensus == "agree"
    assert report.confidence == 0.8


def test_reviewer_init_defaults():
    """CrossModelReviewer should have default models."""
    reviewer = CrossModelReviewer()
    assert reviewer.model_a  # not empty
    assert reviewer.model_b  # not empty
    assert reviewer.model_a != reviewer.model_b  # should be different models
