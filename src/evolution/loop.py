"""EvolutionEngine — the self-evolution closed loop.

Cycle: Detect signals -> Classify risk -> Execute action -> Evaluate -> Learn.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from src.channels.base import ChannelMessage
from src.evolution.actions import ACTION_REGISTRY, ActionResult, ActionStatus
from src.evolution.risk import ActionType, ClassificationResult, RiskClassifier, RiskLevel
from src.proactive.signals import Signal, SignalDetector
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)


@dataclass
class CycleResult:
    """Outcome of one signal through the evolution pipeline."""
    signal_id: str
    action_type: ActionType
    risk: RiskLevel
    executed: bool
    action_status: ActionStatus = ActionStatus.SKIPPED
    detail: dict[str, Any] = field(default_factory=dict)
    score_before: float | None = None
    score_after: float | None = None

    @property
    def score_delta(self) -> float | None:
        if self.score_before is not None and self.score_after is not None:
            return self.score_after - self.score_before
        return None


class EvolutionEngine:
    """Orchestrates the detect -> classify -> act -> evaluate -> learn loop."""

    def __init__(
        self,
        db: EventsDB,
        channel_registry: Any = None,
        dry_run: bool = False,
    ):
        self._db = db
        self._channel_registry = channel_registry
        self._dry_run = dry_run
        self._detector = SignalDetector(db)

    def run_cycle(self) -> list[CycleResult]:
        """Run one evolution cycle: detect all signals, process actionable ones."""
        signals = self._detector.detect_all()
        if not signals:
            return []

        results: list[CycleResult] = []
        for signal in signals:
            result = self._process_signal(signal)
            if result is not None:
                results.append(result)

        if results:
            log.info(
                f"Evolution cycle: {len(results)} actions "
                f"({sum(1 for r in results if r.executed)} executed, "
                f"{sum(1 for r in results if not r.executed)} blocked/skipped)"
            )
        return results

    def _process_signal(self, signal: Signal) -> Optional[CycleResult]:
        """Process a single signal through classify -> act -> evaluate -> learn."""
        # -- Classify --
        classification = RiskClassifier.classify(signal)
        if classification is None:
            return None

        # -- BLOCK: notify and wait --
        if classification.risk == RiskLevel.BLOCK:
            self._notify_block(signal, classification)
            self._log_to_db(signal, classification, executed=False)
            return CycleResult(
                signal_id=signal.id,
                action_type=classification.action_type,
                risk=classification.risk,
                executed=False,
                action_status=ActionStatus.SKIPPED,
                detail={"reason": "BLOCK — awaiting owner approval"},
            )

        # -- Act --
        action = ACTION_REGISTRY.get(classification.action_type)
        if action is None:
            log.warning(f"No action registered for {classification.action_type}")
            return None

        if self._dry_run:
            return CycleResult(
                signal_id=signal.id,
                action_type=classification.action_type,
                risk=classification.risk,
                executed=False,
                action_status=ActionStatus.SKIPPED,
                detail={"reason": "dry_run"},
            )

        action_result = action.execute(self._db, signal.data)

        # -- Log to DB --
        self._log_to_db(
            signal, classification,
            executed=True,
            status=action_result.status.value,
            detail=action_result.detail,
        )

        # -- Notify (REVIEW level) --
        if classification.risk == RiskLevel.REVIEW:
            self._notify_review(signal, classification, action_result)

        return CycleResult(
            signal_id=signal.id,
            action_type=classification.action_type,
            risk=classification.risk,
            executed=True,
            action_status=action_result.status,
            detail=action_result.detail,
        )

    def _log_to_db(
        self,
        signal: Signal,
        classification: ClassificationResult,
        executed: bool,
        status: str = "blocked",
        detail: dict | None = None,
        score_before: float | None = None,
        score_after: float | None = None,
    ) -> None:
        try:
            self._db.log_evolution(
                signal_id=signal.id,
                action_type=classification.action_type.value,
                risk_level=classification.risk.value,
                status=status if executed else "blocked",
                detail=detail,
                score_before=score_before,
                score_after=score_after,
            )
        except Exception as e:
            log.warning(f"Failed to log evolution: {e}")

    def _notify_review(
        self,
        signal: Signal,
        classification: ClassificationResult,
        action_result: ActionResult,
    ) -> None:
        if not self._channel_registry:
            return
        emoji = "\u2705" if action_result.is_success else "\u274c"
        text = (
            f"[\u8fdb\u5316] {emoji} {classification.action_type.value}\n"
            f"\u89e6\u53d1: {signal.title}\n"
            f"\u7ed3\u679c: {action_result.status.value}"
        )
        try:
            self._channel_registry.broadcast(ChannelMessage(
                text=text,
                event_type="evolution.review",
                priority="NORMAL",
                department="evolution",
            ))
        except Exception as e:
            log.warning(f"Failed to send evolution notification: {e}")

    def _notify_block(
        self,
        signal: Signal,
        classification: ClassificationResult,
    ) -> None:
        if not self._channel_registry:
            return
        text = (
            f"[\u5ba1\u6279] \U0001f512 {classification.action_type.value}\n"
            f"\u89e6\u53d1: {signal.title}\n"
            f"\u539f\u56e0: {classification.reason}\n"
            f"\u9700\u8981\u4f60\u786e\u8ba4\u540e\u624d\u80fd\u6267\u884c"
        )
        try:
            self._channel_registry.broadcast(ChannelMessage(
                text=text,
                event_type="evolution.block",
                priority="CRITICAL",
                department="evolution",
            ))
        except Exception as e:
            log.warning(f"Failed to send evolution block notification: {e}")
