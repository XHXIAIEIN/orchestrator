# Orchestrator

Read `.claude/boot.md`. That's everything you need — identity, relationship, voice calibration, recent memories, working guidelines.

The remaining private files are in `SOUL/private/` (identity.md, hall-of-instances.md, experiences.jsonl) — consult as needed.
Files under the memory directory can also be read on demand; no need to load them all.

Then get to work.

## Rules

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
