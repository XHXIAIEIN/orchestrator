"""
EvalHarness — Unified evaluation entry point for Governor integration.

Orchestrates all eval subsystems in a single pipeline:
  1. Trajectory scoring (deterministic, from execution data)
  2. Rubric-based scoring (LLM-as-Judge, optional)
  3. Experiment ledger recording (keep/discard decision)
  4. Regression detection (bootstrap CI vs history)
  5. Early stopping tracking (per-category mastery)

Usage in ReviewManager.finalize_task():
    harness = EvalHarness()
    result = harness.evaluate(
        task_id=42,
        task=task,
        status="done",
        output=output,
        trajectory_summary=trajectory_summary,
        department=dept_key,
    )
    # result.composite_score, result.decision, result.regression, ...

All steps are optional-tolerant: if a subsystem fails, the harness
logs and continues. No single eval component can block task finalization.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class EvalPipelineResult:
    """Unified result from the full eval pipeline."""
    task_id: int = 0
    # Trajectory
    trajectory_composite: float = 0.0
    trajectory_details: dict = field(default_factory=dict)
    # Rubric scoring (if LLM judge ran)
    rubric_composite: float = 0.0
    rubric_weak_dims: list[str] = field(default_factory=list)
    has_critical_weakness: bool = False
    # Experiment ledger
    experiment_decision: str = ""      # keep / discard / baseline / ""
    experiment_reason: str = ""
    # Regression
    regression_direction: str = ""     # improved / regressed / stable / ""
    regression_significant: bool = False
    # Early stopping
    category_stopped: bool = False
    # Composite
    composite_score: float = 0.0       # weighted blend of trajectory + rubric

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "trajectory_composite": round(self.trajectory_composite, 3),
            "rubric_composite": round(self.rubric_composite, 3),
            "rubric_weak_dims": self.rubric_weak_dims,
            "has_critical_weakness": self.has_critical_weakness,
            "experiment_decision": self.experiment_decision,
            "experiment_reason": self.experiment_reason,
            "regression_direction": self.regression_direction,
            "regression_significant": self.regression_significant,
            "category_stopped": self.category_stopped,
            "composite_score": round(self.composite_score, 3),
        }


class EvalHarness:
    """Unified eval pipeline for Governor post-execution evaluation.

    All subsystems are lazily imported and fail-tolerant.
    The harness never raises — it logs warnings and returns partial results.
    """

    def __init__(self, ledger_dir=None, enable_llm_judge: bool = False):
        """
        Args:
            ledger_dir: Override for ExperimentLedger storage path.
            enable_llm_judge: Whether to run LLM-as-Judge scoring (costs tokens).
                              Default False — only trajectory scoring runs by default.
        """
        self._ledger_dir = ledger_dir
        self._enable_llm_judge = enable_llm_judge
        self._ledger = None
        self._early_stopping = None

    @property
    def ledger(self):
        """Lazy-init ExperimentLedger."""
        if self._ledger is None:
            try:
                from src.governance.eval.experiment import ExperimentLedger
                self._ledger = ExperimentLedger(ledger_dir=self._ledger_dir)
            except Exception as e:
                log.warning(f"EvalHarness: ExperimentLedger init failed: {e}")
        return self._ledger

    @property
    def early_stopping(self):
        """Lazy-init EarlyStoppingPolicy."""
        if self._early_stopping is None:
            try:
                from src.governance.eval.early_stopping import EarlyStoppingPolicy
                self._early_stopping = EarlyStoppingPolicy(
                    consecutive_threshold=3, min_samples=2,
                )
            except Exception as e:
                log.warning(f"EvalHarness: EarlyStoppingPolicy init failed: {e}")
        return self._early_stopping

    def evaluate(
        self,
        task_id: int,
        task: dict,
        status: str,
        output: str,
        trajectory_summary: dict,
        department: str,
    ) -> EvalPipelineResult:
        """Run the full eval pipeline on a completed task.

        Pipeline order:
          1. Trajectory scoring (always, from execution data)
          2. Rubric scoring (optional, requires LLM call)
          3. Composite score calculation
          4. Early stopping check (per-department category)
          5. Experiment ledger recording
          6. Regression detection

        All steps are fail-tolerant.
        """
        result = EvalPipelineResult(task_id=task_id)

        # ── 1. Trajectory scoring ──
        score_data = trajectory_summary.get("score", {})
        result.trajectory_composite = score_data.get("composite", 0.0)
        result.trajectory_details = score_data

        # ── 2. Rubric scoring (optional) ──
        if self._enable_llm_judge and status == "done":
            result = self._run_rubric_scoring(result, task, output)

        # ── 3. Composite score ──
        # If rubric ran, blend 60% rubric + 40% trajectory.
        # Otherwise, trajectory alone.
        if result.rubric_composite > 0:
            result.composite_score = (
                result.rubric_composite * 0.6
                + result.trajectory_composite * 0.4
            )
        else:
            result.composite_score = result.trajectory_composite

        # ── 4. Early stopping ──
        es = self.early_stopping
        if es:
            try:
                if es.should_skip(department):
                    result.category_stopped = True
                    log.debug(f"EvalHarness: department '{department}' already mastered, skipping deep eval")
                else:
                    es.report(department, result.composite_score)
                    result.category_stopped = es.should_skip(department)
            except Exception as e:
                log.debug(f"EvalHarness: early stopping failed: {e}")

        # ── 5. Experiment ledger ──
        ledger = self.ledger
        if ledger and result.composite_score > 0:
            try:
                from src.governance.eval.experiment import ConfigSnapshot
                import hashlib

                # Build config snapshot from current task context
                action = task.get("action", "")
                config = ConfigSnapshot(
                    prompt_hash=hashlib.sha256(action.encode()).hexdigest()[:16],
                    prompt_length=len(output),
                    tool_count=trajectory_summary.get("tool_calls_count", 0),
                    model=task.get("spec", {}).get("model", "default"),
                )
                exp_result = ledger.record_experiment(
                    name=f"task_{task_id}_{department}",
                    config=config,
                    score=result.composite_score,
                    cost_usd=0.0,  # cost tracked elsewhere
                    metadata={
                        "task_id": task_id,
                        "department": department,
                        "status": status,
                    },
                )
                result.experiment_decision = exp_result.decision
                result.experiment_reason = exp_result.reason
            except Exception as e:
                log.debug(f"EvalHarness: experiment ledger recording failed: {e}")

        # ── 6. Regression detection ──
        if ledger:
            try:
                from src.governance.eval.regression import check_regression
                history = ledger.history(limit=10)
                if len(history) >= 2:
                    experiment_data = [
                        {"name": e.name, "scores": [e.score]}
                        for e in reversed(history)
                    ]
                    regressions = check_regression(experiment_data, lookback=5)
                    if regressions:
                        latest = regressions[0]
                        result.regression_direction = latest.direction
                        result.regression_significant = latest.significant
                        if latest.significant and latest.direction == "regressed":
                            log.warning(
                                f"EvalHarness: REGRESSION detected for {department} "
                                f"(diff={latest.mean_diff:+.4f}, p≈{latest.p_value_approx:.4f})"
                            )
            except Exception as e:
                log.debug(f"EvalHarness: regression detection failed: {e}")

        log.info(
            f"EvalHarness: task #{task_id} [{department}] "
            f"composite={result.composite_score:.3f} "
            f"traj={result.trajectory_composite:.3f} "
            f"decision={result.experiment_decision or 'n/a'}"
        )
        return result

    def _run_rubric_scoring(self, result: EvalPipelineResult,
                            task: dict, output: str) -> EvalPipelineResult:
        """Run LLM-as-Judge rubric scoring. Fail-tolerant."""
        try:
            from src.governance.eval.scoring import (
                score_deterministic, infer_task_type, get_rubric_for_task,
                build_judge_prompt, parse_judge_response, ScoringResult,
            )

            action = task.get("action", "")

            # Deterministic checks first (free)
            det_checks = score_deterministic(
                output,
                expected_format=task.get("spec", {}).get("expected_format"),
                max_length=task.get("spec", {}).get("max_length"),
            )

            # Rubric scoring (costs tokens)
            task_type = infer_task_type(action)
            rubric = get_rubric_for_task(task_type)
            prompt = build_judge_prompt(
                task_description=action,
                agent_output=output[:3000],
                rubric=rubric,
                ground_truth=task.get("spec", {}).get("expected", ""),
            )

            try:
                from src.core.llm_router import get_router
                router = get_router()
                judge_response = router.generate(prompt, task_type="eval_judge")
                scoring_result = parse_judge_response(judge_response, rubric)

                result.rubric_composite = scoring_result.rubric_composite
                result.rubric_weak_dims = scoring_result.weak_dimensions
                result.has_critical_weakness = scoring_result.has_critical_weakness
            except Exception as e:
                log.debug(f"EvalHarness: LLM judge call failed: {e}")
                # Fall back to deterministic-only
                det_score = sum(1 for v in det_checks.values() if v) / max(len(det_checks), 1)
                result.rubric_composite = det_score

        except Exception as e:
            log.debug(f"EvalHarness: rubric scoring import/setup failed: {e}")

        return result

    def get_stats(self) -> dict:
        """Return aggregate stats from all subsystems."""
        stats = {}
        if self.ledger:
            try:
                stats["experiment"] = self.ledger.stats()
            except Exception:
                pass
        if self.early_stopping:
            try:
                stats["early_stopping"] = self.early_stopping.stats()
            except Exception:
                pass
        return stats
