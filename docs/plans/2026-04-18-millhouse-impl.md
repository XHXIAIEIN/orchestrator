# Plan: Millhouse Steal — Phase Coordination + Non-Progress Detection + Ensemble Review

## Goal

Orchestrator gains three durable capabilities: (1) a machine-readable phase state file that prevents skill entry when phase is wrong; (2) a non-progress detector that blocks review doom-loops by comparing per-slice pushed-back bullets across rounds; (3) an ensemble reviewer registry that fans out N workers concurrently and degrades gracefully instead of crashing.

---

## Context

Source: R80 Millhouse steal (`docs/steal/R80-millhouse-steal.md`).

P0 patterns being implemented here (by priority/coupling):

| Tag | Pattern | Gap severity |
|-----|---------|-------------|
| P0#3 | Load-before-read + 7 dismissal bans in rationalization-immunity | Small — 1 file patch |
| P0#2 | `_phase/status.md` schema + skill entry guards | Large |
| P0#1 | `review_loop.py` non-progress detector + fixer report `## Pushed Back` contract | Large |
| P0#6 | `.claude/reviewers/` two-level registry + `ensemble.py` fan-out | Medium |
| P0#4 | `plan_dag.py` write-conflict edges + plan_template `creates/modifies/reads` fields | Medium |

P0#5 (self-report tooling-bug loop) is **excluded** from this plan — it requires a stop hook + `tooling-bugs.jsonl` + `revise-tasks` skill. That is its own ~6h plan. Owner to schedule separately.

P1 patterns (one-pass regex, exit-code taxonomy, etc.) are **Non-Goals** here; tracked in ASSUMPTIONS below.

---

## ASSUMPTIONS

1. **ASSUMPTION: `SOUL/tools/` Python files are importable from the repo root via `python SOUL/tools/<file>.py`** — no packaging, no `setup.py`. Verify from existing `compiler.py` usage before implementing `review_loop.py` and `ensemble.py`.
2. **ASSUMPTION: `.claude/skills/` SKILL.md files use freeform markdown** — no enforced schema validator currently. Phase guard will be a prose rule, not a machine-checked assertion.
3. **ASSUMPTION: `asyncio` is available** (Python 3.8+) for `ensemble.py` fan-out. If the environment uses Python 3.7, replace `asyncio.gather` with `ThreadPoolExecutor` from `concurrent.futures`.
4. **ASSUMPTION: The `creates:` / `modifies:` / `reads:` fields added to plan_template are advisory** — no CI validator will enforce them at commit time. A standalone `plan_dag.py --validate <plan.md>` is the manual check.
5. **ASSUMPTION: P0#5 (self-report + stop hook + tooling-bugs.jsonl) is out of scope** — owner to plan separately.
6. **ASSUMPTION: `SOUL/private/tooling-bugs.jsonl` does not exist yet** — confirmed by not listing it in scope. If it is created as a side effect, note in final diff report.
7. **ASSUMPTION: The worktree's Python is the system Python** — no venv activation needed for `python SOUL/tools/...` invocations.

---

## File Map

| File | Action | Phase |
|------|--------|-------|
| `SOUL/public/prompts/rationalization-immunity.md` | Modify — append "Review Dismissal" section with 7 forbidden phrases + load-before-read rule | Step 1 |
| `SOUL/public/prompts/phase_state.md` | Create — defines `_phase/status.md` YAML+Timeline schema and skill entry guard rules | Step 2 |
| `SOUL/tools/review_loop.py` | Create — `PlanReviewLoop` state machine: `APPROVED / CONTINUE / BLOCKED_NON_PROGRESS / BLOCKED_MAX_ROUNDS` | Steps 3–4 |
| `.claude/skills/verification-gate/SKILL.md` | Modify — prepend "Load rationalization-immunity BEFORE reading any review output" hard rule | Step 5 |
| `SOUL/tools/ensemble.py` | Create — `EnsembleRunner`: `asyncio.gather` fan-out over worker list, `DEGRADED_FATAL` on total failure, `Write`-to-disk result (no stdout parse) | Steps 6–7 |
| `.claude/reviewers/workers.yaml` | Create — atomic worker registry: `name / provider / model / effort / dispatch_mode` | Step 8 |
| `.claude/reviewers/reviewers.yaml` | Create — ensemble registry: `name / worker / worker_count / handler / handler_prep` | Step 8 |
| `SOUL/tools/plan_dag.py` | Create — `build_dag()` + `extract_layers()` + `CycleError` with explicit cycle path | Steps 9–10 |
| `SOUL/public/prompts/plan_template.md` | Modify — add `creates:` / `modifies:` / `reads:` fields to Step Format Reference section | Step 11 |

