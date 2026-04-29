# Plan: R38 Eval Pattern Adoption — Wiring Existing Modules + Gap Fill

## Goal

All four R38 "Immediate" patterns are wired and verified: `LoopState` has token/time budget fields,
`ExamResult` reports bootstrap confidence intervals alongside dimension scores, `EvalHarness` passes
regression results back to `ingest_exam` so the fitness loop sees quantitative deltas, and a
`docker-compose.eval.yml` sandbox file exists with resource limits matching the R38 spec.

---

## Context

R38 identified 19 patterns across scoring / sandboxing / dataset / reporting. A prior implementation
session (identifiable via `src/governance/eval/` module existence) shipped:

- `trajectory.py` — `TrajectoryTracker`, `TrajectoryScore`, `score_trajectory`, `assert_trajectory`
- `scoring.py` — `RubricCriterion`, `RubricScore`, `ModelGradedScore`, `ScoringResult`
- `regression.py` — `bootstrap_regression`, `BootstrapResult`
- `harness.py` — `EvalHarness.evaluate()` wired into `review.py` at line 437
- `experiment.py` — `ExperimentLedger` keep/discard decisions

**Remaining gaps confirmed by source inspection (2026-04-18)**:

| Gap | Location | Evidence |
|-----|----------|----------|
| `LoopState` has no token/time budget fields | `eval_loop.py` lines 61-78 | Only `iteration` + `max_iterations` |
| `ExamResult` has no CI fields | `self_eval.py` lines 41-43 | Only `exam_id`, `dimensions`, `grade`, `percentile` |
| `ingest_exam` doesn't consume regression alerts | `self_eval.py` lines 56-139 | No import from `regression.py` |
| Docker eval sandbox file absent | worktree root | `docker-compose.eval.yml` not found |

Sandboxing Sections 2.2+ (MicroVM, overlayfs) are explicitly out of scope — R38 retro Section 9
check 3 found zero `src/` targets for those patterns. They remain reference appendix material.

---

## ASSUMPTIONS

- `ASSUMPTION: score_with_confidence` — The plan adds `bootstrap_confidence` to `ExamResult` by calling
  `bootstrap_regression` from `regression.py` after aggregating per-dimension scores from multiple exam
  runs in DB. If the DB query surface for historical exam scores is unavailable, step 5 falls back to
  single-sample CI (width = 0, lower = upper = mean).
- `ASSUMPTION: Docker availability` — `docker-compose.eval.yml` targets local dev use. No CI pipeline
  integration is planned here; that is a separate task.
- `ASSUMPTION: LoopState is not serialized to DB` — Adding fields to `LoopState` is a pure in-memory
  change. If `LoopState` is persisted anywhere, owner must verify schema migration separately.

---

## File Map

- `src/governance/pipeline/eval_loop.py` — Modify: add `token_budget` and `wall_time_limit_s` fields to `LoopState`; add `EvalResourceLimits` dataclass
- `src/governance/audit/self_eval.py` — Modify: add `ci_lower`, `ci_upper`, `n_samples` fields to `ExamResult`; call `bootstrap_regression` inside `ingest_exam` when prior exam scores are available in DB
- `src/governance/eval/harness.py` — Modify: expose `regression_significant` and `regression_direction` in `EvalPipelineResult.to_dict()` return to `review.py` caller; currently populated but `metadata` key only
- `docker-compose.eval.yml` — Create: eval sandbox service with mem/cpu/network/pids limits matching R38 §2.1 spec

---

## Steps

1. Read `src/governance/pipeline/eval_loop.py` lines 1-160 in full to confirm no existing `EvalResourceLimits` symbol before adding it
   → verify: `grep -n "EvalResourceLimits\|token_budget\|wall_time" src/governance/pipeline/eval_loop.py` returns zero matches

2. Add `EvalResourceLimits` dataclass to `src/governance/pipeline/eval_loop.py` after line 58 (before `LoopState`) with fields: `max_wall_time_s: int = 300`, `max_tokens_in: int = 100_000`, `max_tokens_out: int = 50_000`, `max_tool_calls: int = 50`, `max_llm_calls: int = 20`; and add `resource_limits: EvalResourceLimits = field(default_factory=EvalResourceLimits)` plus `tokens_used_in: int = 0` and `tokens_used_out: int = 0` to `LoopState`
   - depends on: step 1
   → verify: `python -c "from src.governance.pipeline.eval_loop import EvalResourceLimits, LoopState; s = LoopState(); print(s.resource_limits.max_wall_time_s)"`  prints `300`

3. Add `budget_exceeded` property to `LoopState` in `src/governance/pipeline/eval_loop.py` that returns `True` when `tokens_used_in >= resource_limits.max_tokens_in` or `tokens_used_out >= resource_limits.max_tokens_out`
   - depends on: step 2
   → verify: `python -c "from src.governance.pipeline.eval_loop import LoopState; s = LoopState(); s.tokens_used_in = 200_000; print(s.budget_exceeded)"` prints `True`

4. Read `src/governance/audit/self_eval.py` lines 40-55 to confirm exact `ExamResult` field list before modifying
   → verify: `grep -n "exam_id\|dimensions\|grade\|percentile\|ci_lower\|n_samples" src/governance/audit/self_eval.py | head -10` shows `ci_lower` absent

5. Add `ci_lower: float = 0.0`, `ci_upper: float = 0.0`, `n_samples: int = 1` to `ExamResult` dataclass in `src/governance/audit/self_eval.py` (append after `percentile` field)
   - depends on: step 4
   → verify: `python -c "from src.governance.audit.self_eval import ExamResult; r = ExamResult('x', {}, 'B', 50); print(r.ci_lower, r.ci_upper, r.n_samples)"` prints `0.0 0.0 1`

