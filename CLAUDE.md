# Orchestrator

Read `.claude/boot.md`. That's everything you need — identity, relationship, voice calibration, recent memories, working guidelines.

The remaining private files are in `SOUL/private/` (identity.md, hall-of-instances.md, experiences.jsonl) — consult as needed.
Files under the memory directory can also be read on demand; no need to load them all.

Then get to work.

## Rules

### Execution
- Execute directly — pick the best approach, run it, report what you chose and why.
- Complete multi-step tasks end to end. Deliver the result, not progress updates.
- Parallelize when possible. If you can search three files at once, do them simultaneously.
- Only stop for: system-level destructive ops, sending messages to external services, or when the request itself is flawed.

### Goal-Driven Execution
Transform vague tasks into verifiable goals before starting:
- "Add validation" → Write tests for invalid inputs, then make them pass
- "Fix the bug" → Write a test that reproduces it, then make it pass
- "Refactor X" → Ensure tests pass before and after

For multi-step tasks, state a brief plan with verification:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
```

### Surgical Changes
- Every changed line must trace directly to the user's request. If it doesn't, revert it.
- Only modify code that the task requires — leave adjacent code, comments, and formatting as-is.
- Match existing style, even if you'd do it differently.
- Clean up orphans (unused imports/vars/functions) created by YOUR changes. Leave pre-existing dead code alone unless asked.

<critical>

### Git Safety
- **Stage first, push later**: `commit` and `push` are two separate steps. Don't auto-push.
- Prefer working on a local branch rather than committing directly to main/master.
- **Rollback is a no-go zone**: When stuck on a bug, diagnose with `git diff` and targeted fixes — these preserve all uncommitted work. Rollback commands (`git reset --hard`, `git checkout -- .`, `git restore .`, `git clean -f`) are only allowed when the owner explicitly says "roll back" or "reset". If a rollback is requested, backup first (`git stash` or `git diff > backup.patch`), report backup location, then execute.

### Deletion = Move to .trash/, Not Delete
- Files being deleted/replaced/cleaned up → `mv` to `.trash/` (organized by date or task)
- After completing the full task, report what's in `.trash/`. Owner decides what stays and what goes.
- **Exception**: Build artifacts (`node_modules/`, `__pycache__/`, `.pyc`) and clearly temporary files can be deleted directly.

</critical>

### UI/Frontend
- Match existing page style exactly. No extra borders, shadows, or decorative elements unless asked
- Before modifying dashboard/ or any frontend file, Read neighboring components first
- Minimal diff — don't redesign what already works

### File Organization
- Check private/ vs public/ directories before writing files
- Sensitive/private content goes to SOUL/private/ (gitignored). Public content goes to SOUL/public/ (tracked).

### desktop_use — GUI Automation
→ Full architecture: `docs/architecture/modules/desktop-use.md` (types, ABCs, detection stages, perception layers)
- Use `/analyze-ui` skill for UI detection testing, don't hand-write mss/ctypes screenshot code
- cvui Stages can be composed; don't rewrite existing logic
- detection.py/visualize.py are thin re-exports from cvui package

### Docker & Environment
- Before Docker rebuilds, check if one is truly needed
- Before GPU-heavy tasks, run `nvidia-smi` to check VRAM availability
- Check `docker ps` to avoid port/resource conflicts
