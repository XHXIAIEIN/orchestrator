# Plan: R80 Prompt-Engineering-Models Steal — P0 Implementation

## Goal

Three P0 patterns from R80 are live in `SOUL/public/prompts/` and `.claude/skills/`: meta-prompting XML trailer in `plan_template.md` + `scrutiny.md`, YAML output contract in `scrutiny.md` outputs, and "When NOT to apply" boundary blocks in `systematic-debugging/SKILL.md` + `skill_routing.md`. Verified by reading each target file and confirming the new sections are present and non-empty.

## Context

R80 steal report: `docs/steal/R80-prompt-engineering-models-steal.md`

Three P0 patterns extracted from `xlrepotestaa/prompt-engineering-models`:

- **P0-1 Meta-Prompting XML tags**: `<reasoning_effort>`, `<self_reflection>`, `<exploration>` trailers that direct *how* the model thinks, not just what to produce. Our current prompts in `SOUL/public/prompts/` have no per-prompt reasoning scaffold — we rely on Claude's built-in extended thinking without steering.
- **P0-2 YAML Output Contract**: Fixed-key YAML schema makes outputs programmatically chainable. `scrutiny.md` currently produces free-form prose; agent-to-agent handoffs have no structured payload contract.
- **P0-3 "When NOT to apply" blocks**: Dedicated boundary-condition sections per technique (4-6 hard stops). `systematic-debugging/SKILL.md` has no technique boundary guards; `skill_routing.md` has no "don't route here when..." conditions.

## ASSUMPTIONS

1. `find-bugs` and `simplify` skills do not exist in this worktree (confirmed: `ls .claude/skills/` shows neither). Steps targeting those skills are deferred to Non-Goals.
2. XML-style tags (`<reasoning_effort>`, `<self_reflection>`, `<exploration>`) are treated as plain-text prompt directives to Claude, not HTML — no parser needed.
3. The YAML output contract applies only to `scrutiny.md`'s machine-facing decision output, not to its conversational explanation prose.
4. `prompt-maker:prompt-standard` skill does not exist in this worktree — adding a "Meta-Prompting" section to that skill is out of scope here (would require the plugin to be present).
5. P1 patterns (3D scoring, before/after diptych, failure taxonomy, chain recipes) are out of scope for this plan.

## Already Implemented

The Layer-0 skill constraint `unaudited-attachment-triage.md` was committed in `f38c3ef` (2026-04-18). It codifies the R80 retrospective lesson: metadata signals gate triage, not verdict; binary attachments must be opened before any security conclusion is drawn. This covers the Security/Governance gap listed in R80 § Gaps Identified ("ADD AS TRIAGE STEP"). No further work needed on that gap.

## File Map

| File | Action | Reason |
|------|--------|--------|
| `SOUL/public/prompts/plan_template.md` | Modify | Add meta-prompting XML trailer section (P0-1) |
| `SOUL/public/prompts/scrutiny.md` | Modify | Add meta-prompting XML trailer (P0-1) + YAML output contract for decision output (P0-2) |
| `.claude/skills/systematic-debugging/SKILL.md` | Modify | Add "When NOT to apply" boundary block (P0-3) |
| `SOUL/public/prompts/skill_routing.md` | Modify | Add per-skill "When NOT to route here" boundary conditions (P0-3) |

## Steps

### Step 1 — Append meta-prompting XML trailer to `plan_template.md`

**Target**: `SOUL/public/prompts/plan_template.md` (134 lines)

**Change**: Append a new section `## Meta-Prompting Trailer` at the end of the file. Content:

```markdown
## Meta-Prompting Trailer

Every plan produced by an agent MUST include the following block verbatim at the end of the plan document, after the Rollback section:

---
<reasoning_effort>HIGH</reasoning_effort>
<self_reflection>Build a rubric before answering: (1) Is every step atomic and 2-5 minutes? (2) Does every step have an action verb + explicit target + verify command? (3) Is every dependency declared? (4) Are banned placeholder phrases absent? Verify all four criteria before finalizing the plan.</self_reflection>
<exploration>Consider: which files does this plan NOT touch that might be affected? Are there hidden ordering dependencies between steps? Would a different File Map sequence reduce risk?</exploration>
```

**Verify**: `grep -n "reasoning_effort" SOUL/public/prompts/plan_template.md` returns a line number.

---

### Step 2 — Append meta-prompting XML trailer to `scrutiny.md`

**Target**: `SOUL/public/prompts/scrutiny.md` (110 lines)

**Change**: Append a new section `## Meta-Prompting Trailer` at the end. Content:

```markdown
## Meta-Prompting Trailer

Include verbatim at the end of every scrutiny evaluation:

---
<reasoning_effort>HIGH</reasoning_effort>
<self_reflection>Build a rubric before answering: (1) Is the task reversible? (2) Does the task affect external services or production state? (3) Is there a spec/goal stated that makes the request verifiable? (4) Does the task cross a Gate Function boundary? Score each criterion explicitly before issuing APPROVE / REJECT / CLARIFY.</self_reflection>
<exploration>Consider the implicit scope: what adjacent files, configs, or services might be affected by this task that the request didn't mention? List them before deciding.</exploration>
```

**Verify**: `grep -n "reasoning_effort" SOUL/public/prompts/scrutiny.md` returns a line number.

- depends on: Step 1 (establishes the pattern; Step 2 follows the same structure)

---

### Step 3 — Add YAML output contract to `scrutiny.md`

**Target**: `SOUL/public/prompts/scrutiny.md`

**Change**: In the existing `scrutiny.md`, locate the section that describes the output format (the APPROVE / REJECT / CLARIFY decision). Add a new subsection `### Machine-Facing Output Contract` immediately after the prose decision description. Content:

