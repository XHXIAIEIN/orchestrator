---
name: verification-spec
description: "Use at task start, before the first write or destructive command, when the owner hands over a code, build, test, deploy, or UI request. Forces upfront success criteria, the proof command, and the working assumptions."
origin: "Orchestrator — split from verification-gate (2026-04-26)"
source_version: "2026-04-26"
---

# Verification Spec — Pre-Task Gate

```
IRON LAW: NO IMPLEMENTATION WITHOUT A VERIFIABLE SUCCESS CRITERION. Vague goals produce unverifiable work.
```

Anthropic's best practices flag verification as the single highest-leverage step. The leverage comes from stating the criterion **before** writing code — post-hoc checks catch broken code, not broken premises. Run this gate before the first write, run, install, or destructive call. Pair with `verification-check` at the end of the same task.

## When to invoke

Trigger when the owner hands over any of:
- A code change, refactor, or new feature
- A build, test, lint, or typecheck task
- A deploy, schema migration, or config change
- A UI / frontend change
- A bug fix (the goal is the failing test that flips green)

Skip only for trivial read-only ops (ls, grep, git status, single-line typo with no behavioral effect).

## The Three Steps

### Step 1: GOAL — State success in verifiable terms

Convert the request into one sentence the owner can diff against reality.

- Bad: "fix the bug" / "make auth work" / "improve performance"
- Good: "User submits /signup with empty email field and sees an inline `Email required` error"
- Good: "`pytest tests/auth/test_login.py` exits 0 with 12 passed, 0 failed"
- Good: "`dist/main.js` after gzip is under 200 KB"

If you cannot write the goal as a verifiable claim, you do not understand the task. Ask the owner one clarifying question, do not guess.

### Step 2: COMMAND — Pick the proof command

What single command (or smallest sequence) proves the goal?

- Tests → exact suite/file path: `pytest tests/foo/test_bar.py::test_baz -v`
- Build → exact invocation: `pnpm build && ls -lh dist/main.js`
- Lint/typecheck → exact checker: `ruff check src/ && mypy src/`
- Manual → exact URL + observable: `curl localhost:3000/api/health → expect 200 + body "ok"`

If the command does not exist yet, the first sub-task is to write it (TDD). State that explicitly.

### Step 3: ASSUMPTIONS — Declare premises out loud

State each assumption on its own line. Verifiable claims, not approval requests — the owner can intercept a wrong premise in two seconds instead of debugging a wrong implementation for an hour.

- Format: `Assume: <X is Y>` / `Assume: <user wants A, not B>` / `Assume: <this file is the entry point>`
- If two plausible interpretations exist, list both, pick one with a reason, proceed
- Do not stall waiting for confirmation — announce, execute, let the owner overrule

## Output Format

Before the first write or destructive command, emit this block verbatim:

```
Goal: <one verifiable claim>
Verify: <exact command or manual check>
Assume: <premise 1>
Assume: <premise 2>          # add lines as needed; omit if no non-obvious premise
```

Then proceed with implementation. Do not narrate the gate — emit the block, move on.

## Common Failure Modes

| Anti-pattern | Fix |
|---|---|
| `Goal: improve auth` | Specify which behavior changes for which input |
| `Verify: it works` | Name a command. "It works" is not a command. |
| `Assume: standard setup` | Name the actual file, version, or config |
| Skipping because "task is obvious" | Obvious tasks have non-obvious failure modes. The spec costs 30 seconds. |
| Spec block buried in prose | Emit it as a fenced block on its own — readable at a glance |

## Boundaries

Apply to: code edit, build run, test run, install, deploy, schema change, config change, UI change.

Skip for: read-only exploration (Glob/Grep/Read with no follow-up changes), pure Q&A (nothing to verify), owner-led planning sessions (plans verify during execution).

## Pairs With

- `verification-check` — runs the proof command after implementation, confirms the goal landed
- `Goal-Driven Execution` (CLAUDE.md) — converts vague tasks into testable goals
- `plan_template.md` — multi-step plans embed per-step verify commands generated from this gate