---

## Steps

### Phase A — Rationalization Immunity + Load-Before-Read (P0#3)

**Step 1.** Append a "Review Dismissal" table to `SOUL/public/prompts/rationalization-immunity.md` immediately after the last existing table, with the following 7 rows (exact text):

```markdown
## Review Dismissal

> Applies when receiving any reviewer output. Load this file BEFORE reading the review — once you have read the findings, rationalizations have already formed.

| Forbidden Dismissal | Why It Fails | Correct Behavior |
|---|---|---|
| "This is low risk" | Risk is assessed after investigation, not before. You have not investigated. | Fix it. |
| "This is out of scope for this task" | Scope does not make a bug disappear. It makes it someone else's future emergency. | Fix it or file a tracked issue — do not dismiss. |
| "This is pre-existing / not my fault" | You touched the code. You own the blast radius. | Fix it. |
| "The reviewer doesn't understand the context" | You have 30 seconds of context. The reviewer has the full diff. | Fix it. |
| "This will break other things" | Unverified fear. Run the tests. | Run the tests. If they break, fix the root cause. |
| "This is a style nit" | Style rot compounds. One "nit" per PR = unreadable codebase in 6 months. | Fix it. |
| "I'll address this in a follow-up" | Follow-ups are where good intentions go to die. | Fix it now or write a concrete JIRA/issue with repro steps before closing this session. |
```

→ verify: `grep -n "Review Dismissal" SOUL/public/prompts/rationalization-immunity.md` returns a line number.

---

### Phase B — Phase State Schema (P0#2)

**Step 2.** Create `SOUL/public/prompts/phase_state.md` with the following exact content (this is a spec document, not code):

```markdown
# Phase State Schema

## Purpose

`_phase/status.md` is the single source of truth for a task's lifecycle phase.
Every skill that can change phase MUST read this file on entry and write to it on exit.
A skill that enters when `phase:` does not match its expected phase MUST stop and print:
`PHASE MISMATCH — expected <X>, current phase is <Y>. Read _phase/status.md.`

## File Location

`_phase/status.md` lives at the task root (beside `_phase/`).
It is NOT tracked in git (add to `.gitignore` or use a gitignored subdirectory).

## Schema

~~~yaml
task: <one-line task identifier>
phase: discussing | planning | implementing | reviewing | done | blocked
blocked_reason: <string, only present when phase=blocked>
plan_start_hash: <git SHA when planning phase began, used for staleness check>
started: <ISO-8601 timestamp of current phase start>
~~~

## Timeline Block

After the YAML block, append a `## Timeline` section.
Each phase transition appends one line — never edit existing lines.

~~~
## Timeline
2026-04-18T10:00Z  discussing   → planning    (plan file: docs/plans/foo.md)
2026-04-18T10:45Z  planning     → implementing
~~~

## Append Protocol

To write a transition without corrupting the YAML:
1. Read the full file.
2. Update ONLY the `phase:` (and `started:`) keys in the YAML block.
3. Append one line to `## Timeline` — never insert, never edit past entries.

## Skill Entry Guard (copy this block into each skill's SKILL.md preamble)

