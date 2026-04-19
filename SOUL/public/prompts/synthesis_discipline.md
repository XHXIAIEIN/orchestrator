<!-- TL;DR: Synthesize across sources; never just concatenate; surface contradictions. -->
# Synthesis Discipline

> **Who consults this**: Any coordinator agent before dispatching implementation sub-tasks.
> **When**: After research/investigation is complete, before spawning or continuing with an executor.

---

## Identity

A coordinator must understand research results before delegating implementation.
Dispatching without synthesis is delegation theater — forwarding, not coordinating.

## How It Works

Before dispatching any sub-task, the coordinator demonstrates synthesis by providing 4 specifics:

1. **File paths** — not "the relevant files", but `src/governance/dispatcher.py:L162`
2. **Exact changes** — not "fix the bug", but "replace the `if` guard on line 42 with a null check"
3. **Function/class names** — not "update the handler", but "modify `TaskDispatcher.dispatch_task()`"
4. **Purpose statement** — one sentence: why this sub-task exists and what it unblocks

## Banned Phrases

These phrases indicate the coordinator has NOT synthesized the research. If a dispatch contains any of these, it is vague — add specific targets before sending:

- "Based on your findings..."
- "Implement the changes"
- "Fix the issues found"
- "Apply the necessary modifications"
- "Update as needed"
- "Handle the edge cases"
- "Make it work"

## Continue vs Spawn Decision Matrix

| Condition | Decision | Reason |
|---|---|---|
| Sub-task needs > 80% of current context | Continue | Context transfer cost exceeds spawn benefit |
| Sub-task is independent, < 20% context overlap | Spawn | Clean slate avoids context pollution |
| Sub-task modifies files the coordinator just read | Continue | Coordinator already has the mental model |
| Sub-task is in a different project/cwd | Spawn | Separate working directory, separate agent |
| Research complete, implementation clear | Spawn | Coordinator synthesized; executor runs from spec |
| Research incomplete, needs exploration | Continue | Don't spawn an agent to wander |

## Dispatch Quality Gate

Before every dispatch, verify all 4:

1. Does the spec contain at least 1 concrete file path with line range?
2. Does the spec name at least 1 function, class, or config key to change?
3. Is there a 1-sentence purpose statement?
4. Would a developer reading this spec know exactly what to do without asking questions?

If any answer is NO, the dispatch is not ready. Synthesize further.

## Dispatch Spec Template

```markdown
## Sub-task: <1-line title>

**Purpose**: <1 sentence — why this exists and what it unblocks>

**Target files**:
- `<absolute/path/to/file.py>:L<start>-L<end>` — <intent>
- `<absolute/path/to/file.py>:L<start>-L<end>` — <intent>

**Changes**:
1. In `<FunctionOrClass>`, <exact change description>
2. In `<FunctionOrClass>`, <exact change description>

**Verification**: <command or check that confirms the sub-task is complete>

**Dependencies**: <what must be done before this, or "none">
```

## Anti-Pattern: The Forwarding Coordinator

```
BAD:  "Scout found issues in the auth module. Fix them."

GOOD: "Scout found that `src/auth/token.py:validate()` (L45-52) silently swallows
       ExpiredTokenError instead of propagating it. Change the bare `except` on L48
       to `except ExpiredTokenError as e: raise AuthError('token expired') from e`.
       This unblocks the retry logic in `src/gateway/retry.py:L30`."
```

The coordinator's job is compression + specificity. If you cannot be specific, you have not understood the problem yet.

## Output Format

N/A — reference document. Coordinators consult this before dispatch; it defines the spec format (see template above) but does not produce standalone output.

## Boundaries

1. **Stop dispatching** if the Dispatch Quality Gate fails on any of the 4 checks — go back and read more code.
2. **Stop and ask the user** if research reveals the task scope is 3x larger than originally described — re-scope before spawning executors.
3. Never dispatch with banned phrases. If you catch yourself writing one, it means you skipped synthesis.
