"""RiskClassifier — maps proactive Signals to risk levels and action types."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.proactive.signals import Signal


class RiskLevel(Enum):
    AUTO = "AUTO"        # Execute immediately, log only
    REVIEW = "REVIEW"    # Execute, then notify owner
    BLOCK = "BLOCK"      # Notify owner, wait for approval


class ActionType(Enum):
    MEMORY_HYGIENE = "memory_hygiene"
    COLLECTOR_HEAL = "collector_heal"
    PROMPT_TUNE = "prompt_tune"
    PARAM_TUNE = "param_tune"
    CODE_FIX = "code_fix"
    STEAL_PATROL = "steal_patrol"


@dataclass
class ClassificationResult:
    risk: RiskLevel
    action_type: ActionType
    reason: str


# ── Signal → (ActionType, RiskLevel) routing table ────────────────────────────
_ROUTING: dict[str, tuple[ActionType, RiskLevel, str]] = {
    "S1": (ActionType.COLLECTOR_HEAL, RiskLevel.AUTO,
           "Collector streak failure — restart or fix path"),
    "S2": (ActionType.CODE_FIX, RiskLevel.BLOCK,
           "Container unhealthy — needs investigation"),
    "S3": (ActionType.MEMORY_HYGIENE, RiskLevel.AUTO,
           "DB growing large — run hygiene"),
    "S4": (ActionType.PROMPT_TUNE, RiskLevel.REVIEW,
           "Governor failure streak — check department prompts"),
    "S7": (ActionType.PARAM_TUNE, RiskLevel.REVIEW,
           "Repeated pattern detected — consider parameter adjustment"),
    "S10": (ActionType.MEMORY_HYGIENE, RiskLevel.AUTO,
            "Deferred items overdue — cull or promote"),
    "S12": (ActionType.CODE_FIX, RiskLevel.BLOCK,
            "Dependency vulnerability — needs security review"),
}


class RiskClassifier:
    """Stateless classifier: Signal → ClassificationResult | None."""

    @staticmethod
    def classify(signal: Signal) -> Optional[ClassificationResult]:
        route = _ROUTING.get(signal.id)
        if route is None:
            return None
        action_type, risk, reason = route
        return ClassificationResult(risk=risk, action_type=action_type, reason=reason)
