# Evaluator-Fix Loop Protocol

Source: yoyo-evolve self-evolving-agent (Round 28 steal)

When completing a non-trivial implementation, use an independent evaluator to review the diff. If the evaluator finds issues, fix them and re-evaluate. Maximum rounds prevent infinite loops.

## Workflow

```
Implementation Agent completes work
        ↓
Evaluator Agent reviews diff (independent — no shared context with implementer)
        ↓
    ┌─ PASS → Done
    └─ FAIL → feedback to Implementation Agent
                ↓
          Fix issues based on feedback
                ↓
          Re-evaluate (back to Evaluator)
                ↓
          Max {MAX_ROUNDS} rounds, then escalate to human
```

## Evaluator Prompt Template

```
You are an independent code evaluator. You did NOT write this code. You have no bias toward it.

Review the following diff against these criteria:

1. **Correctness**: Does the code do what the task description says? Any logic errors?
2. **Safety**: SQL injection, XSS, command injection, secrets in code, unsafe deserialization?
3. **Completeness**: Are there TODO/FIXME/HACK markers? Incomplete error handling? Missing edge cases?
4. **Style**: Does it match the surrounding code style? Any unnecessary changes?
5. **Tests**: If tests were expected, do they exist? Do they cover the changed behavior?

[Task Description]
{task_description}

[Diff]
{diff}

Output format — you MUST use exactly one of:

Verdict: PASS
Reason: {1-sentence summary of why it's acceptable}

OR

Verdict: FAIL
Issues:
- [severity:HIGH/MED] {file}:{line} — {description}
- [severity:HIGH/MED] {file}:{line} — {description}
Fix guidance: {1-2 sentences on what to fix first}
```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| MAX_ROUNDS | 3 | Maximum fix→evaluate cycles before escalating |
| EVALUATOR_MODEL | same as implementer | Can use different model for diversity |
| SEVERITY_THRESHOLD | HIGH | Only FAIL on HIGH issues; MED = warning only |

## Integration Points

- **Governor task execution**: After `execute_task()`, spawn evaluator on the diff
- **Code-review agent**: Use this protocol as the review loop
- **PR creation**: Run evaluator before opening PR

## Anti-Patterns

- **Self-review**: The same agent that wrote the code should NOT evaluate it
- **Context bleeding**: Evaluator should see ONLY the diff + task description, not the full conversation
- **Infinite loop**: Always cap rounds. If still failing at max, the issue is likely in the task spec, not the code
