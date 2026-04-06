import pytest
from src.governance.condenser.context_condenser import compute_compaction_threshold


def test_model_specific_threshold():
    threshold = compute_compaction_threshold(model="claude-sonnet-4-6")
    assert threshold == 170_000  # 200K * 0.85


def test_custom_session_threshold_overrides():
    threshold = compute_compaction_threshold(model="claude-sonnet-4-6", custom_threshold=50_000)
    assert threshold == 50_000


def test_unknown_model_uses_default():
    threshold = compute_compaction_threshold(model="unknown-model-xyz")
    assert threshold == int(128_000 * 0.85)


def test_custom_ratio():
    threshold = compute_compaction_threshold(model="claude-sonnet-4-6", ratio=0.70)
    assert threshold == 140_000
