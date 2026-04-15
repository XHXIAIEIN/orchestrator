"""Tests for src.governance.memory.stale_detector — memory staleness scoring."""
import pytest
from pathlib import Path
from src.governance.memory.stale_detector import score_memory, budget_filter, MemoryEntry


class TestStaleDetector:
    def test_score_returns_positive_float(self):
        entry = MemoryEntry(
            path=Path("test.md"), content="test content",
            frontmatter={"importance": 0.5},
            created_at=1.0, access_count=1, importance=0.5,
        )
        score = score_memory(entry, now=1000.0)
        assert isinstance(score, float)
        assert score > 0

    def test_higher_importance_higher_score(self):
        now = 1000.0
        low = MemoryEntry(
            path=Path("a.md"), content="x",
            frontmatter={"importance": 0.1},
            created_at=1.0, access_count=1, importance=0.1,
        )
        high = MemoryEntry(
            path=Path("b.md"), content="x",
            frontmatter={"importance": 0.9},
            created_at=1.0, access_count=1, importance=0.9,
        )
        assert score_memory(high, now) > score_memory(low, now)

    def test_budget_filter_respects_limit(self):
        # Each entry is 400 chars ≈ 100 tokens (4 chars/token default estimator)
        # 20 entries × 100 tokens = 2000 tokens, budget is 500 → must truncate
        entries = [
            MemoryEntry(
                path=Path(f"{i}.md"), content="x" * 400,
                frontmatter={"importance": 0.5},
                created_at=1.0, access_count=1, importance=0.5,
            )
            for i in range(20)
        ]
        result = budget_filter(entries, max_tokens=500)
        assert len(result) < len(entries)
