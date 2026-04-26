# Plan: Flux-Enchanted P0 Patterns Implementation

## Goal

Implement the 5 P0 patterns from R80 (Conduct module decomposition, 14-code failure taxonomy, deep learnings.json, U-curve + checkpoint, precedent log) such that each pattern has a verifiable artifact in the repo and is wired into at least one active path (hook, skill, or CLAUDE.md reference).

## Context

- Steal report: `docs/steal/R80-flux-enchanted-steal.md`
- Source: https://github.com/enchanted-plugins/flux (MIT, 2026-04)
- Effort budget: ~9h total across 5 P0 patterns
- All file paths in this plan are **worktree-relative** — every step targets the file at the same path inside `.claude/worktrees/steal-flux-enchanted/`. The 2026-04-26 plan-path patch (`feat(steal/flux-enchanted): patch plan paths to worktree-relative`) rewrote the original absolute `/d/Users/Administrator/Documents/GitHub/orchestrator/` prefix to empty so subagents and the main session both write to the worktree, never the main tree (this was the cross-tree pollution mode that produced `.trash/2026-04-19-flux-enchanted-tree-mismatch/` in session 2).
- CLAUDE.md edits (Step 10, Step 20) target `CLAUDE.md` inside this worktree. Step 10 is **deferred behind an owner-review gate** — it converts six full sections to one-line `@`-import stubs, which is a substantive restructure of the global ruleset; owner approves the direction before that step runs. Phase 4 Step 20 operates on the **pre-Step-10** state (the full sections still inline) — it just relocates the `<critical>` block; functionally identical regardless of Step 10's status.
- Existing memory: `SOUL/public/skill_executions.jsonl`, `SOUL/public/skill_store.jsonl` — no structured `learnings.json` yet
- Existing hooks: `.claude/hooks/guard-rules.conf` is load-bearing (must NOT be touched); other post-hooks are advisory candidates
- Existing failure notes: free-text in `.remember/` (path may not exist in main repo — see ASSUMPTION A1)

## ASSUMPTIONS

**A1 — .remember/ path**: Report references `.remember/now.md` as existing mixed memory. Actual path in main repo needs confirmation — run `find /d/Users/Administrator/Documents/GitHub/orchestrator -name "now.md" -path "*remember*"` before Step 14.

**A2 — @-import mechanism availability**: Flux uses `@shared/conduct/xxx.md` syntax. Claude Code's `@` file-import in CLAUDE.md is supported natively. Assumption: the main repo CLAUDE.md supports `@` imports. Owner to confirm if a different mechanism (e.g., shell `source`, explicit copy-paste) is intended.

**A3 — pre-bash hook existence**: Report specifies adding grep to `.claude/hooks/pre-bash.sh`. This file does NOT exist currently — only `guard.sh` and other hooks exist. Step 22 creates it fresh; owner confirm if pre-bash hook is a supported CC hook event name (`PreBash` vs `pre_bash`).

**A4 — learnings.json location**: Report says `SOUL/public/learnings/` for the JSON. `SOUL/private/` is gitignored. Since learnings.json contains strategy effectiveness data (not personal/sensitive), `SOUL/public/learnings/` is the correct location. Owner confirm if confidence decay data should be in private instead.

**A5 — conduct module @-import scope**: Report says "根 CLAUDE.md 只留总纲 + @-import 列表；每 skill 按需加载相关条目". Interpretation: root CLAUDE.md gets @-import lines pointing to `SOUL/public/conduct/*.md`; individual skill SKILL.md files do NOT change in this plan (adding conduct @-imports to all skills is out of scope for this iteration — see Non-Goals).

---

## File Map

| File | Action | Pattern |
|------|--------|---------|
| `SOUL/public/conduct/` | Create directory | P0-1 Conduct modules |
| `SOUL/public/conduct/context.md` | Create | P0-1 |
| `SOUL/public/conduct/verification.md` | Create | P0-1 |
| `SOUL/public/conduct/git-safety.md` | Create | P0-1 |
| `SOUL/public/conduct/deletion.md` | Create | P0-1 |
| `SOUL/public/conduct/planning-discipline.md` | Create | P0-1 |
| `SOUL/public/conduct/surgical-changes.md` | Create | P0-1 |
| `SOUL/public/conduct/failure-modes.md` | Create | P0-1 + P0-2 (F-codes live here) |
| `CLAUDE.md` | Modify — extract 6 sections into @-imports, keep `<critical>` block headers as one-line stubs + @-import | P0-1 + P0-4 (U-curve reorder) |
| `SOUL/public/learnings/` | Create directory | P0-3 |
| `SOUL/public/learnings/schema.json` | Create — canonical 7-field schema with field definitions | P0-3 |
| `SOUL/public/learnings/learnings.json` | Create — empty seed with all 7 fields initialized | P0-3 |
| `SOUL/public/learnings/update-learnings.sh` | Create — script to append a session outcome entry | P0-3 |
| `SOUL/private/precedent-log.md` | Create | P0-5 |
| `.claude/hooks/pre-bash.sh` | Create — grep precedent-log before bash execution | P0-5 |
| `.claude/hooks/whitelist.conf` | Modify — add pre-bash hook exemption for grep itself | P0-5 |
| `.claude/skills/verification-gate/SKILL.md` | Modify — add checkpoint trigger rule at 50% context | P0-4 checkpoint |

