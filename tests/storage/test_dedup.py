"""Tests for Learning Dedup Pipeline."""
from src.storage.dedup import text_similarity, check_duplicate, DedupDecision


def test_text_similarity_identical():
    assert text_similarity("hello world", "hello world") == 1.0


def test_text_similarity_different():
    assert text_similarity("hello world", "goodbye moon") < 0.5


def test_text_similarity_similar():
    sim = text_similarity(
        "Always use pytest for testing",
        "Always use pytest when testing",
    )
    assert sim > 0.8


def test_text_similarity_empty():
    assert text_similarity("", "hello") == 0.0
    assert text_similarity("hello", "") == 0.0


def test_check_duplicate_no_existing():
    decision = check_duplicate("new rule", "general", [])
    assert decision.action == "create"


def test_check_duplicate_exact_match():
    existing = [{"id": 1, "rule": "use pytest for tests", "area": "general",
                 "pattern_key": "test:pytest", "recurrence": 3}]
    decision = check_duplicate("use pytest for tests", "general", existing)
    assert decision.action == "skip"
    assert decision.existing_id == 1
    assert decision.similarity >= 0.95


def test_check_duplicate_similar():
    existing = [{"id": 1, "rule": "Always run pytest before committing",
                 "area": "general", "pattern_key": "test:pre-commit", "recurrence": 2}]
    decision = check_duplicate("Always run pytest before you commit", "general", existing)
    assert decision.action in ("merge", "skip")
    assert decision.existing_id == 1


def test_check_duplicate_different_area_ignored():
    existing = [{"id": 1, "rule": "use pytest for tests", "area": "security",
                 "pattern_key": "test:pytest", "recurrence": 3}]
    decision = check_duplicate("use pytest for tests", "general", existing)
    assert decision.action == "create"  # different area, not compared


def test_check_duplicate_no_match():
    existing = [{"id": 1, "rule": "deploy with docker compose",
                 "area": "general", "pattern_key": "deploy:docker", "recurrence": 1}]
    decision = check_duplicate("always validate user input", "general", existing)
    assert decision.action == "create"
    assert decision.similarity < 0.75