```
### Phase Guard
1. Read `_phase/status.md` (if file absent → create it with `phase: discussing`).
2. If `phase:` ≠ `<EXPECTED_PHASE_FOR_THIS_SKILL>` → STOP. Print PHASE MISMATCH error. Do not proceed.
3. Proceed.
```
```

→ verify: `test -f SOUL/public/prompts/phase_state.md && wc -l SOUL/public/prompts/phase_state.md` prints a line count ≥ 40.

---

### Phase C — Non-Progress Detector (P0#1)

**Step 3.** Create `SOUL/tools/review_loop.py` with the `PlanReviewLoop` class. The file must contain:

- Constants: `VERDICT_APPROVED = "APPROVED"`, `VERDICT_CONTINUE = "CONTINUE"`, `VERDICT_BLOCKED_NON_PROGRESS = "BLOCKED_NON_PROGRESS"`, `VERDICT_BLOCKED_MAX_ROUNDS = "BLOCKED_MAX_ROUNDS"`.
- `class PlanReviewLoop` with `__init__(self, max_rounds: int = 5)` that initialises `self.rounds: int = 0`, `self.max_rounds = max_rounds`, `self.prev_pushed_back: dict[str, list[str]] = {}` (keyed by slice id).
- `def extract_pushed_back(self, fixer_report: str) -> dict[str, list[str]]`: parses fixer_report for sections matching `## Pushed Back` header, then `### <slice-id>` sub-headers. If a sub-header contains only `(empty — slice approved this round)` → store empty list for that slice. Returns `{slice_id: [bullet_text, ...]}`.
  - Implementation: use `re.findall(r'### ([^\n]+)\n(.*?)(?=\n###|\n##|\Z)', pushed_back_body, re.DOTALL)` to extract slices.
- `def advance(self, fixer_report: str) -> str`: calls `extract_pushed_back`, compares to `self.prev_pushed_back`. If any slice has identical non-empty bullet list as previous round → return `VERDICT_BLOCKED_NON_PROGRESS`. If `self.rounds >= self.max_rounds` → return `VERDICT_BLOCKED_MAX_ROUNDS`. If all slices empty → return `VERDICT_APPROVED`. Else update `self.prev_pushed_back = current`, increment `self.rounds`, return `VERDICT_CONTINUE`.

→ verify: `python -c "from SOUL.tools.review_loop import PlanReviewLoop, VERDICT_APPROVED, VERDICT_BLOCKED_NON_PROGRESS; print('ok')"` — but because `SOUL/tools` has no `__init__.py`, use sys.path insert instead: `python -c "import sys; sys.path.insert(0, '.'); from SOUL.tools.review_loop import PlanReviewLoop; print('import ok')"`.

**Step 4.** Write inline unit tests in the `if __name__ == '__main__':` block of `SOUL/tools/review_loop.py` covering:

- Fixer report with `## Pushed Back\n### slice-1\n- bug A\n- bug B` twice in a row → second `advance()` call returns `VERDICT_BLOCKED_NON_PROGRESS`.
- Fixer report where all slices contain `(empty — slice approved this round)` → returns `VERDICT_APPROVED`.
- `max_rounds=2` with two CONTINUE rounds → third call returns `VERDICT_BLOCKED_MAX_ROUNDS`.
- depends on: step 3

→ verify: `python SOUL/tools/review_loop.py` exits 0 and prints `All tests passed.`

---

### Phase D — Verification Gate Patch (P0#3 cont.)

**Step 5.** Edit `SOUL/public/prompts/rationalization-immunity.md` — add a new section `## Pre-Load Rule` immediately after the `## Review Dismissal` section added in step 1:

```markdown
## Pre-Load Rule

**If you are about to read reviewer output** — stop. Load (read) this file first.
"If you have already read the findings, the rationalization has already formed. This section is useless to you now."
The correct sequence is: load `rationalization-immunity.md` → THEN read reviewer findings → THEN decide to fix or push back.
```

