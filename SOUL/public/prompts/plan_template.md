<!-- TL;DR: All plans need Goal+FileMap+AtomicSteps+PhaseGates before first line of code. -->
# Plan Template

## Identity

This template defines the structure for all Orchestrator implementation plans. Every multi-step task must produce a plan in this format before code is written.

## How You Work

### Plan Structure

```markdown
---
phase: plan
status: draft
verdict: null
evidence_strength: null
overridden: false
override_reason: null
gaps: []
---
# Plan: {title}

## Goal
{One sentence, verifiable — what does "done" look like?}

## File Map
- `{absolute/path/to/file.py}` — Create | Modify | Delete

## Steps
1. {Action verb} {specific target} → verify: {exact command}
2. {Action verb} {specific target} → verify: {exact command}
   - depends on: step 1
```

### No Placeholder Iron Rule

The following phrases are banned in plan steps. Each must be replaced with specifics:

| Banned Phrase | Replace With |
|---|---|
| "implement the logic" | Exact logic: "Add null check for `user.email`, return 400 if missing" |
| "add appropriate error handling" | Named errors: "Catch `ConnectionError`, retry 3x with 1s backoff, then raise `ServiceUnavailable`" |
| "update as needed" | Exhaustive list: "Update `config.yaml` key `db.host` from localhost to `${DB_HOST}`" |
| "etc." / "and so on" | Full enumeration of every item |
| "similar to X" | Write out the actual steps, even if repetitive |
| "refactor" (alone) | Specific transform: "Extract lines 42-78 into `validate_input()`, call from `handle_request()`" |
| "clean up" (alone) | Specific items: "Remove unused import `os` on line 3, delete empty `__init__.py` in `utils/`" |
| "optimize" (alone) | Specific change: "Replace O(n^2) nested loop in `search()` with dict lookup, expected O(n)" |

### Step Requirements

- Each step: 2-5 minutes of work, starts with an action verb, has an explicit verify command.
- Dependencies declared explicitly: `depends on: step N`. Implicit ordering is not allowed.
- File paths are absolute. "that config file" is not a valid target.
- **File change declarations required**: Every step that creates or modifies a file must include:
  - `- creates: <absolute/path>` for new files
  - `- modifies: <absolute/path>` for existing files being changed
  - `- reads: <absolute/path>` for files read but not changed (generates no DAG edge)
  Run `python SOUL/tools/plan_dag.py <plan.md>` after writing the plan to detect write conflicts and cycles.
- **Last step of every plan with ≥5 steps MUST be**: `Dispatch verify-subagent with verify_sop.md → verify: agent response contains 'VERDICT: PASS'`

### Step Format Reference

Good:
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

Bad:
```
1. Add email validation logic
   → verify: test it
```

### Dependency Declaration

```
3. Add route `/api/users` in `app.py` calling `validate_email` from step 1
   - depends on: step 1
   → verify: curl -X POST localhost:8000/api/users -d '{"email":"bad"}' | grep 400
```

## Phase Gates

For multi-phase work (Spec, Plan, Implement, Verify), each phase boundary requires a gate check before proceeding. Insert a gate block between phases:

```
--- PHASE GATE: {phase name} → {next phase} ---
[ ] Deliverable exists: {specific artifact — spec doc, plan file, passing tests}
[ ] Acceptance criteria met: {each criterion with evidence}
[ ] No open questions: {all ambiguities resolved, or explicitly deferred with rationale}
[ ] Owner review: {required | not required — if required, STOP and wait}
```

### Gate Rules

1. **No implicit phase transitions.** Moving from planning to implementation without a gate check is a protocol violation.
2. **"Owner review: required" means STOP.** Do not proceed until the owner explicitly approves.
3. **Deferred questions must be logged** as `ASSUMPTION: {question} — {rationale}` in the plan.
4. **Gate evidence must be concrete.** "Spec looks complete" is not evidence. "Spec covers 3 endpoints, 2 error cases, 1 auth flow — all with request/response examples" is evidence.

### Default Gate Configuration

| Transition | Owner Review Required? |
|---|---|
| Spec → Plan | Yes (scope confirmation) |
| Plan → Implement | No (plan IS the approval) |
| Implement → Verify | No (automatic) |
| Verify → Ship/Commit | No (evidence-based) |

