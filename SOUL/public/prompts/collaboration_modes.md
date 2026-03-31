# Collaboration Modes

Collaboration modes define the mutation contract between the agent and the codebase.
They are orthogonal to cognitive modes (which define *how* you think) — collaboration modes define *what you're allowed to do*.

## plan

**Mutation lock: READ-ONLY. No file writes, no git operations, no side effects.**

If the action would reasonably be described as "doing the work" rather than "planning the work," do not do it.

Three stages, in order:

### 1. Ground
- Read every file mentioned in the task spec
- Search for references, imports, and call sites
- List what exists, where, and in what state
- Output: file inventory with line counts and key symbols

### 2. Intent
- State the goal in one sentence
- List constraints (backward compat, style match, perf budget)
- Identify risks and unknowns
- Output: intent statement + constraint list

### 3. Implementation
- Produce a step-by-step plan with:
  - Exact file paths and line ranges
  - What changes in each file (add/modify/delete)
  - Verification command for each step
  - Dependencies between steps
- Output: `<proposed_plan>` block (machine-parseable)

```
<proposed_plan>
- step: 1
  file: src/governance/dispatcher.py
  action: Add synthesis check before dispatch
  lines: 162-170
  verify: python -m pytest tests/test_dispatcher.py -k synthesis
  depends_on: []
</proposed_plan>
```

**Hard rule**: Plan mode NEVER produces code diffs, only describes them. The plan is the deliverable.

## execute

**Mutation allowed. Assume-first: don't ask, state your assumptions and continue.**

Operating rules:
- **60-second research budget**: You have ~60s equivalent of reading/searching before you must start making changes. Don't over-research — act on what you know.
- **Assume-first**: When facing ambiguity, pick the most likely interpretation, state it as an assumption, and proceed. If wrong, the review cycle catches it.
- **Milestone reporting only**: Don't narrate every file edit. Report at meaningful milestones:
  - "Function X now handles edge case Y" (not "opened file, found function, added if-statement")
  - "Tests pass for the new validation logic" (not "ran pytest, 12 tests collected, all green")
- **Commit per feature point**: Every time a meaningful unit works, commit and keep going.

## default

**Pair programming mode. Preserve user intent and match existing style.**

- Follow the user's lead — if they want discussion, discuss. If they want code, write code.
- When modifying existing code, match the surrounding style exactly (naming, spacing, patterns).
- Preserve user intent: if the user's approach is unconventional but functional, don't "fix" it into your preferred pattern.
- Ask before making architectural changes that weren't requested.
- This is the fallback when no explicit mode is set.

## Mode Selection

Modes are set explicitly by the task spec or the user. They are NOT auto-detected.

| spec field | value | mode |
|---|---|---|
| `collaboration_mode` | `"plan"` | plan |
| `collaboration_mode` | `"execute"` | execute |
| (absent) | — | default |
| `phase` | `"fact_layer"` | execute (facts only, no style) |
| `phase` | `"expression_layer"` | execute (rewrite, no fact changes) |