Also edit `.claude/skills/verification-gate/SKILL.md` — insert the following block immediately after the `# Verification Gate Protocol` heading (before the `IRON LAW` line):

```markdown
## Pre-Read Discipline

Before reading any reviewer output or review file:
1. Read `SOUL/public/prompts/rationalization-immunity.md` (specifically the "Review Dismissal" and "Pre-Load Rule" sections).
2. Only then open the review file.

Skipping step 1 means you have already formed rationalizations. The review is worthless.
```

- depends on: step 1

→ verify: `grep -n "Pre-Read Discipline" .claude/skills/verification-gate/SKILL.md` returns a line number.

---

### Phase E — Ensemble Reviewer (P0#6)

**Step 6.** Create `.claude/reviewers/workers.yaml` with the following content exactly (three example workers covering the two dispatch modes):

```yaml
# Atomic worker definitions
# Fields: name, provider, model, effort, dispatch_mode
# dispatch_mode: tool-use (worker reads files via Read tool) | bulk (files inlined into prompt)

workers:
  sonnet-tool:
    provider: anthropic
    model: claude-sonnet-4-5
    effort: medium
    dispatch_mode: tool-use

  opus-tool:
    provider: anthropic
    model: claude-opus-4-5
    effort: high
    dispatch_mode: tool-use

  sonnet-bulk:
    provider: anthropic
    model: claude-sonnet-4-5
    effort: medium
    dispatch_mode: bulk
```

→ verify: `python -c "import yaml; d=yaml.safe_load(open('.claude/reviewers/workers.yaml')); assert 'sonnet-tool' in d['workers']; print('workers.yaml ok')"` — if PyYAML not available, `python -c "import json"` is not applicable; fall back to: `grep -c 'dispatch_mode' .claude/reviewers/workers.yaml | grep -q 3 && echo ok`.

**Step 7.** Create `.claude/reviewers/reviewers.yaml` defining one ensemble that uses `sonnet-tool` × 2 with `opus-tool` as handler:

```yaml
# Ensemble reviewer definitions
# worker_count: how many parallel worker instances to spawn
# handler: which worker definition to use for synthesis step
# handler_prep: optional — run handler_prep worker before synthesis to summarise payload

reviewers:
  sonnet-x2-opus-handler:
    worker: sonnet-tool
    worker_count: 2
    handler: opus-tool
    handler_prep: null
```

→ verify: `grep "sonnet-x2-opus-handler" .claude/reviewers/reviewers.yaml` prints a match.

**Step 8.** Create `SOUL/tools/ensemble.py` with:

- `import asyncio, yaml, subprocess, json` from stdlib. Add `from pathlib import Path`.
- `WORKERS_PATH = Path(".claude/reviewers/workers.yaml")`, `REVIEWERS_PATH = Path(".claude/reviewers/reviewers.yaml")`.
- `def load_registry() -> tuple[dict, dict]`: reads both YAML files, returns `(workers_dict, reviewers_dict)`.
- `async def run_worker(worker_cfg: dict, payload: str, worker_index: int) -> dict`: mock implementation that returns `{"worker_index": worker_index, "verdict": "CONTINUE", "findings": [], "error": None}`. Add `# TODO: replace with actual Claude CLI subprocess call` comment. This is the integration boundary — the real CLI call depends on environment.
- `async def run_ensemble(reviewer_name: str, payload: str) -> dict`: loads registry, gets reviewer config, uses `asyncio.gather(*[run_worker(worker_cfg, payload, i) for i in range(worker_count)])` to fan out. Filters successes. If zero successes → returns `{"verdict": "DEGRADED_FATAL", "findings": [], "reason": "all workers failed"}`. Else passes surviving worker results to a `synthesize_handler()` call.
- `def synthesize_handler(worker_results: list[dict], handler_cfg: dict) -> dict`: stub that returns `{"verdict": "CONTINUE", "findings": [r["findings"] for r in worker_results]}` with `# TODO: invoke handler worker with consolidated findings` comment.
- `def write_review_to_disk(review: dict, output_path: Path) -> None`: writes `json.dumps(review, indent=2)` to `output_path`. Called by `run_ensemble` with path `.trash/reviews/<timestamp>-<reviewer_name>.json`.
- depends on: steps 6, 7

