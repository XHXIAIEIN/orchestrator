---
name: adversarial-dev
description: "Adversarial Generator/Evaluator development loop. Use when a feature needs rigorous QA or self-review isn't catching bugs."
user_invocable: true
argument-hint: "<feature description or plan file>"
origin: "Orchestrator — earned through direct practice (see commit history)"
source_version: "2026-04-18"
---

# Adversarial Development

GAN-inspired development loop with structurally separated roles. The key insight: an agent reviewing its own code has a structural sycophancy problem. Adversarial separation fixes this.

**Source**: R47 Archon steal (adversarial-dev workflow). Proven in production.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  NEGOTIATOR  │ ──→ │  GENERATOR   │ ──→ │  EVALUATOR   │
│              │     │              │     │              │
│  Define      │     │  Build code  │     │  Attack code │
│  acceptance  │     │  to satisfy  │     │  Score 1-10  │
│  criteria    │     │  contract    │     │  per criterion│
└──────────────┘     └──────────────┘     └──────────────┘
       ↑                                        │
       │         ┌─── PASS (all ≥ 7) ──→ DONE  │
       │         │                              │
       └── FAIL ─┘── retry ≤ 3 ────────────────┘
```

## Protocol

### Phase 1: NEGOTIATE (define the contract)

1. Read the feature description from `$ARGUMENTS`
2. Read CLAUDE.md and relevant existing code
3. Define **5-15 specific, testable acceptance criteria**

Write contract to `.claude/adversarial/{feature-slug}/contract.json`:

```json
{
  "feature": "Feature Name",
  "criteria": [
    {
      "name": "short-kebab-name",
      "description": "Specific, testable description — what to verify and how",
      "threshold": 7
    }
  ]
}
```

**Rules for good criteria:**
- Each criterion must be independently verifiable (run a command, check output)
- No vague criteria ("code is clean") — only concrete ones ("no type errors in `tsc --noEmit`")
- Include edge cases the Generator might miss
- Include at least one criterion about error handling

### Phase 2: GENERATE (build the code)

Read the contract. Implement the feature.

**Generator rules:**
- Build defensively — anticipate Evaluator attacks
- One file at a time, type-check after each change
- Think about edge cases, input validation, error paths
- Run existing tests after each significant change
- Commit meaningful units: `feat({feature}): {description}`

When done, signal: `GENERATION_COMPLETE`

### Phase 3: EVALUATE (attack the code)

**Switch to Evaluator role.** You are now adversarial.

**Evaluator rules — CRITICAL:**
- **READ-ONLY**: Do NOT modify any source code. You are a judge, not a helper.
- **Run the code**: Execute tests, curl endpoints, try edge cases
- **Try to break it**: Invalid inputs, missing fields, race conditions, large payloads
- **Score honestly**: Your job is to find problems, not to be encouraging

Score each criterion 1-10:

| Score | Meaning |
|-------|---------|
| 9-10 | Exceptional — handles unmentioned edge cases |
| 7-8 | Solid — meets criterion as stated |
| 5-6 | Partial — fails some edge cases |
| 3-4 | Weak — major gaps |
| 1-2 | Broken — doesn't work |

**PASS threshold: ALL scores ≥ 7.** No curve grading. No "close enough."

Write feedback to `.claude/adversarial/{feature-slug}/feedback-round-{N}.json`:

```json
{
  "passed": false,
  "scores": {"criterion-name": 6, "another": 8},
  "feedback": [
    {
      "criterion": "criterion-name",
      "score": 6,
      "details": "Specific: file:line, exact error, reproduction command",
      "suggestion": "What to fix and why"
    }
  ],
  "overall": "What worked, what didn't, what must be fixed"
}
```

### Phase 4: ITERATE or COMPLETE

**If PASSED** (all scores ≥ 7):
- Output final report with scores
- Clean up: keep contract and final feedback, remove intermediate rounds

**If FAILED:**
- Check retry count. If retry ≥ 3: **STOP** with failure report
- Switch back to Generator role
- Read the feedback file — specifically what failed and why
- Fix ONLY the failing criteria (don't touch passing code)
- Type-check, test, commit
- Switch back to Evaluator role for re-evaluation

## State Management

Uses [Disk State Loop](SOUL/public/prompts/disk_state_loop.md) pattern.

State file: `.claude/adversarial/{feature-slug}/state.json`
```json
{
  "phase": "negotiating|generating|evaluating|complete|failed",
  "retry": 0,
  "max_retries": 3,
  "pass_threshold": 7,
  "status": "running"
}
```

## Anti-Patterns

| Don't | Why | Do Instead |
|-------|-----|-----------|
| Evaluator modifies code | Defeats adversarial separation | Evaluator writes feedback, Generator fixes |
| "Good enough" scoring | Defeats the purpose | Hard 7/10 threshold, no exceptions |
| Generator reads feedback before generating | Biases initial implementation | Generate first, evaluate after |
| Skip criteria definition | No objective measure of quality | Always negotiate contract first |
| Evaluate your own code charitably | Structural sycophancy | Actively try to break it |

## When NOT to Use

- Simple bug fixes (overkill)
- Documentation changes (no code to evaluate)
- Tasks with < 3 acceptance criteria (use regular review instead)
- Exploratory/prototyping work (adversarial tension slows exploration)

## Integration

Call from other skills or directly:
```
/adversarial-dev implement user authentication with OAuth2
```

For complex features, combine with `/prime` first:
```
/prime governance
/adversarial-dev add retry logic to executor with exponential backoff
```
