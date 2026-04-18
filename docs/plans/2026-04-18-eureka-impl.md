# Plan: Eureka Steal Implementation — Cross-Skill Frontmatter Protocol + Gap Back-Arrow + Override Audit Trail

## Goal

Adopt three P0 patterns from Eureka into Orchestrator:
(1) a unified YAML frontmatter schema on steal reports, plans, and memory files that lets skills machine-read status/verdict/gaps without parsing prose;
(2) a Depth-Gap back-arrow protocol so a downstream phase can register a gap on any upstream phase and have it surfaced at rerun;
(3) an override-with-verbatim-reason path on Gate Functions so every owner override is captured, forwarded to `.remember/experiences.jsonl`, and consulted by skills on the next similar gate decision.

"Done" = (a) `docs/steal/*.md` and `docs/plans/*.md` files carry conformant YAML frontmatter parseable by a 5-line Python snippet, (b) at least two existing skills (steal + plan-writer) reference the schema file and emit gaps[], (c) Gate Functions in CLAUDE.md + worktree CLAUDE.md carry the override path, and (d) a smoke-test script exits 0.

---

## Context

R80 (Eureka steal) surfaced three structural gaps in Orchestrator:

1. **No shared frontmatter schema.** Memory files use R42 evidence-tier YAML; steal reports use markdown prose headers; plan files have no status fields at all. Skills cannot machine-read state across phases without parsing prose — they hand-write `skill_routing.md` decision trees instead.

2. **No cross-phase gap tracking.** `verification-gate` is a one-shot check at completion. There is no way for a later phase (e.g., a new steal round) to register "the earlier plan's assumption X was never validated" and have that surface when someone reruns the plan skill.

3. **Gate Functions are binary pass/stop.** When the owner says "just do it anyway", no reason is captured, no trail exists, and the next similar gate has no memory of the previous override. Eureka's override path (verbatim reason → downstream scoring) closes this.

---

## ASSUMPTIONS (defer-to-owner)

| # | Question | Impact if wrong |
|---|----------|-----------------|
| A1 | Apply the new frontmatter schema to **all** existing `docs/steal/*.md` files retroactively, or only to new ones going forward? | If retroactive: ~10 files need header surgery. If forward-only: simpler, but historical reports stay un-parseable. **Defaulting to forward-only in this plan.** |
| A2 | `docs/plans/*.md` retroactive migration: same question. | Same as A1. Default: forward-only. |
| A3 | Write the gap-scanning smoke test in Python (uses stdlib `yaml`, zero new deps) or shell? | Shell can't parse YAML cleanly. **Defaulting to Python.** Owner: if Python is unavailable in CI, say so and we switch to a schema-lint shell script. |
| A4 | Override audit trail: write to `.remember/experiences.jsonl` (private, gitignored) or to `SOUL/public/override-log.md` (tracked)? | Private = owner-only history. Tracked = visible in repo. **Defaulting to `SOUL/public/override-log.md` so overrides survive worktree clones.** |
| A5 | Scope of Gate Function patch: apply to **both** the main `CLAUDE.md` (repo root) and the worktree CLAUDE.md? Or main only, worktree inherits? | Worktrees currently have their own CLAUDE.md copies. **Defaulting to main repo CLAUDE.md only; worktree CLAUDE.md is a snapshot and will be refreshed at next session.** Owner: confirm. |
| A6 | P1 patterns (Red Flags table per skill, Source Attribution, Phase Readiness Warning, Slim Router) are **not in scope** for this plan. Owner: schedule separately or add here? |  |

---

## File Map

