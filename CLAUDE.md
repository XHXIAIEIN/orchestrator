# Orchestrator

Read `.claude/boot.md`. That's everything you need — identity, relationship, voice calibration, recent memories, working guidelines.

The remaining private files are in `SOUL/private/` (identity.md, hall-of-instances.md, experiences.jsonl) — consult as needed.
Files under the memory directory can also be read on demand; no need to load them all.

Then get to work.

## Rules

### Execution
- Execute directly. Don't ask "should I continue?" or "should I run this?" — just do it.
- Don't present a menu of options. Use your judgment, pick the best approach, execute.
- Complete multi-step tasks end to end. Don't report progress at every step waiting for a nod.
- Parallelize when possible. If you can search three files at once, don't do them one by one.
- Only stop for: system-level destructive ops, sending messages to external services, or when the request itself is flawed.

### Deletion = Move to .trash/, Not Delete
- Files being deleted/replaced/cleaned up → `mv` to `.trash/` (organized by date or task)
- After completing the full task, report what's in `.trash/`. Owner decides what stays and what goes.
- **Exception**: Build artifacts (`node_modules/`, `__pycache__/`, `.pyc`) and clearly temporary files can be deleted directly.

### Git Safety
- **Stage first, push later**: `commit` and `push` are two separate steps. Don't auto-push.
- Prefer working on a local branch rather than committing directly to main/master.
- **Rollback is a no-go zone**: Never execute `git reset --hard`, `git checkout -- .`, `git restore .`, `git clean -f`, or any operation that discards uncommitted changes — unless the owner explicitly says "roll back" or "reset". If a rollback is requested, backup first (`git stash` or `git diff > backup.patch`), report backup location, then execute.
- When stuck on a bug, **diagnose the problem** — don't nuke the code back to the last commit.

### UI/Frontend
- Match existing page style exactly. No extra borders, shadows, or decorative elements unless asked
- Before modifying dashboard/ or any frontend file, Read neighboring components first
- Minimal diff — don't redesign what already works

### File Organization
- Check private/ vs public/ directories before writing files
- Never put sensitive/private content in git-tracked directories
- SOUL/private/ is gitignored; SOUL/public/ is tracked

### Docker & Environment
- Before Docker rebuilds, check if one is truly needed
- Before GPU-heavy tasks, run `nvidia-smi` to check VRAM availability
- Check `docker ps` to avoid port/resource conflicts
