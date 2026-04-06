# Prompt Eval Closed Loop — Design Spec

> Governor-driven prompt evolution with Git Hook quality gate.
> Stolen from: Claude Code Skills 2.0 (eval + A/B + trigger optimization + production monitoring).

## Problem

Orchestrator has a complete eval toolkit (trajectory, rubric, experiment ledger, regression detection, corpus capture, epochs) but the pieces aren't wired into a closed loop. Prompt changes to department SKILL.md / prompt.md are made by intuition, not data. No automated verification that a prompt change improves performance. No production-to-eval feedback pipeline.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  GOVERNOR — Main Loop (drives evolution)                │
│                                                         │
│  1. Task execution → normal dispatch                    │
│  2. Production sampling → score + capture               │
│  3. Department health aggregation → rolling baselines   │
│  4. Degradation / weakness detection                    │
│  5. Prompt optimization trigger (auto or manual)        │
│  6. Generate prompt patch → git commit attempt          │
│                                                         │
└───────────────────────────┬─────────────────────────────┘
                            │ git commit
                            ▼
┌─────────────────────────────────────────────────────────┐
│  GIT HOOK — Quality Gate (guards against regression)    │
│                                                         │
│  1. Detect prompt file diff (SKILL.md / prompt.md)      │
│  2. Load department exam cases (exam_cases.jsonl)        │
│  3. Run eval: old prompt vs new prompt (A/B)            │
│  4. Bootstrap regression test                           │
│  5. Decision: keep (commit passes) / discard (blocked)  │
│  6. Write result to experiment ledger                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

```
Production task → Governor dispatch → Agent executes
                                          │
                    ┌─────────────────────┤
                    ▼                     ▼
              SUCCESS (5% sample)    FAILURE (100% capture)
                    │                     │
                    ▼                     ▼
            data/eval_corpus/       data/eval_corpus/
            sample_*.jsonl          corpus_*.jsonl
                    │                     │
                    └──────┬──────────────┘
                           ▼
                  departments/<dept>/<div>/exam_cases.jsonl
                  (auto-generated + manually curated)
                           │
                           ▼  (consumed by)
                  Git Hook A/B eval
                           │
                           ▼
                  data/experiments/<dept>/ledger.jsonl
```

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/governance/eval/prompt_eval.py` | **CREATE** | Core: load exam cases, run A/B, compare, decide |
| `src/governance/eval/department_rubric.py` | **CREATE** | Per-department weighted rubric definitions |
| `src/governance/eval/production_sampler.py` | **CREATE** | Success sampling + health aggregation |
| `src/governance/eval/harness.py` | **MODIFY** | Add production sampling hook + department-scoped ledger |
| `src/governance/eval/corpus.py` | **MODIFY** | Add success capture + exam case generation |
| `src/governance/eval/experiment.py` | **MODIFY** | Support department-scoped ledgers |
| `scripts/hooks/prompt-eval-gate.sh` | **CREATE** | pre-commit hook: detect prompt diff → call prompt_eval.py |
| `departments/<dept>/<div>/exam_cases.jsonl` | **CREATE** | Per-division eval test cases (auto + curated) |

## Component Design

### 1. Department Rubric (`department_rubric.py`)

Each department gets a rubric tailored to its job. Weights reflect what matters for that role.

```python
DEPARTMENT_RUBRICS: dict[str, list[RubricCriterion]] = {
    "engineering": [
        RubricCriterion(name="correctness",   weight=0.35, ...),
        RubricCriterion(name="completeness",   weight=0.25, ...),
        RubricCriterion(name="safety",         weight=0.20, ...),
        RubricCriterion(name="surgical_focus",  weight=0.20, ...),
        # surgical_focus: did it stay within task scope?
    ],
    "quality": [
        RubricCriterion(name="finding_accuracy", weight=0.30, ...),
        RubricCriterion(name="severity_calibration", weight=0.25, ...),
        RubricCriterion(name="coverage",          weight=0.25, ...),
        RubricCriterion(name="anti_sycophancy",   weight=0.20, ...),
    ],
    "operations": [
        RubricCriterion(name="diagnosis_accuracy", weight=0.35, ...),
        RubricCriterion(name="fix_safety",         weight=0.30, ...),
        RubricCriterion(name="completeness",       weight=0.20, ...),
        RubricCriterion(name="rollback_awareness", weight=0.15, ...),
    ],
    "personnel": [
        RubricCriterion(name="metric_accuracy",    weight=0.30, ...),
        RubricCriterion(name="trend_identification", weight=0.25, ...),
        RubricCriterion(name="anomaly_detection",  weight=0.25, ...),
        RubricCriterion(name="actionability",      weight=0.20, ...),
    ],
    "protocol": [
        RubricCriterion(name="coverage",           weight=0.30, ...),
        RubricCriterion(name="accuracy",           weight=0.30, ...),
        RubricCriterion(name="prioritization",     weight=0.20, ...),
        RubricCriterion(name="false_positive_rate", weight=0.20, ...),
    ],
    "security": [
        RubricCriterion(name="detection_accuracy", weight=0.35, ...),
        RubricCriterion(name="false_positive_rate", weight=0.25, ...),
        RubricCriterion(name="severity_calibration", weight=0.25, ...),
        RubricCriterion(name="remediation_quality", weight=0.15, ...),
    ],
}
```

Source: each department's SKILL.md scope definition + exam.md scoring anchors.

`get_department_rubric(dept: str) -> list[RubricCriterion]` — returns department-specific rubric, falls back to `scoring.py` generic rubric if department not found.

### 2. Exam Cases (`exam_cases.jsonl`)

Each department division gets a JSONL file of eval test cases.

```jsonl
{"id": "eng-impl-001", "input": "Fix null check in data_processor.py line 42", "expected_behavior": "Adds null guard, doesn't modify other logic, tests pass", "tags": ["bugfix", "surgical"], "source": "curated", "difficulty": "medium"}
{"id": "eng-impl-002", "input": "Add retry logic to API client", "expected_behavior": "Exponential backoff, configurable max retries, existing tests still pass", "tags": ["feature", "edge_cases"], "source": "corpus:task_127", "difficulty": "medium"}
```

Fields:
- `id`: `<dept>-<div>-<seq>` format
- `input`: task description (what the agent receives)
- `expected_behavior`: what a good response looks like (for LLM judge reference)
- `tags`: for filtering and analysis
- `source`: `curated` (human-written) | `corpus:<task_id>` (auto-generated from production) | `clawvard:<exam_id>` (from exam system)
- `difficulty`: `easy` | `medium` | `hard`

**Bootstrap strategy**: Start with 5-10 manually curated cases per division from existing exam.md content. Production sampling auto-expands over time.

### 3. Prompt Eval Engine (`prompt_eval.py`)

Core evaluation logic. Called by both Git Hook (A/B mode) and Governor (baseline mode).

```python
@dataclass
class PromptEvalResult:
    department: str
    division: str
    old_score: float           # baseline prompt score
    new_score: float           # candidate prompt score
    delta: float               # new - old
    regression: BootstrapResult  # statistical test
    decision: Decision         # keep / discard
    reason: str
    per_criterion: dict        # criterion → {old_score, new_score, delta}
    cases_run: int
    cost_usd: float