→ verify: `python -c "import sys; sys.path.insert(0,'.');import asyncio; from SOUL.tools.ensemble import run_ensemble; r=asyncio.run(run_ensemble('sonnet-x2-opus-handler','test payload')); assert r.get('verdict') != 'DEGRADED_FATAL'; print('ensemble ok')"`.

---

### Phase F — Plan DAG Validator (P0#4)

**Step 9.** Create `SOUL/tools/plan_dag.py` with:

- `class CycleError(Exception)`: stores `cycle: list[str]` (card ids in cycle order). `__str__` returns `"Cycle detected: " + " → ".join(self.cycle)`.
- `def build_dag(cards: list[dict]) -> dict[str, set[str]]`: accepts list of card dicts with keys `id` (str), `creates` (list[str] filenames), `modifies` (list[str] filenames), `reads` (list[str] filenames), `depends_on` (list[str] card ids). Returns adjacency dict `{card_id: set_of_predecessor_ids}`.
  - Explicit edges: from `card["depends_on"]`.
  - Implicit write-conflict edges: build a `file_last_writer: dict[str, str]` map sorted by card id numerically; for each card, any file in `creates ∪ modifies` that already has a prior writer → add implicit edge `card_id depends_on file_last_writer[file]`.
  - `reads:` entries never generate edges.
- `def extract_layers(dag: dict[str, set[str]]) -> list[list[str]]`: Kahn's algorithm. Returns list of layers (each layer = list of card ids that can run in parallel), sorted within each layer by card id (numeric sort). Raises `CycleError` with the specific cycle path if a cycle is detected. Cycle detection: after Kahn, any remaining nodes with in-degree > 0 form the cycle; extract via DFS back-edge on those nodes.
- `def validate_plan_file(plan_path: Path) -> list[list[str]]`: reads the plan markdown, extracts steps with `creates:` / `modifies:` / `reads:` / `depends on:` lines (regex: `^\s*-\s*(creates|modifies|reads):\s*(.+)$` and `^\s*depends on:\s*step (\d+)`), builds card dicts, calls `build_dag` + `extract_layers`, returns layers. Prints `"Plan is DAG-clean. Layers: <layers>"` or raises `CycleError`.
- `if __name__ == '__main__':` block: accepts `sys.argv[1]` as plan path, calls `validate_plan_file`.

→ verify: `python -c "import sys; sys.path.insert(0,'.'); from SOUL.tools.plan_dag import build_dag, extract_layers, CycleError; dag={'A':set(),'B':{'A'}}; layers=extract_layers(dag); assert layers==[['A'],['B']]; print('dag ok')"`.

**Step 10.** Add self-test in `SOUL/tools/plan_dag.py` `if __name__ == '__main__':` block (when called without args) covering:

- Linear dependency A→B→C → layers `[['A'], ['B'], ['C']]`.
- Write conflict: cards 1 and 2 both modify `foo.py`, no explicit dep → `build_dag` adds implicit edge 2→1 → layers `[['1'],['2']]`.
- Cycle A→B→A → `CycleError` raised.
- depends on: step 9

→ verify: `python SOUL/tools/plan_dag.py` (no args) exits 0 and prints `All DAG tests passed.`

---

### Phase G — Plan Template Update (P0#4 cont.)

**Step 11.** Edit `SOUL/public/prompts/plan_template.md` in the "Step Format Reference" section — replace the "Good" example block with an extended version that includes the three new fields. Find the existing "Good" example block:

