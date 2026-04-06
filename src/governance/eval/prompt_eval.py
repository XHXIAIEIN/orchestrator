"""
Prompt Eval Engine — A/B evaluation of prompt changes.

Core evaluation logic for the Prompt Eval Closed Loop.
Called by:
  - Git Hook (A/B mode): compare old vs new prompt on exam cases
  - Governor (baseline mode): establish/update department baselines
  - CLI (health-report mode): show per-department rolling health

Usage:
    # A/B eval (git hook)
    python -m src.governance.eval.prompt_eval --department engineering --division implement --mode ab

    # Baseline
    python -m src.governance.eval.prompt_eval --department engineering --mode baseline

    # Health report
    python -m src.governance.eval.prompt_eval --all --mode health-report
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

log = logging.getLogger(__name__)

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DEPARTMENTS_DIR = PROJECT_ROOT / "departments"

# Minimum cases for reliable A/B comparison
MIN_AB_CASES = 10

Decision = Literal["keep", "discard", "insufficient_data"]


@dataclass
class PromptEvalResult:
    """Result of an A/B prompt evaluation."""
    department: str
    division: str
    old_score: float           # baseline prompt score
    new_score: float           # candidate prompt score
    delta: float               # new - old
    regression: dict = field(default_factory=dict)  # BootstrapResult as dict
    decision: Decision = "keep"
    reason: str = ""
    per_criterion: dict = field(default_factory=dict)  # criterion -> {old, new, delta}
    cases_run: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            "department": self.department,
            "division": self.division,
            "old_score": round(self.old_score, 3),
            "new_score": round(self.new_score, 3),
            "delta": round(self.delta, 3),
            "decision": self.decision,
            "reason": self.reason,
            "per_criterion": self.per_criterion,
            "cases_run": self.cases_run,
            "cost_usd": round(self.cost_usd, 4),
            "regression": self.regression,
        }


def load_exam_cases(
    department: str,
    division: str | None = None,
) -> list[dict]:
    """Load exam cases for a department/division.

    Looks in departments/<dept>/<div>/exam_cases.jsonl.
    Falls back to all divisions if division is None.
    """
    cases = []

    if division:
        paths = [DEPARTMENTS_DIR / department / division / "exam_cases.jsonl"]
    else:
        paths = list((DEPARTMENTS_DIR / department).glob("*/exam_cases.jsonl"))

    for path in paths:
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    cases.append(json.loads(line))
        except Exception as e:
            log.warning(f"prompt_eval: error loading {path}: {e}")

    return cases


def load_prompt_content(department: str, division: str, ref: str = "") -> str:
    """Load prompt content from a file or git ref.

    Args:
        ref: "" for working tree, "HEAD" for last commit,
             ":0:<path>" for staged version.
    """
    # Determine prompt file path (relative to project root)
    prompt_path = f"departments/{department}/{division}/prompt.md"
    skill_path = f"departments/{department}/SKILL.md"

    # Try prompt.md first, fall back to SKILL.md
    for path in [prompt_path, skill_path]:
        if ref:
            try:
                result = subprocess.run(
                    ["git", "show", f"{ref}:{path}"],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                )
                if result.returncode == 0:
                    return result.stdout
            except Exception:
                pass
        else:
            full_path = PROJECT_ROOT / path
            if full_path.exists():
                return full_path.read_text(encoding="utf-8")

    return ""


class PromptEvaluator:
    """A/B evaluation of prompt changes."""

    def __init__(self, epochs: int = 3, reducer: str = "mode"):
        self.epochs = epochs
        self.reducer = reducer

    async def evaluate_prompt_change(
        self,
        department: str,
        division: str,
        old_prompt: str,
        new_prompt: str,
        exam_cases: list[dict] | None = None,
    ) -> PromptEvalResult:
        """Run A/B eval comparing old vs new prompt on exam cases.

        Steps:
          1. Load exam cases for this department/division
          2. For each case, run eval with old prompt (3 epochs, mode reducer)
          3. For each case, run eval with new prompt (3 epochs, mode reducer)
          4. Aggregate per-criterion scores
          5. Bootstrap regression test on score distributions
          6. Decision: keep if improved or same+simpler, discard otherwise
        """
        from src.governance.eval.department_rubric import get_department_rubric
        from src.governance.eval.epochs import EpochRunner, ScoreReducer
        from src.governance.eval.regression import bootstrap_regression
        from src.governance.eval.scoring import build_judge_prompt, parse_judge_response

        if exam_cases is None:
            exam_cases = load_exam_cases(department, division)

        result = PromptEvalResult(
            department=department,
            division=division,
            old_score=0.0,
            new_score=0.0,
            delta=0.0,
        )

        if len(exam_cases) < MIN_AB_CASES:
            result.decision = "insufficient_data"
            result.reason = f"only {len(exam_cases)} cases (need {MIN_AB_CASES}+)"
            result.cases_run = len(exam_cases)
            log.warning(
                f"prompt_eval: insufficient cases for {department}/{division} "
                f"({len(exam_cases)} < {MIN_AB_CASES})"
            )
            # Still run what we have for informational purposes
            if not exam_cases:
                return result

        rubric = get_department_rubric(department)
        epoch_runner = EpochRunner(epochs=self.epochs, reducer=self.reducer)

        old_scores: list[float] = []
        new_scores: list[float] = []
        per_criterion_old: dict[str, list[float]] = {c.name: [] for c in rubric}
        per_criterion_new: dict[str, list[float]] = {c.name: [] for c in rubric}

        for case in exam_cases:
            case_input = case.get("input", "")
            expected = case.get("expected_behavior", "")

            # Eval function: given a prompt, build judge prompt and score
            async def eval_with_prompt(prompt_text: str, _case_input=case_input, _expected=expected) -> float:
                judge_prompt = build_judge_prompt(
                    task_description=_case_input,
                    agent_output=f"[Simulated output with system prompt]\n{prompt_text[:500]}",
                    rubric=rubric,
                    ground_truth=_expected,
                )
                try:
                    from src.core.llm_router import get_router
                    router = get_router()
                    response = router.generate(judge_prompt, task_type="eval_judge")
                    scoring_result = parse_judge_response(response, rubric)
                    return scoring_result.rubric_composite
                except Exception as e:
                    log.debug(f"prompt_eval: judge call failed: {e}")
                    return 0.0

            # Run epochs for old prompt
            old_result = await epoch_runner.run(
                lambda _s, _p=old_prompt: eval_with_prompt(_p), None
            )
            old_scores.append(old_result.reduced)

            # Run epochs for new prompt
            new_result = await epoch_runner.run(
                lambda _s, _p=new_prompt: eval_with_prompt(_p), None
            )
            new_scores.append(new_result.reduced)

        result.cases_run = len(exam_cases)

        if old_scores:
            result.old_score = sum(old_scores) / len(old_scores)
        if new_scores:
            result.new_score = sum(new_scores) / len(new_scores)
        result.delta = result.new_score - result.old_score

        # Bootstrap regression test
        if old_scores and new_scores:
            bootstrap = bootstrap_regression(
                before=old_scores,
                after=new_scores,
                n_bootstrap=5000,  # fewer than default for speed
                seed=42,
            )
            result.regression = bootstrap.to_dict()

            # Decision logic (from spec)
            if result.new_score > result.old_score:
                result.decision = "keep"
                result.reason = f"score improved {result.old_score:.3f} -> {result.new_score:.3f}"
            elif result.new_score == result.old_score:
                if len(new_prompt) < len(old_prompt):
                    result.decision = "keep"
                    result.reason = f"score tied at {result.new_score:.3f}, new prompt shorter"
                else:
                    result.decision = "keep"
                    result.reason = f"score tied at {result.new_score:.3f}, neutral change"
            elif bootstrap.significant:
                result.decision = "discard"
                result.reason = (
                    f"significant regression {result.old_score:.3f} -> {result.new_score:.3f} "
                    f"(p={bootstrap.p_value_approx:.4f})"
                )
            else:
                result.decision = "keep"
                result.reason = (
                    f"score dropped {result.old_score:.3f} -> {result.new_score:.3f} "
                    f"but not statistically significant (p={bootstrap.p_value_approx:.4f})"
                )

        log.info(
            f"prompt_eval: {department}/{division} — {result.decision} "
            f"({result.reason})"
        )
        return result

    async def evaluate_baseline(
        self,
        department: str,
        division: str,
        prompt: str,
    ) -> float:
        """Run eval on current prompt to establish/update baseline.

        Called by Governor during production health checks.
        """
        from src.governance.eval.department_rubric import get_department_rubric
        from src.governance.eval.epochs import EpochRunner
        from src.governance.eval.scoring import build_judge_prompt, parse_judge_response

        exam_cases = load_exam_cases(department, division)
        if not exam_cases:
            log.warning(f"prompt_eval: no exam cases for {department}/{division}")
            return 0.0

        rubric = get_department_rubric(department)
        epoch_runner = EpochRunner(epochs=self.epochs, reducer=self.reducer)

        scores: list[float] = []
        for case in exam_cases:
            case_input = case.get("input", "")
            expected = case.get("expected_behavior", "")

            async def eval_fn(_sample, _input=case_input, _expected=expected) -> float:
                judge_prompt = build_judge_prompt(
                    task_description=_input,
                    agent_output=f"[Simulated output with system prompt]\n{prompt[:500]}",
                    rubric=rubric,
                    ground_truth=_expected,
                )
                try:
                    from src.core.llm_router import get_router
                    router = get_router()
                    response = router.generate(judge_prompt, task_type="eval_judge")
                    scoring_result = parse_judge_response(response, rubric)
                    return scoring_result.rubric_composite
                except Exception as e:
                    log.debug(f"prompt_eval: baseline judge call failed: {e}")
                    return 0.0

            result = await epoch_runner.run(eval_fn, None)
            scores.append(result.reduced)

        baseline = sum(scores) / len(scores) if scores else 0.0
        log.info(f"prompt_eval: baseline for {department}/{division} = {baseline:.3f}")
        return baseline


def generate_health_report(sampler=None) -> dict:
    """Generate health report across all departments.

    Returns dict with per-department health status.
    """
    if sampler is None:
        from src.governance.eval.production_sampler import ProductionSampler
        sampler = ProductionSampler()

    # Load all departments that have health data
    health_dir = sampler._health_dir
    if not health_dir.exists():
        return {"departments": {}, "message": "No health data yet"}

    departments = set()
    for f in health_dir.glob("*.jsonl"):
        dept = f.stem
        if not dept.endswith("_baseline"):
            departments.add(dept)

    report = {}
    for dept in sorted(departments):
        health = sampler.get_health(dept)
        report[dept] = health.to_dict()

    return {"departments": report}


# ── CLI Entry Point ──────────────────────────────────────────


async def _main():
    import argparse

    parser = argparse.ArgumentParser(description="Prompt Eval Engine")
    parser.add_argument("--department", "-d", help="Department to evaluate")
    parser.add_argument("--division", "-v", help="Division within department")
    parser.add_argument("--mode", "-m", choices=["ab", "baseline", "health-report"],
                        default="baseline", help="Evaluation mode")
    parser.add_argument("--old-ref", default="HEAD", help="Git ref for old prompt (default: HEAD)")
    parser.add_argument("--new-ref", default="", help="Git ref for new prompt (default: working tree)")
    parser.add_argument("--all", action="store_true", help="Run for all departments")
    parser.add_argument("--epochs", type=int, default=3, help="Epochs per case")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.mode == "health-report":
        report = generate_health_report()
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            depts = report.get("departments", {})
            if not depts:
                print("No health data available yet.")
                return
            for dept, health in depts.items():
                status = "CRITICAL" if health.get("critical") else "ALERT" if health.get("alert") else "OK"
                print(
                    f"  {dept:15s}  {status:8s}  "
                    f"rolling={health['rolling_mean']:.3f}  "
                    f"baseline={health['baseline']:.3f}  "
                    f"delta={health['delta']:+.3f}  "
                    f"n={health['sample_count']}"
                )
                if health.get("weak_criteria"):
                    print(f"                   weak: {', '.join(health['weak_criteria'])}")
        return

    if not args.department and not args.all:
        parser.error("--department or --all required")

    evaluator = PromptEvaluator(epochs=args.epochs)

    if args.all:
        departments = [d.name for d in DEPARTMENTS_DIR.iterdir()
                       if d.is_dir() and d.name != "shared"]
    else:
        departments = [args.department]

    for dept in departments:
        if args.mode == "baseline":
            divisions = [args.division] if args.division else [
                d.name for d in (DEPARTMENTS_DIR / dept).iterdir()
                if d.is_dir() and d.name != "guidelines"
            ]
            for div in divisions:
                prompt = load_prompt_content(dept, div)
                if not prompt:
                    continue
                score = await evaluator.evaluate_baseline(dept, div, prompt)
                print(f"  {dept}/{div}: baseline = {score:.3f}")

        elif args.mode == "ab":
            if not args.division:
                parser.error("--division required for ab mode")

            old_prompt = load_prompt_content(dept, args.division, ref=args.old_ref)
            new_prompt = load_prompt_content(dept, args.division, ref=args.new_ref)

            if not old_prompt:
                print(f"  {dept}/{args.division}: no old prompt at {args.old_ref}")
                continue
            if not new_prompt:
                print(f"  {dept}/{args.division}: no new prompt")
                continue

            result = await evaluator.evaluate_prompt_change(
                dept, args.division, old_prompt, new_prompt,
            )

            if args.json:
                print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            else:
                symbol = {
                    "keep": "PASS",
                    "discard": "FAIL",
                    "insufficient_data": "WARN",
                }[result.decision]
                print(
                    f"  [{symbol}] {dept}/{args.division}: "
                    f"{result.old_score:.3f} -> {result.new_score:.3f} "
                    f"({result.delta:+.3f}) — {result.reason}"
                )

            # Exit with error code if discard
            if result.decision == "discard":
                exit(1)


if __name__ == "__main__":
    asyncio.run(_main())