class PromptEvaluator:
    """A/B evaluation of prompt changes."""

    def __init__(self, epochs: int = 3, reducer: str = "mode"):
        self.epoch_runner = EpochRunner(epochs=epochs, reducer=reducer)

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
        ...

    async def evaluate_baseline(
        self,
        department: str,
        division: str,
        prompt: str,
    ) -> float:
        """Run eval on current prompt to establish/update baseline.

        Called by Governor during production health checks.
        """
        ...
```

**Eval function per case**: Given (prompt, exam_case) → score:
1. Build a simulated task from `exam_case.input`
2. Use `scoring.py`'s `build_judge_prompt()` with department-specific rubric
3. LLM judge scores against `exam_case.expected_behavior`
4. Return weighted rubric composite

**Cost control**:
- Default 3 epochs (mode reducer) per case — handles Clawvard's observed 35-point variance
- For A/B: run both variants on same cases (paired comparison, reduces variance)
- Minimum 10 cases for reliable A/B, skip if fewer available
- Budget cap: `max_cost_usd` parameter, abort if exceeded mid-eval

### 4. Production Sampler (`production_sampler.py`)

Runs inside Governor's post-task evaluation. Two jobs:
1. **Sample successful tasks** for eval corpus (currently only failures are captured)
2. **Aggregate department health** for degradation detection

```python
@dataclass
class DepartmentHealth:
    department: str
    rolling_mean: float        # last N task scores
    baseline: float            # established baseline
    delta: float               # rolling_mean - baseline
    sample_count: int
    alert: bool                # True if delta < -0.5
    weak_criteria: list[str]   # criteria consistently scoring low