| File | Action | Why |
|------|--------|-----|
| `SOUL/public/schemas/artifact-frontmatter.md` | **Create** | Canonical definition of the unified frontmatter schema (fields, types, allowed values, gap struct). This is the single source of truth all skills read. |
| `SOUL/public/schemas/` | **Create dir** | New directory; does not exist yet. |
| `.claude/skills/steal/SKILL.md` | **Modify** | Add "On Start: read artifact-frontmatter.md schema" + "On Save: emit YAML frontmatter block conformant to schema" to the steal skill. |
| `.claude/skills/write-plan/SKILL.md` | **Modify** | Same as steal: add frontmatter emission + gaps[] support to the plan-writer skill. (If write-plan skill doesn't exist, this step creates it as a stub; see ASSUMPTION below.) |
| `SOUL/public/prompts/plan_template.md` | **Modify** | Add frontmatter block to the plan template's example output so every new plan starts with conformant YAML. Also add the "Rename/Reorder Permission" line (P1 soft scaffolding, 1-line cost). |
| `CLAUDE.md` (repo root: `D:/Users/Administrator/Documents/GitHub/orchestrator/CLAUDE.md`) | **Modify** | Patch Gate Functions section: add override path (user provides verbatim reason → append to `SOUL/public/override-log.md` → proceed) to all four gate types. |
| `SOUL/public/override-log.md` | **Create** | Append-only log of owner gate overrides. Schema: `timestamp | gate-type | decision | verbatim-reason | outcome`. |
| `scripts/smoke-test-frontmatter.py` | **Create** | Python script: scans `docs/steal/*.md` and `docs/plans/*.md`, parses YAML frontmatter, asserts required fields present. Exits 0 if all conformant, exits 1 with diff on first violation. Used for local spot-check (not CI-wired in this plan). |

**Excluded from this plan (not touched):**
- `SOUL/private/` files
- `skill_routing.md` (converting it from hand-written if/else to frontmatter-scan is P0-1 Phase 2; deferred)
- `boot.md` (routing expansion is deferred per A6)
- Any `docs/steal/*.md` or `docs/plans/*.md` file other than the two template anchors

---

## Steps

### Phase 1 — Schema Definition

**1. Create directory `SOUL/public/schemas/` in the worktree**

```
mkdir -p /d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/schemas
```

→ verify: `ls /d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/schemas/` returns empty listing without error.

---

**2. Create `SOUL/public/schemas/artifact-frontmatter.md` defining the canonical schema**

Content must specify:
- Required fields for **steal reports**: `phase` (fixed: `steal`), `status` (`in-progress` | `complete`), `round` (integer), `source_url` (string), `evidence` (`verbatim` | `artifact` | `impression`), `verdict` (`adopt` | `park` | `kill` | `partial`), `gaps` (list, may be empty `[]`)
- Required fields for **plans**: `phase` (fixed: `plan`), `status` (`draft` | `ready` | `in-progress` | `complete`), `verdict` (`proceed` | `proceed-with-caution` | `blocked` | `done`), `evidence_strength` (`strong` | `medium` | `weak`), `overridden` (bool), `override_reason` (string | null), `gaps` (list)
- Gap struct definition: `{phase: string, note: string, severity: "minor" | "significant", resolved: bool, resolved_in: string | null}`
- Cap rule prose: "If gaps[] contains 2+ entries with `severity: significant` → treat `evidence_strength` ceiling as `medium`. If 3+ significant → ceiling is `weak`."
- Protocol B' exception: "The **only** permitted cross-artifact write is flipping `resolved: false → true` and filling `resolved_in` on an existing gap entry, when the owning phase is being rerun and the downstream phase has been confirmed."
- A complete YAML example block for both steal and plan types

→ verify: `cat /d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/schemas/artifact-frontmatter.md | head -5` shows `# Artifact Frontmatter Schema`.

---

### Phase 2 — Template & Skill Integration

**3. Modify `SOUL/public/prompts/plan_template.md`: prepend frontmatter block to plan example**

- depends on: step 2

Locate the existing `Plan Structure` code block (lines 12-24 in current file). Insert before the `# Plan: {title}` line this frontmatter template:

```markdown
---
phase: plan
status: draft
verdict: null
evidence_strength: null
overridden: false
override_reason: null
gaps: []
---
```

Also insert after the final `## Boundaries` section a one-line soft-scaffolding note:

```
> Section headings above are starting points. Rename, reorder, or add sections to match how the content actually unfolded.
```

→ verify: `grep -n "^phase: plan" /d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/plan_template.md` returns a hit; `grep -n "starting points" /d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/plan_template.md` returns a hit.

---

**4. Locate the steal skill SKILL.md path**

- depends on: step 2

```
find /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/steal -name "SKILL.md"
```

→ verify: command prints exactly one path. If zero → STOP, report to owner (skill path is wrong). If >1 → use the one not in `constraints/`.

---

**5. Modify the steal skill SKILL.md: add schema reference + frontmatter emission instruction**

- depends on: step 4

In the "On Start" section of `.claude/skills/steal/SKILL.md`, add as the first bullet:

```
- Read `SOUL/public/schemas/artifact-frontmatter.md` to load the canonical frontmatter schema.
```

In the "On Save / Artifact Output" section (or "Output Format" if no "On Save" section exists), add:

```
Every steal report saved to `docs/steal/` MUST open with a YAML frontmatter block conformant to the steal schema defined in `SOUL/public/schemas/artifact-frontmatter.md`. The `gaps[]` field must list any upstream phase gaps discovered during this steal round. If none, write `gaps: []`.
```

→ verify: `grep -n "artifact-frontmatter.md" /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/steal/SKILL.md` returns at least 2 hits.

---

**6. Locate or confirm write-plan skill path**

- depends on: step 2

```
find /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills -maxdepth 2 -name "SKILL.md" | sort
```

→ verify: output lists existing skill paths. Identify which skill owns plan writing (likely `write-plan` or `plan-writer`). If neither exists → record as ASSUMPTION gap and skip step 7 (plan-writer does not exist yet; stub creation is out of scope for this plan).

---

**7. Modify the plan-writer skill SKILL.md: add schema reference + frontmatter emission instruction**

- depends on: step 6 (skip if write-plan skill not found)

Same patch pattern as step 5, but for plan files:

In "On Start": add `- Read SOUL/public/schemas/artifact-frontmatter.md`.

In output format section: add `Every plan file MUST open with a YAML frontmatter block conformant to the plan schema. Set status: draft initially. Set gaps: [] unless this plan is responding to a prior steal round's gap entry.`

→ verify: `grep -n "artifact-frontmatter.md" <plan-skill-SKILL.md-path>` returns at least 2 hits.

---

### Phase 3 — Gate Function Patch

**8. Read current Gate Functions section of `CLAUDE.md` (repo root)**

```
grep -n "Gate:" /d/Users/Administrator/Documents/GitHub/orchestrator/CLAUDE.md
```

→ verify: outputs lines for all four gate types (Delete/Replace, Git Reset, Modify Core Config, Send External Message). Confirms exact line numbers before editing.

---

**9. Add override path to Gate: Delete / Replace File in `CLAUDE.md`**

- depends on: step 8

After the existing step 4 (`4. Proceed.`) in the Delete/Replace gate block, insert:

```
**Override path**: If owner explicitly overrides a "NO → STOP" gate check, require them to state a verbatim reason in the same message. Append to `SOUL/public/override-log.md`: `| <ISO-timestamp> | delete-replace | override | "<verbatim reason>" | pending |`. Then proceed.
```

→ verify: `grep -n "Override path" /d/Users/Administrator/Documents/GitHub/orchestrator/CLAUDE.md` returns exactly 1 hit after this step (more will be added in step 10).

---

**10. Add override path to Gate: Git Reset / Restore / Checkout in `CLAUDE.md`**

- depends on: step 9

Same pattern: after step 4 of the Git Reset gate block, insert:

```
**Override path**: Owner-requested rollback already satisfies step 1 above — no additional verbatim-reason gate. However, if a rollback is performed outside an explicit "roll back" request (i.e., diagnosed as needed by the agent), this gate fires: require verbatim reason, append to `SOUL/public/override-log.md`: `| <ISO-timestamp> | git-reset | override | "<verbatim reason>" | pending |`.
```

→ verify: `grep -c "Override path" /d/Users/Administrator/Documents/GitHub/orchestrator/CLAUDE.md` returns 2.

---

**11. Add override path to Gate: Modify Core Config in `CLAUDE.md`**

- depends on: step 10

After step 4 of the Modify Core Config gate block:

```
**Override path**: If step 3 check fails ("change does not trace to user request") but owner explicitly approves anyway, require verbatim reason, append to `SOUL/public/override-log.md`: `| <ISO-timestamp> | core-config | override | "<verbatim reason>" | pending |`.
```

→ verify: `grep -c "Override path" /d/Users/Administrator/Documents/GitHub/orchestrator/CLAUDE.md` returns 3.

---

**12. Add override path to Gate: Send External Message in `CLAUDE.md`**

- depends on: step 11

After step 4 of the Send External Message gate block:

```
**Override path**: If owner explicitly overrides the "explicit request" requirement, require a verbatim send-authorization message. Append to `SOUL/public/override-log.md`: `| <ISO-timestamp> | external-message | override | "<verbatim reason>" | pending |`.
```

→ verify: `grep -c "Override path" /d/Users/Administrator/Documents/GitHub/orchestrator/CLAUDE.md` returns 4.

---

### Phase 4 — Override Log + Smoke Test

**13. Create `SOUL/public/override-log.md` with schema header**

- depends on: step 9

File content:

```markdown
# Gate Override Log

Append-only. Each row = one owner gate override.
Format: `| ISO-timestamp | gate-type | decision | verbatim-reason | outcome |`

| timestamp | gate-type | decision | verbatim-reason | outcome |
|-----------|-----------|----------|-----------------|---------|
```

→ verify: `head -5 /d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/override-log.md` shows the header line.

---

**14. Create `scripts/smoke-test-frontmatter.py` in the worktree**

Content: Python 3 script using `pathlib` + stdlib `yaml` (`import yaml` via PyYAML — if unavailable, script prints install instruction and exits 2).

Logic:
1. Scan `docs/steal/*.md` and `docs/plans/*.md` for files that contain a YAML frontmatter block (lines between opening `---` and closing `---`).
2. For each file with a frontmatter block, parse the YAML and assert: `phase` field is present and is a string; `status` field is present; `gaps` field is present and is a list.
3. For each gap entry in `gaps`, assert keys `phase`, `note`, `severity`, `resolved` are all present; `severity` is `"minor"` or `"significant"`; `resolved` is bool.
4. Print `PASS: <filepath>` for each conformant file, `FAIL: <filepath> — <reason>` for each violation.
5. Exit 0 if zero failures, exit 1 if any failures.

Files without any `---` frontmatter block are **skipped** (not failed) — forward-only migration means old files without frontmatter are not checked.

→ verify: `python /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-eureka/scripts/smoke-test-frontmatter.py` exits 0 (no existing files have frontmatter yet, so all are skipped).

---

**15. Add conformant YAML frontmatter to this plan file itself (`docs/plans/2026-04-18-eureka-impl.md`)**

- depends on: step 2

Insert at the very top of this file (before `# Plan:`):

```yaml
---
phase: plan
status: draft
verdict: proceed
evidence_strength: strong
overridden: false
override_reason: null
gaps:
  - phase: steal
    note: "R80 steal report itself lacks YAML frontmatter — it uses prose markdown headers. This plan adds frontmatter only to new artifacts; the R80 report stays as-is per A1 (forward-only)."
    severity: minor
    resolved: false
    resolved_in: null
---
```

→ verify: `python /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-eureka/scripts/smoke-test-frontmatter.py` exits 0 and prints `PASS: docs/plans/2026-04-18-eureka-impl.md`.

---

## Phase Gate: Plan → Implement

```
--- PHASE GATE: Plan → Implement ---
[ ] Deliverable exists: this plan file, conformant to plan_template.md
[ ] Acceptance criteria: all 15 steps have action verb + specific target + verify command; 0 banned phrases
[ ] Open questions: A1–A6 explicitly marked as ASSUMPTIONS; write-plan skill existence check deferred to step 6
[ ] Owner review: REQUIRED — confirm A4 (override log location), A5 (CLAUDE.md scope), A6 (P1 deferral) before proceeding to implementation
```

---

## Non-Goals

- **P1 patterns** (per-skill Red Flags table, Source Attribution tags in prose, Phase Readiness Warning, Slim Router `/orchestrator:status`) — deferred. Track as A6.
- **P2 patterns** (Workflow order rationale, 3-miss pause) — reference only, no implementation.
- **Retroactive frontmatter migration** of existing steal reports and plan files — deferred per A1/A2.
- **Modifying `skill_routing.md`** to use frontmatter scanning instead of hand-written decision tree — this is P0-1 Phase 2; needs its own plan after the schema is stable.
- **Eureka's full idea evaluation workflow** (concept/validate/gtm/feasibility/mvp/decide pipeline) — we are adopting the protocols, not the workflow itself.
- **Any new Python deps** beyond stdlib + PyYAML (which is already present in most environments).

---

## Rollback

All changes in this plan are additive (new files + appends to existing skill SKILL.md files + insertion of frontmatter block to plan_template.md + Gate Function text additions to CLAUDE.md).

**To undo completely:**
1. `git revert <commit-sha>` on the commit(s) that introduced these changes — no data is destroyed.
2. Delete `SOUL/public/schemas/artifact-frontmatter.md`, `SOUL/public/override-log.md`, `scripts/smoke-test-frontmatter.py`.
3. The smoke-test script has no side effects; it only reads files.

**Partial rollback (e.g., keep schema but revert Gate Function patch):**
- `git diff` the CLAUDE.md changes, manually remove the four "Override path" blocks.
- The schema and skill patches are independent; they can be reverted without touching each other.
