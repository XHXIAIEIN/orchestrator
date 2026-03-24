# src/governance/pipeline/phase_rollback.py
"""Phase Rollback — roll back to previous stage instead of aborting.

Stolen from pro-workflow's bidirectional pipeline. When a stage fails,
instead of aborting the whole pipeline or retrying the same stage,
roll back to the last known-good checkpoint and try an alternative path.

Checkpoints are lightweight: just the task state dict + stage outputs
at each stage boundary. Stored in memory during pipeline execution,
optionally persisted to tmp/ for crash recovery.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class StageCheckpoint:
    """Snapshot of pipeline state at a stage boundary."""
    stage_name: str
    stage_index: int
    timestamp: str = ""
    task_state: dict = field(default_factory=dict)   # task spec/status at this point
    outputs: dict = field(default_factory=dict)       # stage outputs (scratchpad paths, etc.)
    success: bool = True

    def to_dict(self) -> dict:
        return {
            "stage_name": self.stage_name,
            "stage_index": self.stage_index,
            "timestamp": self.timestamp,
            "success": self.success,
            "outputs": self.outputs,
        }


@dataclass
class RollbackDecision:
    """Result of rollback analysis."""
    should_rollback: bool
    target_stage: str = ""       # stage to roll back to
    target_index: int = -1
    reason: str = ""
    alternative_strategy: str = ""  # "retry_with_simpler_model" | "skip_and_continue" | "human_escalate"


class PipelineCheckpointer:
    """Manages checkpoints for a single pipeline execution.

    Usage:
        cp = PipelineCheckpointer(task_id=42)
        cp.save("preflight", 0, task_state={...})
        cp.save("scrutiny", 1, task_state={...})
        cp.save("execute", 2, task_state={...}, success=False)

        decision = cp.decide_rollback("execute", error="test_failed")
        # → RollbackDecision(should_rollback=True, target_stage="scrutiny", ...)
    """

    def __init__(self, task_id: int, persist_dir: str = ""):
        self.task_id = task_id
        self.checkpoints: list[StageCheckpoint] = []
        self.persist_dir = persist_dir

    def save(
        self,
        stage_name: str,
        stage_index: int,
        task_state: dict = None,
        outputs: dict = None,
        success: bool = True,
    ) -> StageCheckpoint:
        """Save a checkpoint at a stage boundary."""
        cp = StageCheckpoint(
            stage_name=stage_name,
            stage_index=stage_index,
            timestamp=datetime.now(timezone.utc).isoformat(),
            task_state=task_state or {},
            outputs=outputs or {},
            success=success,
        )
        self.checkpoints.append(cp)

        if self.persist_dir:
            self._persist(cp)

        return cp

    def decide_rollback(self, failed_stage: str, error: str = "") -> RollbackDecision:
        """Analyze whether to rollback and where.

        Rules:
        1. If failed at stage 0 (preflight), no rollback possible → escalate
        2. If failed at execute, roll back to pre-execute (re-scrutinize with new info)
        3. If failed at verify_gates, roll back to execute (retry with gate feedback)
        4. If failed at quality_review, roll back to execute (rework with review feedback)
        5. If previous rollback already failed at same target, escalate instead
        """
        if not self.checkpoints:
            return RollbackDecision(
                should_rollback=False,
                reason="No checkpoints available",
                alternative_strategy="human_escalate",
            )

        # Find the failed stage index
        failed_idx = -1
        for cp in self.checkpoints:
            if cp.stage_name == failed_stage:
                failed_idx = cp.stage_index
                break

        if failed_idx <= 0:
            return RollbackDecision(
                should_rollback=False,
                reason=f"Cannot rollback from {failed_stage} (index={failed_idx})",
                alternative_strategy="human_escalate",
            )

        # Find last successful checkpoint before the failure
        target = None
        for cp in reversed(self.checkpoints):
            if cp.stage_index < failed_idx and cp.success:
                target = cp
                break

        if not target:
            return RollbackDecision(
                should_rollback=False,
                reason="No successful checkpoint to roll back to",
                alternative_strategy="human_escalate",
            )

        # Check for rollback loops (already tried rolling back to this stage)
        rollback_attempts = sum(
            1 for cp in self.checkpoints
            if cp.stage_name == target.stage_name and not cp.success
        )
        if rollback_attempts >= 2:
            return RollbackDecision(
                should_rollback=False,
                reason=f"Already rolled back to {target.stage_name} {rollback_attempts} times",
                alternative_strategy="human_escalate",
            )

        # Determine strategy based on failure type
        strategy = "retry"
        if "test" in error.lower() or "gate" in error.lower():
            strategy = "retry_with_feedback"
        elif "timeout" in error.lower() or "stuck" in error.lower():
            strategy = "retry_with_simpler_model"
        elif "context" in error.lower() or "token" in error.lower():
            strategy = "retry_with_condensed_context"

        return RollbackDecision(
            should_rollback=True,
            target_stage=target.stage_name,
            target_index=target.stage_index,
            reason=f"Rolling back from {failed_stage} to {target.stage_name} (error: {error[:100]})",
            alternative_strategy=strategy,
        )

    def get_checkpoint(self, stage_name: str) -> StageCheckpoint | None:
        """Get the most recent checkpoint for a given stage."""
        for cp in reversed(self.checkpoints):
            if cp.stage_name == stage_name:
                return cp
        return None

    def get_last_success(self) -> StageCheckpoint | None:
        """Get the most recent successful checkpoint."""
        for cp in reversed(self.checkpoints):
            if cp.success:
                return cp
        return None

    def _persist(self, cp: StageCheckpoint) -> None:
        """Write checkpoint to disk for crash recovery."""
        try:
            path = Path(self.persist_dir) / f"task-{self.task_id}"
            path.mkdir(parents=True, exist_ok=True)
            fname = path / f"cp-{cp.stage_index:02d}-{cp.stage_name}.json"
            fname.write_text(json.dumps(cp.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            log.debug(f"Failed to persist checkpoint: {e}")

    def format_status(self) -> str:
        """Format checkpoint history for logging."""
        if not self.checkpoints:
            return "No checkpoints"
        lines = [f"Pipeline checkpoints for task #{self.task_id}:"]
        for cp in self.checkpoints:
            mark = "✅" if cp.success else "❌"
            lines.append(f"  {mark} [{cp.stage_index}] {cp.stage_name}")
        return "\n".join(lines)
