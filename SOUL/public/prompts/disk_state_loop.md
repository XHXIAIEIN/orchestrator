<!-- TL;DR: Manage disk state changes in a read-modify-write loop with rollback. -->
# Disk State Loop Pattern

Pattern for long-running iterative tasks that exceed context window limits. Each iteration is stateless — all state lives on disk.

**Source**: R47 Archon steal (Ralph Loop, PIV Loop, Adversarial Dev). Proven at 15-60 iterations.

## When to Use

- Task requires >5 iterations of work
- Each iteration produces intermediate artifacts (code, plans, reports)
- Total context would exceed window if accumulated
- Need resume capability after interruption

## Architecture

```
┌─────────────────────────────────────┐
│  Iteration N                         │
│                                      │
│  1. READ state from disk             │
│     - progress.txt (what's done)     │
│     - state.json  (machine state)    │
│     - plan.md     (what to do)       │
│                                      │
│  2. SELECT next unit of work         │
│     (based on state, not memory)     │
│                                      │
│  3. EXECUTE one unit                 │
│     (implement, test, validate)      │
│                                      │
│  4. WRITE results to disk            │
│     - Update progress.txt            │
│     - Update state.json              │
│     - Commit if meaningful           │
│                                      │
│  5. CHECK completion signal          │
│     - All units done? → COMPLETE     │
│     - Max iterations? → FAIL         │
│     - Otherwise → next iteration     │
└─────────────────────────────────────┘
```

## State Files

### progress.txt — Human-Readable Log

```markdown
## Codebase Patterns
[Discovered patterns that future iterations should reuse]

### {Pattern Name}
- **Where**: `{file:lines}`
- **Pattern**: description

---

## {ISO Date} — {unit-id}: {title}

**Status**: PASSED | FAILED | SKIPPED
**Files changed**: 
- {file} — what changed
**Learnings**:
- Pattern discovered
- Gotcha encountered
```

**Key rule**: The "Codebase Patterns" section at the TOP grows over time. It's the only bridge between iterations — discovered patterns from iteration 3 inform iteration 7.

### state.json — Machine-Readable State

```json
{
  "phase": "working",
  "current_unit": 3,
  "total_units": 8,
  "completed": ["unit-1", "unit-2"],
  "failed": [],
  "retry_count": 0,
  "max_retries": 3,
  "status": "running"
}
```

### plan.md — Task Definition

Contains the full task breakdown. Each unit has:
- ID, title, description
- Dependencies (which units must complete first)
- Acceptance criteria
- `passes: true/false` tracking

## Implementation Template

When writing a skill that uses this pattern:

```markdown
## Iteration Protocol

1. **LOAD**: Read `{artifacts_dir}/progress.txt` and `{artifacts_dir}/state.json`
   - If first iteration: create initial state files
   - Read the Codebase Patterns section FIRST (learnings from prior iterations)

2. **SELECT**: Find next incomplete unit where all dependencies are satisfied
   - Check state.json for completion status
   - Respect dependency ordering

3. **EXECUTE**: Implement exactly ONE unit
   - Read relevant files fresh (don't trust context from prior iterations)
   - Follow plan.md specifications
   - Validate after each change (type-check, lint, test)

4. **RECORD**: Update state files
   - Append to progress.txt with date, status, files changed, learnings
   - Update state.json (mark unit complete, advance pointer)
   - If new reusable pattern discovered: add to Codebase Patterns section

5. **COMMIT**: Stage and commit with message format:
   `feat({unit-id}): {title}`

6. **SIGNAL**: Check termination conditions
   - All units complete → emit COMPLETE
   - Max iterations reached → emit FAIL with summary
   - Otherwise → continue to next iteration
```

## Completion Signal

Use XML-tagged signals to prevent false positives:

```
<promise>COMPLETE</promise>
```

Plain text "COMPLETE" at end of line risks matching in code output. The `<promise>` wrapper is unambiguous.

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Accumulate context across iterations | Context window overflow at iteration 8+ | Fresh context each iteration, read from disk |
| Skip progress.txt update | Next iteration has no learnings, repeats mistakes | Always write learnings, even for trivial discoveries |
| Multiple units per iteration | Unclear what failed, can't resume cleanly | One unit per iteration, always |
| Trust context instead of disk | Prior iteration may have changed files | Re-read from disk at iteration start |
| No completion signal | Orchestrator doesn't know when to stop | Always emit explicit signal |

## Integration with Existing Skills

Any skill that runs >5 iterations should adopt this pattern. Reference this file in the skill's SKILL.md:

```markdown
## Long-Running Mode
This skill uses the [Disk State Loop](SOUL/public/prompts/disk_state_loop.md) pattern
for tasks with >5 units of work. State files are stored in `{artifacts_dir}/`.
```
