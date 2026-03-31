# Synthesis Discipline

A coordinator MUST understand research results before delegating implementation.
Dispatching without synthesis is delegation theater — you're not coordinating, you're forwarding.

## The Rule

Before dispatching any sub-task, the coordinator must demonstrate synthesis:
1. **Specific file paths** — not "the relevant files", but `src/governance/dispatcher.py:L162`
2. **Exact changes** — not "fix the bug", but "replace the `if` guard on line 42 with a null check"
3. **Function/class names** — not "update the handler", but "modify `TaskDispatcher.dispatch_task()`"
4. **Purpose statement** — one sentence: why this sub-task exists and what it unblocks

## Banned Phrases

These phrases indicate the coordinator has NOT synthesized the research:

- "Based on your findings..."
- "Implement the changes"
- "Fix the issues found"
- "Apply the necessary modifications"
- "Update as needed"
- "Handle the edge cases"
- "Make it work"

If a dispatch contains any of these, it is vague. Add specific targets before sending.

## Continue vs Spawn Decision Matrix

| Condition | Decision | Reason |
|---|---|---|
| Sub-task needs >80% of current context | **Continue** | Context transfer cost exceeds spawn benefit |
| Sub-task is independent, <20% context overlap | **Spawn** | Clean slate avoids context pollution |
| Sub-task modifies files the coordinator just read | **Continue** | Coordinator already has the mental model |
| Sub-task is in a different project/cwd | **Spawn** | Separate working directory, separate agent |
| Research phase complete, implementation clear | **Spawn** | Coordinator synthesized, executor can run blind |
| Research incomplete, needs exploration | **Continue** | Don't spawn an agent to wander |

## Dispatch Quality Gate

Before every dispatch, verify:
1. Does the spec contain at least one concrete file path?
2. Does the spec name at least one function, class, or config key to change?
3. Is there a one-sentence purpose statement?
4. Would a developer reading this spec know exactly what to do without asking questions?

If any answer is NO, the dispatch is not ready. Synthesize further.

## Anti-Pattern: The Forwarding Coordinator

```
BAD:  "Scout found issues in the auth module. Fix them."
GOOD: "Scout found that `src/auth/token.py:validate()` (L45-52) silently swallows
       ExpiredTokenError instead of propagating it. Change the bare `except` on L48
       to `except ExpiredTokenError as e: raise AuthError('token expired') from e`.
       This unblocks the retry logic in `src/gateway/retry.py:L30`."
```

The coordinator's job is compression + specificity. If you can't be specific, you haven't understood the problem yet.