---

## Steps

### Phase 1 — Conduct Module Extraction (~2h)

**Step 1.** Read `CLAUDE.md` lines 1-250 in full to establish exact section boundaries before any edit.
→ verify: `wc -l CLAUDE.md` returns a line count; Read tool returns content without error.

**Step 2.** Create directory `SOUL/public/conduct/` (main repo).
→ verify: `ls SOUL/public/conduct/`

**Step 3.** Create `SOUL/public/conduct/context.md` containing the exact text of the `### Context Management` section extracted from CLAUDE.md (lines ~44-48), plus a header `# Conduct: Context Management` and a footer `<!-- source: CLAUDE.md §Context Management, extracted 2026-04-18 -->`.
→ verify: `wc -c SOUL/public/conduct/context.md` returns non-zero; section text matches original verbatim.

**Step 4.** Create `SOUL/public/conduct/planning-discipline.md` containing the exact text of `### Planning Discipline` (lines ~49-56) with header `# Conduct: Planning Discipline`.
→ verify: `grep "No Placeholder Iron Rule" SOUL/public/conduct/planning-discipline.md`
- depends on: step 2

**Step 5.** Create `SOUL/public/conduct/surgical-changes.md` containing the exact text of `### Surgical Changes` (lines ~57-63) with header `# Conduct: Surgical Changes`.
→ verify: `grep "Edit Integrity" SOUL/public/conduct/surgical-changes.md`
- depends on: step 2

**Step 6.** Create `SOUL/public/conduct/git-safety.md` containing the exact text of `### Git Safety` section inside `<critical>` (lines ~66-71) with header `# Conduct: Git Safety`.
→ verify: `grep "Stage first, push later" SOUL/public/conduct/git-safety.md`
- depends on: step 2

**Step 7.** Create `SOUL/public/conduct/deletion.md` containing the exact text of `### Deletion = Move to .trash/` section (lines ~72-78) with header `# Conduct: Deletion Policy`.
→ verify: `grep "\.trash/" SOUL/public/conduct/deletion.md`
- depends on: step 2

**Step 8.** Create `SOUL/public/conduct/verification.md` containing the exact text of `### Verification Gate` section (lines ~151+) with header `# Conduct: Verification Gate`.
→ verify: `grep "Identify.*Execute.*Read.*Confirm.*Declare" SOUL/public/conduct/verification.md`
- depends on: step 2

**Step 9.** Create `SOUL/public/conduct/failure-modes.md` with:
- Header `# Conduct: Failure Modes — F01–F14 Taxonomy`
- Table of all 14 codes with columns: `Code | Name | Signature | Counter | Escalation` populated from steal report data:
  - F01 Sycophancy — agrees with user correction without evidence; counter: re-state original reasoning; single instance escalates
  - F02 Fabrication — cites non-existent file/function/URL; counter: grep/Read before asserting; single instance escalates
  - F03 Scope Creep — edits files not in task File Map; counter: re-read File Map before each edit; 3+ instances → owner stop
  - F04 Confirmation Bias — only reads evidence supporting current hypothesis; counter: explicitly search for contradictory evidence; 3+ instances
  - F05 Premature Closure — declares done before verify command passes; counter: run verify command output before Declare; single instance escalates
  - F06 Context Bleed — applies rule from a previous task to current task; counter: re-read task boundary at session start; 3+ instances
  - F07 Tool Misuse — uses Read when Grep would suffice, or Bash when Edit exists; counter: consult tool-selection heuristic; 3+ instances
  - F08 Over-Explanation — writes 3 paragraphs where 1 sentence works; counter: count sentences before sending; 3+ instances
  - F09 Permission Creep — asks "should I continue?" mid-task for reversible steps; counter: check Execution Mode rules; 3+ instances
  - F10 Silent Assumption — proceeds with undeclared assumption that changes outcome; counter: log assumption in plan ASSUMPTIONS section; single instance escalates
  - F11 Reward Hacking — satisfies metric while violating intent (e.g., deletes test instead of fixing code); counter: re-read task goal statement; single instance escalates
  - F12 Degeneration Loop — same failing attempt 3+ times without diagnosis change; counter: read error output, change diagnosis, not retry; single instance at count ≥ 3
  - F13 Orphan Creation — leaves unused imports/vars/files after own edits; counter: run grep for own symbol names post-edit; 3+ instances
  - F14 Version Drift — uses API/syntax from training data that has since changed; counter: Read actual file before assuming signature; single instance escalates