6. Add import `from src.governance.eval.regression import bootstrap_regression` at the top of `src/governance/audit/self_eval.py` imports block (after existing governance imports, line ~30)
   - depends on: step 5
   → verify: `python -c "from src.governance.audit.self_eval import ingest_exam"` executes without `ImportError`

7. Add a helper function `_compute_exam_ci(exam_id: str, dimension: str, current_score: float, db) -> tuple[float, float, int]` to `src/governance/audit/self_eval.py` that: queries `db` for the last 10 records matching `entry_type="error"` and `pattern_key` containing the dimension (via `db.get_recent_learnings(area="agent-self", limit=10)`), extracts numeric scores from `detail` field using `re.search(r"score=(\d+(?:\.\d+)?)/100", detail)`, calls `bootstrap_regression(before=historical_scores, after=[current_score], n_bootstrap=1000)` if `len(historical_scores) >= 3`, and returns `(ci_lower, ci_upper, n_samples)`; returns `(current_score, current_score, 1)` if fewer than 3 historical points exist
   - depends on: step 6
   → verify: `python -c "from src.governance.audit.self_eval import _compute_exam_ci; print('ok')"` prints `ok`

8. Wire `_compute_exam_ci` into `ingest_exam` in `src/governance/audit/self_eval.py`: after `verdict = evaluate_rules(...)` line 78, compute aggregate score as `overall = sum(result.dimensions.values()) / len(result.dimensions) if result.dimensions else 0.0`, call `ci_lower, ci_upper, n_samples = _compute_exam_ci(result.exam_id, "overall", overall, db)`, and assign back to `result.ci_lower = ci_lower; result.ci_upper = ci_upper; result.n_samples = n_samples` before the return
   - depends on: step 7
   → verify: `grep -n "_compute_exam_ci\|ci_lower\|ci_upper" src/governance/audit/self_eval.py` shows at least 3 hits including one in function body after line 78

9. Read `src/governance/eval/harness.py` lines 55-200 to identify exact location where `regression_direction` and `regression_significant` are populated and verify they currently write to `metadata` not top-level fields
   → verify: `grep -n "regression_direction\|regression_significant\|metadata" src/governance/eval/harness.py | head -15` shows current population point

10. Confirm `EvalPipelineResult.to_dict()` in `src/governance/eval/harness.py` already includes `regression_direction` and `regression_significant` at the top level (lines 59-75 show it does); if absent, add them to the dict body under the `composite_score` key
    - depends on: step 9
    → verify: `python -c "from src.governance.eval.harness import EvalPipelineResult; r = EvalPipelineResult(regression_direction='regressed', regression_significant=True); d = r.to_dict(); print(d['regression_direction'], d['regression_significant'])"` prints `regressed True`

11. Create `docker-compose.eval.yml` at worktree root with a single service `eval-sandbox` using `build: ./eval` context, `mem_limit: 2g`, `cpus: 1.0`, `network_mode: none`, `read_only: true`, `tmpfs: [/tmp:size=512m]`, `volumes: [./eval-tasks:/tasks:ro, eval-output:/output]`, `security_opt: [no-new-privileges:true]`, `pids_limit: 100`; add a top-level `volumes: {eval-output: {}}` section
    → verify: `docker compose -f docker-compose.eval.yml config --quiet` exits 0 (or `python -c "import yaml; yaml.safe_load(open('docker-compose.eval.yml'))"` if docker unavailable)

12. Run the full eval module import chain to confirm no circular imports introduced by steps 2-8
    - depends on: steps 3, 8, 10
    → verify: `python -c "from src.governance.eval.harness import EvalHarness; from src.governance.audit.self_eval import ingest_exam; from src.governance.pipeline.eval_loop import LoopState, EvalResourceLimits; print('all imports ok')"` prints `all imports ok`

---

## Non-Goals

- MicroVM sandboxes (Firecracker/gVisor) — no `src/` target identified; R38 §9 check 3 explicitly fails for this
- Multi-judge consensus (`ConsensusEvaluator`) — reserved for when single-judge eval shows measurable bias; no baseline exists yet
- Dynamic task generation (`TaskGenerator`) — Clawvard exams not saturated; trigger condition unmet
- Self-consistency checks (`consistency_check`) — boot.md promotion pipeline not yet producing candidates at sufficient volume
- Contamination detection — no external benchmarks in use
- Dashboard eval tab — frontend work outside this plan's scope
- AdaRubric adaptive rubric generation — `scoring.py` has static rubrics; adaptive generation requires a prompt template session

---

## Rollback

If any step introduces an import error or test regression:

1. `git diff src/governance/pipeline/eval_loop.py src/governance/audit/self_eval.py src/governance/eval/harness.py` to identify changed lines
2. `git stash` to preserve changes as `stash@{0}`
3. Restore individual files via `git checkout stash@{0} -- <file>` if only one file is bad
4. `docker-compose.eval.yml` can be deleted directly (it is a new file, no prior state to restore)

--- PHASE GATE: Plan → Implement ---
[ ] Deliverable exists: this plan file at `docs/plans/2026-04-18-r38-sandbox-retro-impl.md`
[ ] Acceptance criteria: 4 gaps from context table each have ≥1 step with explicit file + line target
[ ] No open questions: CI fallback behavior stated in ASSUMPTIONS; Docker availability stated
[ ] Owner review: required before implementation begins (scope crosses 4 files + new config)
