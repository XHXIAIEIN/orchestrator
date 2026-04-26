# Handoff: Claude Code Best Practices — Phase B (remaining gaps)

**Source sessions**: 2026-04-26 (Phase A landed at `1d95ed6`, Gap 2 landed at `6a2c6ee`)
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

## What's left (Phase B — two independent work items)

### Gap 1: Verification timing is inverted

**Problem**: `.claude/skills/verification-gate/SKILL.md` is a *post-hoc* check (run after work claims to be done). Anthropic's best practices flag verification as "the single highest-leverage thing" and recommend stating success criteria *up front*, before any code is written.

**Proposed split**:
- `verification-spec` skill — invoked at task start. Forces "what does success look like? what command proves it?" before any write/run tool call.
- `verification-check` skill — current 5-step evidence chain, kept as the post-completion gate.

**Files to touch**:
- `.claude/skills/verification-gate/SKILL.md` → rename to `verification-check/`, trim to post-hoc only
- New: `.claude/skills/verification-spec/SKILL.md` — frontmatter description: "Use at task start when the owner hands over a code/build/test/UI request, before the first write or destructive command"
- Update `SOUL/public/prompts/skill_routing.md` to route both
- Update `CLAUDE.md` See-also row

**Estimated**: 1 session, ~150 LOC of skill content.

### Gap 3: Subagent role audit

**Problem**: best practices says subagents are for *research* (heavy intermediate output, only conclusion matters), not parallel *execution*. Our 13 project subagents (engineer, operator, verifier, sentinel, inspector, analyst, architect, reviewer, Plan, Explore, general-purpose, codex:codex-rescue, prompt-maker:prompt-linter) include several execution-oriented ones.

**Action**:
- Read each `.claude/agents/*.md` (and `~/.claude/agents/` if present)
- Classify research vs execution
- For execution-type subagents that just shadow main-thread work, either delete or document the specific case where context isolation pays off
- Update `.claude/skills/README.md` "When to create a skill vs other primitives" table with concrete examples

**Estimated**: 1 session.

## Suggested order

1. ~~Gap 2~~ ✅ landed at `6a2c6ee`
2. Gap 1 next (highest ROI per Anthropic's framing)
3. Gap 3 last (requires reading all agent definitions)

## Opening prompt for next session

```
Read SOUL/public/prompts/session_handoff_workflow_best_practices.md, then start Gap 1.
```
