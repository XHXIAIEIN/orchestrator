# Project Conventions

Low-frequency reference for Orchestrator-specific conventions. Loaded on demand from CLAUDE.md.

## UI / Frontend

- Match existing page style exactly. No extra borders, shadows, or decorative elements unless asked.
- Before modifying `dashboard/` or any frontend file, Read neighboring components first.
- Minimal diff — don't redesign what already works.

## File Organization

- Sensitive / private content → `SOUL/private/` (gitignored).
- Public, version-controlled content → `SOUL/public/`.
- Project-internal memory → `.remember/`.
- Trash / staging for deletion → `.trash/<date>-<task>/`.
- Check `private/` vs `public/` before writing any new file.

## desktop_use — GUI Automation

Full architecture: `docs/architecture/modules/desktop-use.md` (types, ABCs, detection stages, perception layers).

- Use `/analyze-ui` skill for UI detection testing — don't hand-write `mss` / `ctypes` screenshot code.
- cvui Stages can be composed; don't rewrite existing logic.
- `detection.py` / `visualize.py` are thin re-exports from the cvui package.

## Docker & Environment

- Before Docker rebuilds, check if one is truly needed (`docker images`, `docker ps`).
- Before GPU-heavy tasks, run `nvidia-smi` to check VRAM availability.
- Check `docker ps` to avoid port / resource conflicts before starting services.
- Container is named `orchestrator`; DB is at `./data/orchestrator.db`.
