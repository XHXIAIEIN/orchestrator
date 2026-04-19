# Conduct: Planning Discipline

- All multi-step plans MUST follow `SOUL/public/prompts/plan_template.md` format.
- **File Map first**: List every file that will be touched before writing any step.
- **Atomic steps**: Each step is 2-5 minutes, starts with an action verb, has an explicit verify command.
- **No Placeholder Iron Rule**: Never write vague steps. Banned: "implement the logic", "add appropriate error handling", "update as needed", "etc.", "similar to X", bare "refactor"/"clean up"/"optimize". Every step must specify exact targets, exact changes, exact verification.
- **Explicit dependencies**: If step N depends on step M, write `depends on: step M`. Implicit ordering is not allowed.
- **Delete Before Rebuild**: For files >300 LOC undergoing structural refactor, first remove dead code (unused exports/imports/props/debug logs) and commit separately. Then start the real work with a clean token budget.

<!-- source: CLAUDE.md §Planning Discipline, extracted 2026-04-18 -->
