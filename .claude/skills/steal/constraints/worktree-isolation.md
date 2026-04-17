# Layer 0: Worktree Isolation — Never Touch the Caller's Branch

**Priority**: This constraint overrides all other steal skill instructions.

## Rule

Steal work MUST run in a dedicated `git worktree` on a `steal/*` branch.
The main workspace's branch, index, and uncommitted changes MUST remain untouched.

`git checkout -b steal/<topic>` in the main repo is **banned** during steal work.
It hijacks whatever branch the owner was on (e.g., `main`, `docs/xxx`, a feature branch)
and strands their in-progress changes. This has happened repeatedly — it is the single
most common pollution vector of the steal skill.

## Correct Pattern

```
git worktree add .claude/worktrees/steal-<topic> -b steal/<topic>
cd .claude/worktrees/steal-<topic>
# ... all steal work: clone target, analyze, write report, commit ...
cd <back to main repo root>
git worktree remove .claude/worktrees/steal-<topic>
```

`.claude/worktrees/` is already gitignored.

## Sub-Agent Dispatch

When dispatching a sub-agent for steal work, pass `isolation: "worktree"` in the
Agent tool call. Do NOT brief the agent to "create a steal branch" — that would
reproduce the same pollution inside the worktree.

## Violation indicators

- `git checkout` or `git switch` with a `-b steal/*` flag issued from the main repo root
- Agent prompt contains `[STEAL]` but the current `pwd` is the main repo top-level
- Steal report files created outside any worktree (check `git rev-parse --show-toplevel`
  against `.claude/worktrees/` prefix)
- Post-steal: `git branch --show-current` in the main repo returns `steal/*` (means
  the main workspace got hijacked and never restored)

## Enforcement

If you detect any violation mid-task, STOP immediately. Do not try to "fix" by
switching back — you may have uncommitted changes that need preserving first.
Report the violation and ask the owner how to proceed.

The `dispatch-gate.sh` hook enforces this at the tool-call layer: `[STEAL]` tagged
agent dispatches are blocked unless `git branch --show-current` returns a `steal/*`
or `round/*` branch. Being inside a worktree on `steal/<topic>` satisfies this
naturally; switching the main repo's branch satisfies it destructively. Only the
former is acceptable.
