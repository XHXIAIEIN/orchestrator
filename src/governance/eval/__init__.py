"""
Agent Evaluation module (R38 — stolen from Inspect AI, promptfoo, Braintrust, AutoAgent).

Provides:
  - trajectory: Tool call trajectory capture, scoring, and assertions
  - scoring: LLM-as-Judge rubric-based scoring with partial credit
  - corpus: Production→Test feedback loop (failed tasks → eval corpus)
  - experiment: Keep/Discard experiment ledger for config evolution
  - epochs: Multi-run evaluation with statistical aggregation (ScoreReducer)
  - early_stopping: Per-category adaptive stopping for mastered categories
  - regression: Bootstrap CI regression detection for score changes
  - registry: Decorator-based component registration for eval tasks/scorers
  - harness: Unified eval entry point for Governor integration
"""

# ── Core data capture ──
from src.governance.eval.trajectory import (
    TrajectoryTracker, TrajectoryScore, Trajectory,
    score_trajectory, assert_trajectory, trajectory_from_snapshot,
)
from src.governance.eval.scoring import (
    ScoringResult, RubricCriterion, Verdict,
    score_with_rubric, score_deterministic,
    get_rubric_for_task, infer_task_type,
)
from src.governance.eval.corpus import (
    capture_for_corpus, load_corpus, EvalCorpus, CAPTURABLE_STATUSES,
)

# ── Experiment lifecycle ──
from src.governance.eval.experiment import ExperimentLedger, ExperimentResult, ConfigSnapshot
from src.governance.eval.epochs import EpochRunner, ScoreReducer, reduce_scores
from src.governance.eval.early_stopping import EarlyStoppingPolicy
from src.governance.eval.regression import bootstrap_regression, check_regression

# ── Discovery ──
from src.governance.eval.registry import register_eval, list_registered, get_registered

# ── Harness (unified entry point) ──
from src.governance.eval.harness import EvalHarness, EvalPipelineResult

__all__ = [
    # trajectory
    "TrajectoryTracker", "TrajectoryScore", "Trajectory",
    "score_trajectory", "assert_trajectory", "trajectory_from_snapshot",
    # scoring
    "ScoringResult", "RubricCriterion", "Verdict",
    "score_with_rubric", "score_deterministic",
    "get_rubric_for_task", "infer_task_type",
    # corpus
    "capture_for_corpus", "load_corpus", "EvalCorpus", "CAPTURABLE_STATUSES",
    # experiment
    "ExperimentLedger", "ExperimentResult", "ConfigSnapshot",
    "EpochRunner", "ScoreReducer", "reduce_scores",
    "EarlyStoppingPolicy",
    "bootstrap_regression", "check_regression",
    # registry
    "register_eval", "list_registered", "get_registered",
    # harness
    "EvalHarness", "EvalPipelineResult",
]