class ProductionSampler:
    """Production sampling and department health tracking."""

    def __init__(self, sample_rate: float = 0.05, window: int = 20):
        self.sample_rate = sample_rate    # 5% of successful tasks
        self.window = window              # rolling window size
        self._scores: dict[str, list[float]] = defaultdict(list)

    def should_sample(self, task_id: int) -> bool:
        """Deterministic sampling based on task_id hash."""
        return (hash(task_id) % 100) < (self.sample_rate * 100)

    def record_score(self, department: str, score: float, criteria_scores: dict):
        """Record a task score for department health tracking."""
        ...

    def get_health(self, department: str) -> DepartmentHealth:
        """Get current health status for a department."""
        ...

    def get_all_health(self) -> dict[str, DepartmentHealth]:
        """Health status across all departments."""
        ...
```

**Integration point**: `EvalHarness.evaluate()` calls `sampler.record_score()` after every task. For sampled tasks, also calls `capture_success_for_corpus()`.

**Health persistence**: `data/department_health/<dept>.jsonl` — append-only, one line per recorded score. Git-tracked for diff/revert.

### 5. Corpus Enhancement (`corpus.py` modifications)

Two additions to existing corpus system:

**a) Success capture** — new function alongside `capture_for_corpus()`:

```python
def capture_success_for_corpus(
    task_id: int,
    task: dict,
    output: str,
    score: float,
    criteria_scores: dict,
    corpus_dir: Path | None = None,
) -> Optional[Path]:
    """Capture a successful task as a golden example.

    Only called for sampled tasks (5%). Stores in sample_*.jsonl
    alongside failure corpus_*.jsonl.
    """
    ...
```

**b) Auto exam case generation** — new method on `EvalCorpus`:

```python
def to_exam_cases(
    self,
    department: str,
    division: str | None = None,
    max_cases: int = 30,
) -> list[dict]:
    """Generate exam cases from corpus entries.

    For failures: "here's what went wrong, do better"
    For successes: "here's a golden example, match this quality"

    Returns exam_cases.jsonl compatible dicts.
    """
    ...
```

### 6. Department-Scoped Ledger (`experiment.py` modification)

Current ledger is global. Add department isolation:

```python
class ExperimentLedger:
    def __init__(self, ledger_dir=None, department: str | None = None):
        self._dir = ledger_dir or LEDGER_DIR
        if department:
            self._dir = self._dir / department  # data/experiments/engineering/
        ...
```

Each department gets its own `ledger.jsonl`. `current_best()` returns the best config for that department specifically.

### 7. Git Hook (`scripts/hooks/prompt-eval-gate.sh`)

pre-commit hook that detects prompt file changes and runs eval.

```bash
#!/usr/bin/env bash
# Prompt Eval Gate — pre-commit hook
# Blocks commits that regress department prompt quality.

PROMPT_PATTERNS=(
    "departments/*/SKILL.md"
    "departments/**/prompt.md"
)

changed_prompts=()
for pattern in "${PROMPT_PATTERNS[@]}"; do
    while IFS= read -r file; do
        [[ -n "$file" ]] && changed_prompts+=("$file")
    done < <(git diff --cached --name-only -- "$pattern" 2>/dev/null)
done

