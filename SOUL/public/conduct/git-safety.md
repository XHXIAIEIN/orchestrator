# Conduct: Git Safety

- **Stage first, push later**: `commit` and `push` are two separate steps. Don't auto-push.
- Prefer working on a local branch rather than committing directly to main/master.
- **Steal work requires `[STEAL]` tag + dedicated worktree**: When dispatching agents for steal/偷师 tasks, the agent prompt MUST include `[STEAL]` at the start. The dispatch-gate hook blocks `[STEAL]` work unless `git branch --show-current` returns a `steal/*` or `round/*` branch. **Create a worktree, not a branch in the main repo** — `git checkout -b steal/<topic>` on the main workspace is forbidden (it hijacks the caller's branch). Correct setup: `git worktree add .claude/worktrees/steal-<topic> -b steal/<topic> && cd .claude/worktrees/steal-<topic>`. For sub-agent dispatch, also pass `isolation: "worktree"` in the Agent tool call. Full rules: `.claude/skills/steal/constraints/worktree-isolation.md`.
- **Rollback is a no-go zone**: When stuck on a bug, diagnose with `git diff` and targeted fixes — these preserve all uncommitted work. Rollback commands (`git reset --hard`, `git checkout -- .`, `git restore .`, `git clean -f`) are only allowed when the owner explicitly says "roll back" or "reset". If a rollback is requested, backup first (`git stash` or `git diff > backup.patch`), report backup location, then execute.

<!-- source: CLAUDE.md §Git Safety (inside <critical>), extracted 2026-04-18 -->
