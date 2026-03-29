"""Tests for Hotness Scorer."""
import pytest
from datetime import datetime, timezone, timedelta
from src.storage.hotness import score_hotness, classify_tier, HotnessScorer, HotnessResult


def test_score_zero_hits():
    assert score_hotness(0, None) == 0.0


def test_score_recent_high_hits():
    """Recent + high hits = high score."""
    now = datetime.now(timezone.utc).isoformat()
    score = score_hotness(10, now)
    assert score >= 9.0  # 10 * ~1.0


def test_score_old_high_hits():
    """Old + high hits = decayed score."""
    old = (datetime.now(timezone.utc) - timedelta(days=25)).isoformat()
    score = score_hotness(10, old)
    assert score < 3.0  # significantly decayed


def test_score_no_last_hit():
    """No last_hit_at uses default recency 0.5."""
    score = score_hotness(10, None)
    assert score == 5.0


def test_classify_hot():
    assert classify_tier(5.0) == "hot"
    assert classify_tier(10.0) == "hot"


def test_classify_warm():
    assert classify_tier(1.0) == "warm"
    assert classify_tier(4.9) == "warm"


def test_classify_cold():
    assert classify_tier(0.0) == "cold"
    assert classify_tier(0.9) == "cold"