- Footer: `<!-- adapted from enchanted-plugins/flux failure-modes taxonomy, 2026-04-18 -->`
→ verify: `grep -c "^| F" SOUL/public/conduct/failure-modes.md` returns `14`
- depends on: step 2

**Step 10.** Edit `CLAUDE.md`: replace each of the 6 extracted sections (`### Context Management`, `### Planning Discipline`, `### Surgical Changes`, `### Git Safety`, `### Deletion = Move to .trash/`, `### Verification Gate`) with a one-line stub + @-import:
```
### Context Management
@SOUL/public/conduct/context.md
```
(repeat pattern for each section). The `<critical>` wrapper block must be preserved; only the section body text is replaced with the @-import line.
→ verify: `wc -l CLAUDE.md` returns a count at least 80 lines fewer than before; `grep "@SOUL/public/conduct/" CLAUDE.md | wc -l` returns `6`
- depends on: steps 3, 4, 5, 6, 7, 8

--- PHASE GATE: Extraction → Taxonomy ---
[ ] Deliverable: 7 files exist in `SOUL/public/conduct/` (6 conduct modules + failure-modes.md)
[ ] Acceptance: `ls SOUL/public/conduct/ | wc -l` returns `7`
[ ] Acceptance: CLAUDE.md contains 6 `@SOUL/public/conduct/` import lines
[ ] No open questions: ASSUMPTION A2 (@-import syntax) must be confirmed by owner before Step 10 is executed
[ ] Owner review: required — Step 10 edits the main CLAUDE.md; confirm @-import syntax first

---

### Phase 2 — Failure Taxonomy Wiring (~1.5h)

**Step 11.** Read `.claude/skills/steal/SKILL.md` to understand current `remember` write pattern (if any F-code tagging exists).
→ verify: Read tool returns file content without error.