```
1. Create `src/validators/email.py` with `validate_email(addr: str) -> bool`
   that checks RFC 5322 format using `re.fullmatch(EMAIL_PATTERN, addr)`
   → verify: python -c "from src.validators.email import validate_email; assert validate_email('a@b.com'); assert not validate_email('bad')"
```

Replace it with:

```
1. Create `src/validators/email.py` with `validate_email(addr: str) -> bool`
   that checks RFC 5322 format using `re.fullmatch(EMAIL_PATTERN, addr)`
   - creates: src/validators/email.py
   - reads: (none)
   - modifies: (none)
   → verify: python -c "from src.validators.email import validate_email; assert validate_email('a@b.com'); assert not validate_email('bad')"

2. Add route `/api/users` in `app/routes.py` that calls `validate_email`
   - creates: (none)
   - reads: src/validators/email.py
   - modifies: app/routes.py
   - depends on: step 1
   → verify: curl -X POST localhost:8000/api/users -d '{"email":"bad"}' | grep 400
```

Also add a paragraph after the "Step Requirements" bullet list:

```markdown
- **File change declarations required**: Every step that creates or modifies a file must include:
  - `- creates: <absolute/path>` for new files
  - `- modifies: <absolute/path>` for existing files being changed
  - `- reads: <absolute/path>` for files read but not changed (generates no DAG edge)
  Run `python SOUL/tools/plan_dag.py <plan.md>` after writing the plan to detect write conflicts and cycles.
```

- depends on: step 9

→ verify: `grep -n "creates:" SOUL/public/prompts/plan_template.md | head -5` returns at least 2 matches.

---

## Non-Goals

- P0#5 self-report tooling-bug loop (separate plan, ~6h)
- P1 one-pass regex substitution in `compiler.py`
- P1 exit-code failure taxonomy (`failures.py`)
- P1 numbered-list choice convention unification
- P1 `<!-- protected -->` marker in `backlog.md`
- P1 per-card atomicity extraction test / `plan_validator.py`
- P1 staleness check via `plan_start_hash` (`plan_staleness.py`)
- P1 worker model-as-name `workers.yaml` integration with `persona` skill
- P2 items (codeguide, VSCode color coding, Gemini bulk mode, forwarding wrapper, `@namespace:skill` convention)
- Actual Claude CLI subprocess integration in `ensemble.py` (stub only — integration requires owner to confirm CLI invocation syntax)
- `_phase/status.md` creation or population (the schema spec is written; phase guard wiring into existing skills is out of scope)

---

## Rollback

All new files created in this plan can be reverted individually:

```bash
# Remove new files
rm SOUL/public/prompts/phase_state.md
rm SOUL/tools/review_loop.py
rm SOUL/tools/ensemble.py
rm SOUL/tools/plan_dag.py
rm .claude/reviewers/workers.yaml
rm .claude/reviewers/reviewers.yaml

# Restore modified files from git
git checkout SOUL/public/prompts/rationalization-immunity.md
git checkout SOUL/public/prompts/plan_template.md
git checkout .claude/skills/verification-gate/SKILL.md
```

No existing data files are modified. No hooks are modified. No boot.md is modified. Full rollback in < 2 minutes.

---

## Phase Gates

--- PHASE GATE: Plan → Implement ---
[ ] Deliverable exists: this plan file at `docs/plans/2026-04-18-millhouse-impl.md`
[ ] Goal is one sentence and verifiable: yes (three capabilities enumerated above)
[ ] File Map complete: 9 files listed, all absolute paths resolvable from worktree root
[ ] No banned placeholder phrases: all steps have exact targets, exact regex/code, exact verify commands
[ ] ASSUMPTION gaps declared: 7 assumptions documented
[ ] Owner review: required — ensemble.py `run_worker` stub leaves Claude CLI integration open; owner must confirm dispatch_mode→CLI mapping before real fan-out works