Override: If the user says "just do it" or grants blanket approval, all gates become automatic (still logged, but no STOP).

### Gate Checklist Per Transition

**Gate 1: Spec → Plan** (before writing any plan steps)
- [ ] Goal is one sentence and verifiable (not "improve X")
- [ ] File Map is complete (every file to be touched is listed)
- [ ] Ambiguities resolved (if spec says "add auth" but not which type → ASK)
- [ ] Scope confirmed (nothing in File Map the user did not request)
- [ ] Simplicity pre-check: describe the simplest possible implementation in 1-2 sentences. If your plan exceeds this by >2x LOC or >2x files, justify why in the plan header

**Gate 2: Plan → Implement** (before writing any code)
- [ ] Every step has action verb + specific target + verify command
- [ ] No banned placeholder phrases (check against Iron Rule table)
- [ ] Dependencies are explicit
- [ ] Steps are 2-5 min each (split anything bigger)
- [ ] Owner has seen the plan (unless task is reversible and under 30 min total)

**Gate 3: Implement → Done** (before declaring completion)
- [ ] Every step's verify command has been run and passed
- [ ] No unrelated changes in `git diff`
- [ ] Orphaned imports/vars from your changes are cleaned up
- [ ] If tests exist, they pass
- [ ] Verify-subagent dispatched and returned `VERDICT: PASS` (required for plans ≥ 5 steps)

## Quality Bar

- Goal must be falsifiable: "improve performance" fails; "reduce p95 latency from 200ms to under 100ms" passes.
- File Map must list every file before the first step is written. Files discovered mid-plan require a File Map update.
- Total plan length: 5-30 steps. Under 5 for a multi-step task = too coarse. Over 30 = split into sub-plans.
- Every step's verify command must be copy-pasteable — no pseudocode, no "check the output".

## Boundaries

- **STOP and ask the user** if the plan exceeds 30 steps — the task should be split into sub-plans with separate ownership.
- **STOP and ask the user** if the File Map includes files outside the project root — cross-project changes need explicit scope approval.
- Never skip a phase gate, even for "trivial" changes. Logging "Gate passed: all criteria met" takes 5 seconds; recovering from a skipped gate takes hours.
- A plan with any banned placeholder phrase is incomplete and must not proceed to implementation.

> Section headings above are starting points. Rename, reorder, or add sections to match how the content actually unfolded.

## Phase Gate Contract Document

When a plan crosses a phase boundary (Spec → Plan, Plan → Implement, Implement → Verify, or any custom phase), the transitioning agent **must** produce a contract file before the next phase begins.

### Contract File Convention

- Path: `.phase-gate/<from-phase>-to-<to-phase>.md` (relative to project root)
- Example: `.phase-gate/plan-to-implement.md`
- Created by: the agent completing the **outgoing** phase
- Read by: the agent starting the **incoming** phase (mandatory, not optional)

### Contract File Template

```markdown
# Phase Gate: {from} → {to}

**Date**: {YYYY-MM-DD}
**Plan reference**: {path/to/plan.md}

## Assumptions
<!-- List every assumption made in {from} phase that the {to} phase will rely on -->
- [ ] {Assumption 1}
- [ ] {Assumption 2}

## Interface Contracts
<!-- APIs, file formats, data shapes, environment variables agreed upon -->
| Name | Type | Value / Shape | Owner |
|------|------|---------------|-------|
| {interface} | {api\|file\|env\|type} | {description} | {who produces it} |

## Verification Points
<!-- How does the {to} phase know it succeeded? -->
- [ ] {Criterion 1} → checked by: {command or manual step}
- [ ] {Criterion 2} → checked by: {command or manual step}

## Open Questions
<!-- Unresolved items deferred to {to} phase — must be resolved before phase ends -->
- [ ] {Question} — assigned to: {owner\|agent}
```

### Gate Rules

1. **No contract = no phase transition.** If the contract file does not exist at the start of the incoming phase, create it before writing any code or making any decisions.
2. **Contract conflicts with plan = STOP.** If the contract contradicts the current plan, surface the conflict to the owner before proceeding.
3. **Contract is a living document** during the phase — update it when assumptions are validated or invalidated. Mark resolved items with `[x]`.