```markdown
### Machine-Facing Output Contract

When scrutiny output will be consumed by another agent (not a human), emit the decision block in YAML instead of prose. Schema:

```yaml
scrutiny_result:
  verdict: APPROVE | REJECT | CLARIFY          # enum, required
  confidence: 1-10                              # integer, required
  gate_triggered: null | string                 # which Gate Function fired, if any
  reversible: true | false                      # is the task reversible?
  missing_info:                                 # list if verdict=CLARIFY, else []
    - string
  rejection_reason: null | string               # required if verdict=REJECT
```

Keep prose explanation for human-facing output. YAML contract is for agent-to-agent handoffs only.
```

**Verify**: `grep -n "scrutiny_result" SOUL/public/prompts/scrutiny.md` returns a line number.

- depends on: Step 2 (file already opened and trailer added; this edit follows in the same file)

---

### Step 4 — Add "When NOT to apply" boundary block to `systematic-debugging/SKILL.md`

**Target**: `.claude/skills/systematic-debugging/SKILL.md` (88 lines)

**Change**: After the final phase section (Phase 4 or the last numbered phase), append a new section `## When NOT to Apply This Protocol`. Content:

```markdown
## When NOT to Apply This Protocol

Do NOT invoke the full systematic-debugging protocol when:

1. **The error message is self-explanatory and the fix is one line** — a missing import, a typo in a variable name, a wrong argument count. Five-phase root-cause analysis for a `NameError: name 'x' is not defined` is overhead, not discipline.
2. **The issue was introduced by the current session's most recent edit** — check `git diff HEAD` first; if the broken line is visible, fix it directly without Phase 1.
3. **You are debugging a test fixture, not production logic** — test scaffolding failures (wrong mock return, missing fixture) don't require backward tracing five levels deep.
4. **The bug has already been root-caused and you're implementing the known fix** — don't re-run Phase 1 when the cause is already in the conversation context.
5. **The failure is environmental, not code** — missing env var, wrong Python version, port already in use. Diagnosis is `env | grep VAR` or `lsof -i :PORT`, not a call chain trace.
```

**Verify**: `grep -n "When NOT to Apply" .claude/skills/systematic-debugging/SKILL.md` returns a line number.

---

### Step 5 — Add "When NOT to route here" conditions to `skill_routing.md`

**Target**: `SOUL/public/prompts/skill_routing.md` (97 lines)

**Change**: Append a new section `## Routing Boundary Conditions` at the end of the file. Content:

```markdown
## Routing Boundary Conditions

Anti-pattern guard: explicit stop rules for the most over-used routing paths.

### Do NOT route to `systematic-debugging` when:
- The error is visible in the last edit (`git diff` shows the broken line) — fix directly.
- The issue is an environment problem (missing package, wrong Python, port conflict) — diagnose with shell tools, not the debugging protocol.

### Do NOT route to `verification-gate` when:
- The task is still in-progress — verification-gate is a *completion* check, not a mid-task checkpoint.
- The output is human-readable prose with no side effects — evidence-chain overhead exceeds value.

### Do NOT route to `steal` skill when:
- The target repo has not been reviewed for active malware delivery (e.g., postinstall hooks in `package.json`, suspicious `setup.py`). Screen for executable entry points before initiating Phase 1.
- The steal topic duplicates a round already in `docs/steal/` at P0 coverage — check the index before dispatching.

### Do NOT route to `scrutiny` when:
- The task is explicitly reversible (can be undone with a single `git revert`) AND touches no external services — scrutiny overhead is not justified.
- The agent already has explicit owner authorization in the current session context — re-running scrutiny is theater.
```

**Verify**: `grep -n "Routing Boundary Conditions" SOUL/public/prompts/skill_routing.md` returns a line number.

- depends on: Step 4 (conceptually parallel, but Step 4 establishes the "When NOT to" pattern; Step 5 follows the same structure)

---

## Non-Goals

- **`find-bugs` skill**: Does not exist in this worktree. YAML output contract and "When NOT to apply" for `find-bugs` are deferred.
- **`simplify` skill**: Does not exist in this worktree. Boundary conditions for `simplify` are deferred.
- **`prompt-maker:prompt-standard` plugin**: Not present in this worktree. Adding "Meta-Prompting" as a required section to that plugin's prompt-standard definition is deferred.
- **P1 patterns**: 3D scoring (severity × impact × effort), before/after code diptych, exhaustive failure taxonomy port to systematic-debugging, chain/sequence playbook for skill_routing — all out of scope for this plan.
- **Unaudited zip audit**: The two `.zip` files in the source repo were not opened during the steal. Auditing them is a separate task requiring a sandboxed environment.
- **supply-chain-risk-auditor skill**: The triage step addition mentioned in R80 § Adjacent Discoveries targets a skill that is not in this worktree.

## Rollback

All four target files are tracked in git. If any step produces a broken prompt:

```bash
git diff SOUL/public/prompts/plan_template.md   # inspect
git diff SOUL/public/prompts/scrutiny.md
git diff .claude/skills/systematic-debugging/SKILL.md
git diff SOUL/public/prompts/skill_routing.md
```

To revert a single file: owner runs `git checkout HEAD -- <file>` (requires explicit owner instruction per CLAUDE.md Git Safety rules — do not self-revert without authorization).

---

<reasoning_effort>HIGH</reasoning_effort>
<self_reflection>Build a rubric before answering: (1) Is every step atomic and 2-5 minutes? (2) Does every step have an action verb + explicit target + verify command? (3) Is every dependency declared? (4) Are banned placeholder phrases absent? Verify all four criteria before finalizing the plan.</self_reflection>
<exploration>Consider: which files does this plan NOT touch that might be affected? Are there hidden ordering dependencies between steps? Would a different File Map sequence reduce risk?</exploration>
