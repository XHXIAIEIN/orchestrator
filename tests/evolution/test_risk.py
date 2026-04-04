"""Tests for RiskClassifier — signal → risk level mapping."""
import pytest
from src.proactive.signals import Signal
from src.evolution.risk import RiskLevel, RiskClassifier, ActionType


def _signal(sid: str, tier: str = "B", severity: str = "medium") -> Signal:
    return Signal(id=sid, tier=tier, title="test", severity=severity, data={})


class TestRiskClassifier:
    def test_collector_fail_is_auto(self):
        sig = _signal("S1", tier="A", severity="high")
        result = RiskClassifier.classify(sig)
        assert result.risk == RiskLevel.AUTO
        assert result.action_type == ActionType.COLLECTOR_HEAL

    def test_governor_fail_maps_to_prompt_tune(self):
        sig = _signal("S4", tier="A", severity="high")
        result = RiskClassifier.classify(sig)
        assert result.action_type == ActionType.PROMPT_TUNE
        assert result.risk == RiskLevel.REVIEW

    def test_db_size_maps_to_memory_hygiene(self):
        sig = _signal("S3", tier="B", severity="medium")
        result = RiskClassifier.classify(sig)
        assert result.action_type == ActionType.MEMORY_HYGIENE
        assert result.risk == RiskLevel.AUTO

    def test_repeated_pattern_maps_to_param_tune(self):
        sig = _signal("S7", tier="B", severity="medium")
        result = RiskClassifier.classify(sig)
        assert result.action_type == ActionType.PARAM_TUNE
        assert result.risk == RiskLevel.REVIEW

    def test_unknown_signal_returns_none(self):
        sig = _signal("S99", tier="D", severity="low")
        result = RiskClassifier.classify(sig)
        assert result is None

    def test_container_health_is_block(self):
        sig = _signal("S2", tier="A", severity="high")
        result = RiskClassifier.classify(sig)
        assert result.risk == RiskLevel.BLOCK

    def test_dependency_vuln_is_block(self):
        sig = _signal("S12", tier="D", severity="high")
        result = RiskClassifier.classify(sig)
        assert result.risk == RiskLevel.BLOCK
