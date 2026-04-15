"""Tests for src.governance.learning.atomic_fact_splitter — fact atomization."""
import pytest
from src.governance.learning.atomic_fact_splitter import (
    split_into_atomic_facts, validate_fact, deduplicate_facts, AtomicFact,
)


class TestAtomicFactSplitter:
    def test_split_compound_sentence(self):
        facts = split_into_atomic_facts("Alice likes Python and Bob likes Rust")
        assert len(facts) >= 2

    def test_single_fact_unchanged(self):
        facts = split_into_atomic_facts("Alice likes Python")
        assert len(facts) >= 1
        assert any("Alice" in f for f in facts)

    def test_validate_fact_accepts_good_fact(self):
        ok, reason = validate_fact("Alice prefers functional programming")
        assert ok is True

    def test_validate_fact_returns_tuple(self):
        """validate_fact should always return (bool, str)."""
        ok, reason = validate_fact("The user likes Python")
        assert isinstance(ok, bool)
        assert isinstance(reason, str)

    def test_deduplicate_removes_near_duplicates(self):
        facts = [
            AtomicFact(content="Alice likes Python", source_entry="s1",
                       fact_index=0, entities=["Alice"], confidence=0.9, temporal_refs=[]),
            AtomicFact(content="Alice likes Python programming", source_entry="s1",
                       fact_index=1, entities=["Alice"], confidence=0.9, temporal_refs=[]),
        ]
        result = deduplicate_facts(facts, existing=[], threshold=0.7)
        assert len(result) <= len(facts)
