"""Tests for task tier classification and budget control."""
import pytest
from src.governance.context.tiers import TaskTier, TIERS, classify_task_tier

class TestTaskTier:
    def test_tiers_exist(self):
        assert "light" in TIERS
        assert "standard" in TIERS
        assert "heavy" in TIERS

    def test_tier_budgets_ascending(self):
        assert TIERS["light"].context_budget < TIERS["standard"].context_budget
        assert TIERS["standard"].context_budget < TIERS["heavy"].context_budget

    def test_classify_exam_as_heavy(self):
        tier = classify_task_tier("Clawvard practice: understanding", {})
        assert tier.name == "heavy"

    def test_classify_patrol_as_light(self):
        tier = classify_task_tier("check container status", {})
        assert tier.name == "light"

    def test_classify_default_as_standard(self):
        tier = classify_task_tier("fix import error in collector.py", {})
        assert tier.name == "standard"

    def test_spec_tier_override(self):
        tier = classify_task_tier("simple task", {"tier": "heavy"})
        assert tier.name == "heavy"

    def test_classify_analyze_as_heavy(self):
        tier = classify_task_tier("analyze codebase architecture", {})
        assert tier.name == "heavy"

    def test_classify_status_as_light(self):
        tier = classify_task_tier("status check for docker containers", {})
        assert tier.name == "light"