**Step 12.** Add a "Failure Tagging Rule" section to `SOUL/public/conduct/failure-modes.md` after the F-code table:
```markdown
## Tagging Rule
Every entry written to memory or `.remember/` that describes a failure MUST include a `[Fxx]` tag matching the closest code above. Format: `[F02] Fabricated path docs/foo.md — Read showed it didn't exist`.
If no code fits exactly, use the nearest + note "partial match".
```
→ verify: `grep "Tagging Rule" SOUL/public/conduct/failure-modes.md`
- depends on: step 9

**Step 13.** Add a "Failure Tag Aggregation" section to `SOUL/public/learnings/schema.json` (see Step 17 — schema creation). This is a placeholder note; actual wiring happens in Step 17.
→ verify: no action needed here; dependency documented.

---

### Phase 3 — Deep Learnings JSON (~3h)

**Step 14.** Resolve ASSUMPTION A1: run `find /d/Users/Administrator/Documents/GitHub/orchestrator -name "now.md" -path "*remember*" 2>/dev/null` and `ls .remember/ 2>/dev/null` to discover actual memory file paths.
→ verify: command output shows either file paths or "no such file" — either outcome is valid; record result.

**Step 15.** Create directory `SOUL/public/learnings/` in the main repo.
→ verify: `ls SOUL/public/learnings/`

**Step 16.** Create `SOUL/public/learnings/schema.json` with this exact structure:
```json
{
  "_version": "1.0",
  "_description": "Flux-pattern learnings schema. Adapted from enchanted-plugins/flux. 2026-04-18.",
  "_fields": {
    "sessions": "Array of {date, topic, outcome} — one entry per steal/round session",
    "strategy_stats": "Object keyed by strategy_id: {applied, reverted, consecutive_failures, last_used}",
    "fix_history": "Last 30 entries: {date, fcode, description, what_worked}",
    "negative_examples": "Last 15 entries: {date, fcode, description, what_failed, why}",
    "weakness_profile": "Object: {weakness_id: {description, co_occurring_with: [], count}}",
    "confidence_scores": "Object keyed by strategy_id: {score_0_to_1, last_updated, decay_per_session: 0.10}",
    "recommendations": "Array of {generated_date, basis_fcode, text, status: pending|accepted|rejected}"
  },
  "_patterns": {
    "reliable": "strategy with confidence_score >= 0.8 and consecutive_failures == 0",
    "unreliable": "strategy with consecutive_failures >= 2",
    "stuck": "strategy applied >= 3 times with no revert but outcome unchanged",
    "plateau": "confidence_score delta < 0.05 across last 3 sessions",
    "co_occurring": "two weaknesses appearing together in >= 3 fix_history entries"
  }
}
```
→ verify: `python3 -c "import json; json.load(open('SOUL/public/learnings/schema.json'))"` exits 0
- depends on: step 15

**Step 17.** Create `SOUL/public/learnings/learnings.json` as the live data file, seeded with empty structures per schema:
```json
{
  "_schema_version": "1.0",
  "_last_updated": "2026-04-18",
  "sessions": [],
  "strategy_stats": {},
  "fix_history": [],
  "negative_examples": [],
  "weakness_profile": {},
  "confidence_scores": {},
  "recommendations": []
}
```
→ verify: `python3 -c "import json; d=json.load(open('SOUL/public/learnings/learnings.json')); assert len(d['sessions'])==0"` exits 0
- depends on: step 16

**Step 18.** Create `SOUL/public/learnings/update-learnings.sh` — a bash script that:
1. Accepts arguments: `--session topic=<str> outcome=<pass|fail>` OR `--fix fcode=<F01-F14> description=<str> what_worked=<str>` OR `--decay` (applies 10% confidence decay to all strategy scores)
2. Reads `learnings.json`, applies the mutation, trims `fix_history` to last 30 and `negative_examples` to last 15, writes back atomically via temp file + `mv`
3. Prints `updated learnings.json: <field> now has <N> entries`

Script must use `python3 -c` inline for JSON manipulation (no external deps). Include `set -euo pipefail` at top.
→ verify: `bash SOUL/public/learnings/update-learnings.sh --session topic=test-run outcome=pass` exits 0 and `python3 -c "import json; d=json.load(open('SOUL/public/learnings/learnings.json')); assert len(d['sessions'])==1"` exits 0
- depends on: step 17

---

### Phase 4 — U-curve Placement + Checkpoint (~1h)

**Step 19.** Read `CLAUDE.md` again (post-step-10 state) to confirm current section order and identify where Gate Functions and `<critical>` block currently sit relative to file start/end.
→ verify: Read tool returns content; note line numbers of `<critical>` open and close tags.
- depends on: step 10

**Step 20.** Edit `CLAUDE.md`: move the entire `<critical>...</critical>` block (containing Gate Functions + Git Safety stub + Deletion stub) to be the **first major section** after the "## Rules" header and "### Commitment Hierarchy" section — before `### Execution`. This places `<critical>` content in the first-200 token zone.
→ verify: `grep -n "<critical>" CLAUDE.md` returns a line number < 60
- depends on: step 19

**Step 21.** Edit `.claude/skills/verification-gate/SKILL.md` in the main repo: add a "Checkpoint Protocol" section after the existing five-step evidence chain:
```markdown
## Checkpoint Protocol (U-curve)

When context usage reaches approximately 50%, emit a `<checkpoint>` block before continuing:

```xml
<checkpoint>
  <goal>{one-sentence restatement of current task goal}</goal>
  <decisions>{bullet list of choices made so far and their rationale}</decisions>
  <open_questions>{bullet list of unresolved items}</open_questions>
  <next_step>{exact next action}</next_step>
</checkpoint>
```

After emitting, treat checkpoint as the truth source. Earlier conversation context may be ignored for decisions already captured here.
```
→ verify: `grep "Checkpoint Protocol" .claude/skills/verification-gate/SKILL.md`
- depends on: step 8

---

### Phase 5 — Precedent Log + Pre-bash Hook (~1.5h)

**Step 22.** Create `SOUL/private/precedent-log.md` with this structure:
```markdown
# Precedent Log

Self-observed operation failures. Distinct from user feedback (`.remember/`) and iteration learnings (`SOUL/public/learnings/`).

Each entry: command that failed | why it failed | what worked instead | signal to detect next time | tags [F-code]

---

<!-- entries below, newest first -->
```
→ verify: `grep "Self-observed" SOUL/private/precedent-log.md`

