# Handoff: Claude Code Best Practices — Phase B (COMPLETE)

**Status**: ✅ COMPLETE — all three gaps landed (Phase A `1d95ed6`, Gap 2 `6a2c6ee`, Gap 1 `5a66a7b`, Gap 3 `449cb85`).
**Source sessions**: 2026-04-26
**Source documents**:
- https://code.claude.com/docs/en/best-practices
- https://agentskills.io/skill-creation/best-practices

## What's done

### Phase A — `1d95ed6` `refactor(claude.md): slim by 27%, externalize advisory rules to skills`

- CLAUDE.md: 198 → 145 lines
- Externalized: Memory Evidence Grading, Per-Skill Constraints meta, UI/Docker conventions, Verification Gate detail block
- New: `.claude/skills/memory-evidence/SKILL.md` (auto-invokes on memory file edits)
- New: `.claude/skills/README.md` (per-skill meta + authoring guide grounded in skill best practices)
- New: `SOUL/public/prompts/project-conventions.md`
- Added `/clear between unrelated tasks` to Context Management section
- Block-protect region (5 safety gates) preserved byte-for-byte
- Backup at `.trash/2026-04-26-workflow-refactor/CLAUDE.md.bak`

### Gap 2 — `6a2c6ee` `docs(claude.md, skill_routing): route multi-file refactors through Plan Mode`

- `SOUL/public/prompts/skill_routing.md`: decision-tree branch + Routing Signals row for "multi-file structural change → Plan Mode (Shift+Tab)"
- `CLAUDE.md`: Plan Mode bullet at the top of Planning Discipline (`### Planning Discipline → Plan Mode for >2 files`)
- +6 lines total, block-protect region untouched

### Gap 1 — landed in this session (split verification gate)

- New `.claude/skills/verification-spec/{SKILL.md,workflow.json,.skill_id}` — pre-task gate, emits Goal/Verify/Assume block before first write
- New `.claude/skills/verification-check/{SKILL.md,workflow.json,.skill_id}` — post-task 5-step evidence chain (Pre-Flight section moved into spec)
- `babysit-pr`, `systematic-debugging`, `steal` workflow.json `follow_up` updated to `verification-check`
- `CLAUDE.md` See-also rows split into pre-task / post-task entries (block-protect untouched)
- `SOUL/public/prompts/skill_routing.md` decision tree + Routing Signals + Quality Bar all reference the split
- `README.md` skill table split into two rows
- `SOUL/public/skill_store.jsonl` retired old + imported two new
- Old `.claude/skills/verification-gate/` moved to `.trash/2026-04-26-gap1/`

### Gap 3 — `449cb85` `refactor(agents): retire architect+operator, scope engineer to worktree dispatch`

- Audited 8 project-local subagents against best-practices "research not execution" rule
- Kept 5 research-type (analyst, inspector, reviewer, sentinel, verifier) — all READ-ONLY
- Kept `engineer` but tightened description to worktree-isolated dispatch only (steal pilots, worktree pipeline)
- Retired `architect` (superseded by Plan Mode added in Gap 2) and `operator` (infra ops need live state on main thread, isolation is net loss)
- `.claude/skills/README.md` gained: dispatch 3-question test, full Subagent Roster table, retired list with rationale
- Files moved to `.trash/2026-04-26-gap3/`

## Phase B closed

No further gaps from the source documents are tracked. Future workflow improvements should open a fresh handoff.
