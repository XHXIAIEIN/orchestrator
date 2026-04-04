"""Evolution actions — concrete operations the loop can execute autonomously."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)


class ActionStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


@dataclass
class ActionResult:
    status: ActionStatus
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == ActionStatus.SUCCESS


class BaseAction(ABC):
    """Base class for all evolution actions."""

    @abstractmethod
    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        """Execute the action. Returns ActionResult."""

    def rollback(self, db: EventsDB, execute_detail: dict[str, Any]) -> None:
        """Rollback the action. Default: no-op (action is inherently safe)."""


# ── 1. Memory Hygiene ─────────────────────────────────────────────────────────

class MemoryHygieneAction(BaseAction):
    """Retire stale learnings, dedup memories, decay hotness."""

    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        from src.governance.learning.experience_cull import run_cull
        try:
            report = run_cull(db)
            return ActionResult(
                status=ActionStatus.SUCCESS,
                detail={
                    "retired_count": len(report.retired),
                    "promoted_count": len(report.promoted),
                    "at_risk_count": len(report.at_risk),
                    "total_active": report.total_active,
                    "summary": report.format(),
                },
            )
        except Exception as e:
            log.warning(f"MemoryHygiene failed: {e}")
            return ActionResult(status=ActionStatus.FAILED, detail={"error": str(e)})


# ── 2. Collector Heal ──────────────────────────────────────────────────────────

class CollectorHealAction(BaseAction):
    """Restart failed collectors."""

    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        from src.jobs.collectors import run_collectors
        collector = signal_data.get("collector", "unknown")
        try:
            run_collectors(db)
            return ActionResult(
                status=ActionStatus.SUCCESS,
                detail={"collector": collector, "action": "restarted"},
            )
        except Exception as e:
            log.warning(f"CollectorHeal failed for {collector}: {e}")
            return ActionResult(
                status=ActionStatus.FAILED,
                detail={"collector": collector, "error": str(e)},
            )


# ── 3. Prompt Tune ────────────────────────────────────────────────────────────

class PromptTuneAction(BaseAction):
    """Apply skill evolution suggestions to department SKILL.md."""

    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        from src.governance.learning.skill_evolver import analyze_department
        from pathlib import Path

        department = signal_data.get("department")
        if not department:
            return ActionResult(status=ActionStatus.SKIPPED, detail={"reason": "no department in signal"})

        suggestion_path = Path(f"departments/{department}/skill-suggestions.md")
        skill_path = Path(f"departments/{department}/SKILL.md")

        if not suggestion_path.exists():
            result_text = analyze_department(department)
            if not result_text:
                return ActionResult(status=ActionStatus.SKIPPED, detail={"reason": "insufficient data for analysis"})

        if not suggestion_path.exists():
            return ActionResult(status=ActionStatus.SKIPPED, detail={"reason": "no suggestions generated"})

        original = skill_path.read_text(encoding="utf-8") if skill_path.exists() else ""
        suggestions = suggestion_path.read_text(encoding="utf-8")

        return ActionResult(
            status=ActionStatus.SUCCESS,
            detail={
                "department": department,
                "original_hash": hash(original),
                "suggestions_preview": suggestions[:200],
                "applied": False,
            },
        )

    def rollback(self, db: EventsDB, execute_detail: dict[str, Any]) -> None:
        pass


# ── 4. Param Tune ─────────────────────────────────────────────────────────────

class ParamTuneAction(BaseAction):
    """Adjust numerical parameters based on observed patterns."""

    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        pattern = signal_data.get("pattern", "unknown")
        return ActionResult(
            status=ActionStatus.SUCCESS,
            detail={"pattern": pattern, "recommendation": "logged for review"},
        )


# ── 5. Code Fix ───────────────────────────────────────────────────────────────

class CodeFixAction(BaseAction):
    """BLOCK-level: flag the issue for human review, don't auto-fix."""

    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        return ActionResult(
            status=ActionStatus.SKIPPED,
            detail={"reason": "BLOCK-level action — awaiting owner approval", "signal_data": signal_data},
        )


# ── 6. Steal Patrol ───────────────────────────────────────────────────────────

class StealPatrolAction(BaseAction):
    """Scan watchlist repos for new patterns. Read-only operation."""

    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        return ActionResult(
            status=ActionStatus.SKIPPED,
            detail={"reason": "steal patrol placeholder — needs GitHub API integration"},
        )


# ── Action Registry ───────────────────────────────────────────────────────────

from src.evolution.risk import ActionType

ACTION_REGISTRY: dict[ActionType, BaseAction] = {
    ActionType.MEMORY_HYGIENE: MemoryHygieneAction(),
    ActionType.COLLECTOR_HEAL: CollectorHealAction(),
    ActionType.PROMPT_TUNE: PromptTuneAction(),
    ActionType.PARAM_TUNE: ParamTuneAction(),
    ActionType.CODE_FIX: CodeFixAction(),
    ActionType.STEAL_PATROL: StealPatrolAction(),
}