if [[ ${#changed_prompts[@]} -eq 0 ]]; then
    exit 0  # No prompt changes, pass through
fi

echo "🔍 Prompt changes detected: ${changed_prompts[*]}"
echo "   Running eval gate..."

# Extract department and division from path
for file in "${changed_prompts[@]}"; do
    dept=$(echo "$file" | cut -d'/' -f2)
    div=$(echo "$file" | cut -d'/' -f3)

    # Run A/B eval
    python -m src.governance.eval.prompt_eval \
        --department "$dept" \
        --division "$div" \
        --old-ref "HEAD" \
        --new-ref ":0:$file" \
        --mode ab

    result=$?
    if [[ $result -ne 0 ]]; then
        echo "❌ Prompt eval FAILED for $dept/$div — commit blocked"
        echo "   Run with --force to bypass (not recommended)"
        exit 1
    fi
done

echo "✅ Prompt eval passed for all changed departments"
```

**CLI interface** for `prompt_eval.py`:

```
python -m src.governance.eval.prompt_eval --department engineering --division implement --mode ab
python -m src.governance.eval.prompt_eval --department engineering --mode baseline
python -m src.governance.eval.prompt_eval --all --mode health-report
```

### 8. Harness Integration (`harness.py` modification)

Add production sampling to the existing pipeline:

```python
class EvalHarness:
    def __init__(self, ..., sampler: ProductionSampler | None = None):
        self._sampler = sampler or ProductionSampler()
        ...

    def evaluate(self, ...) -> EvalPipelineResult:
        # ... existing pipeline steps 1-6 ...

        # ── 7. Production sampling ──
        if self._sampler:
            self._sampler.record_score(
                department, result.composite_score,
                criteria_scores=result.trajectory_details,
            )
            if status == "done" and self._sampler.should_sample(task_id):
                capture_success_for_corpus(task_id, task, output, result.composite_score, ...)

        # ── 8. Department health check ──
        if self._sampler:
            health = self._sampler.get_health(department)
            if health.alert:
                log.warning(f"⚠️ Department {department} health degraded: "
                           f"{health.rolling_mean:.3f} vs baseline {health.baseline:.3f}")
                result.metadata["health_alert"] = True
                result.metadata["weak_criteria"] = health.weak_criteria

        return result
```

## Decision Logic

### A/B Eval Decision (Git Hook)

```
new_score > old_score                         → keep (commit passes)
new_score == old_score AND new_prompt shorter  → keep (simplicity wins)
new_score == old_score AND same length         → keep (neutral change OK)
new_score < old_score AND regression significant → discard (commit blocked)
new_score < old_score AND not significant      → keep with warning
fewer than 10 exam cases available             → keep with warning (insufficient data)
```

Note: "not significant" means the bootstrap CI contains 0 — could be noise. Allow the commit but log a warning.

### Health Alert Threshold

```
rolling_mean < baseline - 0.5  → alert (suggest prompt review)
rolling_mean < baseline - 1.0  → critical (auto-create improvement task)
3 consecutive alerts           → escalate to owner
```

## Exam Case Bootstrap Plan

For initial launch, seed exam cases from existing exam.md files:

| Department | Division | Existing exam.md | Seed cases |
|------------|----------|-----------------|------------|
| engineering | implement | Yes (2 evidence items) | 8 curated |
| operations | collect | Yes | 6 curated |
| operations | operate | Yes | 6 curated |
| personnel | analyze | Yes | 6 curated |
| personnel | recall | Yes | 6 curated |
| protocol | communicate | Yes | 5 curated |
| protocol | interpret | Yes | 5 curated |
| quality | review | Yes (6 exam runs documented) | 8 curated |

Divisions without exam.md get 3 minimal cases each, expanded by production sampling.

**Target**: 10+ cases per division within 2 weeks of production sampling.

## Cost Model

| Operation | Token cost | Frequency |
|-----------|-----------|-----------|
| A/B eval per case (3 epochs × 2 variants) | ~6K tokens | Per prompt commit |
| Production sample (1 LLM judge call) | ~2K tokens | 5% of tasks |
| Health aggregation | 0 (arithmetic) | Every task |
| Exam case generation from corpus | ~1K tokens | On corpus capture |

**Worst case**: 10-case A/B eval = ~60K tokens ≈ $0.18 (Sonnet). Acceptable as pre-commit gate.

## Boundaries

### What this system does NOT do
- **Auto-modify prompts**: Governor detects problems and CAN trigger optimization, but the actual prompt editing is a separate concern (human or future auto-optimizer). This spec covers detection + gating only.
- **Replace Clawvard**: Clawvard tests agent competency holistically. This tests individual prompt quality. Complementary, not overlapping.
- **Score individual tasks differently**: Production sampling uses the same `EvalHarness.evaluate()` pipeline. No new scoring logic.

### Future extensions (not in this spec)
- Auto-prompt optimizer: given weak criteria, generate candidate prompt patches
- Trigger accuracy testing: test department SKILL.md descriptions against natural language queries
- Cross-department regression: detect when improving one department degrades another
- Dashboard widget: visual health across all 6 departments

## Verification

Task complete when:
1. `prompt_eval.py --department engineering --mode baseline` runs and produces a score
2. Modifying `departments/engineering/implement/prompt.md` and committing triggers A/B eval
3. Intentionally degrading a prompt blocks the commit
4. `EvalHarness.evaluate()` records production samples to `data/eval_corpus/sample_*.jsonl`
5. `prompt_eval.py --all --mode health-report` shows per-department rolling health
6. Experiment ledger shows department-scoped entries in `data/experiments/<dept>/ledger.jsonl`