**Step 23.** Confirm `SOUL/private/` is gitignored by checking `.gitignore` in the main repo for a `SOUL/private/` entry. If missing, add `SOUL/private/` to `.gitignore`.
→ verify: `grep "SOUL/private" .gitignore`
- depends on: step 22

**Step 24.** Create `.claude/hooks/pre-bash.sh` in the worktree with:
```bash
#!/usr/bin/env bash
# pre-bash hook: grep precedent-log before executing any bash command
# Runs in ≤10ms for typical log size (<500 entries)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../.." || exit 0  # advisory only — never block on repo-root resolution

PRECEDENT_LOG="SOUL/private/precedent-log.md"
COMMAND="${CLAUDE_TOOL_INPUT:-}"  # CC injects the bash command here

if [[ -f "$PRECEDENT_LOG" && -n "$COMMAND" ]]; then
  # Extract first 6 tokens of command as search key
  KEY=$(echo "$COMMAND" | grep -oE '\S+' | head -6 | tr '\n' ' ' | xargs)
  HITS=$(grep -i -- "$KEY" "$PRECEDENT_LOG" 2>/dev/null | head -3 || true)
  if [[ -n "$HITS" ]]; then
    echo "[PRECEDENT] Similar command found in precedent-log:"
    echo "$HITS"
    echo "[PRECEDENT] Review before proceeding."
  fi
fi

exit 0  # always exit 0 — advisory only, never block
```
Make executable: `chmod +x .claude/hooks/pre-bash.sh`
→ verify: `bash .claude/hooks/pre-bash.sh` exits 0 (no error even when CLAUDE_TOOL_INPUT is unset)
- depends on: step 22

**Step 25.** Verify `.claude/hooks/whitelist.conf` (if it exists) does not inadvertently block the pre-bash hook's internal `grep` call. Read the file; if it contains a rule that would match `grep -i` against the precedent log, add an exemption line `allow	grep.*precedent-log	precedent-log self-lookup`.
→ verify: `bash .claude/hooks/pre-bash.sh` still exits 0 after any whitelist changes
- depends on: step 24

--- PHASE GATE: Implementation → Done ---
[ ] Deliverable: `ls SOUL/public/conduct/ | wc -l` = 7; `ls SOUL/public/learnings/` = 3 files; `SOUL/private/precedent-log.md` exists; `.claude/hooks/pre-bash.sh` is executable
[ ] Acceptance: `python3 -c "import json; json.load(open('SOUL/public/learnings/learnings.json'))"` exits 0
[ ] Acceptance: `grep -c "@SOUL/public/conduct/" CLAUDE.md` = 6
[ ] Acceptance: `grep "<critical>" CLAUDE.md` shows line number < 60
[ ] Acceptance: `grep "Checkpoint Protocol" .claude/skills/verification-gate/SKILL.md` returns match
[ ] No open questions: ASSUMPTION A3 (pre-bash hook event name) confirmed by CC hook docs
[ ] Owner review: not required — all changes are reversible markdown/JSON/shell files

---

## Non-Goals

- Modifying individual skill SKILL.md files to add per-skill `@conduct/` imports (out of scope for this iteration; root CLAUDE.md @-imports cover global scope first)
- Implementing SAT binary assertion gate (P1 — separate plan)
- Scope fence templates for sub-agent dispatch (P1 — separate plan)
- Advisory hook audit for existing post-hooks (P1 — separate plan)
- Gauss convergence math engine or σ-scoring (P2 — reference only)
- 64-model registry (P1 — separate plan; only text models relevant)
- Automatic confidence decay scheduler (Phase 3 `update-learnings.sh --decay` covers manual trigger; cron/daemon automation is out of scope)

## Rollback

All changes are new files + markdown edits. No database migrations, no compiled artifacts.

If any step produces a broken state:

1. `git diff CLAUDE.md` to see exact CLAUDE.md changes
2. `git stash` to save all WIP
3. Individual files in `SOUL/public/conduct/`, `SOUL/public/learnings/`, `SOUL/private/` can be deleted directly (they are new, no prior content to restore)
4. `.claude/hooks/pre-bash.sh` can be deleted directly (new file)
5. Revert CLAUDE.md edits via `git checkout -- CLAUDE.md` **only after owner confirms** rollback intent per Git Safety rules

No `git reset --hard` needed — all changes are additive except CLAUDE.md section replacements which are fully reversible via git diff.
