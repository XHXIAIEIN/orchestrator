# Plan: loki-skills-cli Steal Implementation

## Goal

Integrate three P0 patterns (Awakening Ritual, Literal-path sub-agent contract, Jump classification) and two P1 patterns (Provenance watermarks, Post-action self-validation blocks) from R81 into Orchestrator's skill and prompt system, resulting in five concrete file additions/modifications that are verifiable by `cat` and dry-run read tests.

## Context

Source: R81 steal of `zirz1911/loki-skills-cli` (fork of Soul-Brews-Studio/oracle-skills-cli, MIT).
The steal identified patterns that slot into Orchestrator without requiring a vault, MCP server, or Bun runtime — markdown-only changes.
All work lands in the main Orchestrator repo (not the worktree), after owner reviews this plan.

## ASSUMPTIONS

1. **Vault coupling skipped by design** — loki's `ψ/` symlinked vault is the source of the `/awaken`, `/learn`, and `/forward` patterns. Orchestrator replaces all `ψ/` references with `.remember/` (already gitignored for transient state) and `SOUL/private/` (for committed identity docs).
2. **`/awaken` is invoked manually** — there is no hook that auto-triggers it on `git clone`; the owner must call it when landing in a new repo.
3. **`dag_orchestration.md` is the correct home for the literal-path contract** — the steal report says "add to `dag_orchestration.md` or create new `subagent_dispatch_contract.md`"; this plan chooses `dag_orchestration.md` to avoid file sprawl. Owner can override.
4. **Jump Tracker is folded into `rationalization-immunity.md`** — Orchestrator has no `/rrr` equivalent; the report says it "could fold into `doctor` skill". This plan extends `rationalization-immunity.md` with the tracker section and leaves `doctor` integration as a follow-up.
5. **Provenance watermark uses `git log --follow` for `source_version:`** — the report says "pre-commit hook that rewrites `source_version:` from last commit hash touching that skill". This plan uses a manual step (not a hook) to initialize the field; a hook is a follow-up.
6. **`steal/SKILL.md` dispatch template location** — the current `steal/SKILL.md` dispatch block is assumed to be in `.claude/skills/steal/SKILL.md`; the plan patches the literal-path fields there.
7. **No new runtime code written** — all deliverables are `.md` files. Any `.ts` / `.py` / hook scripting is out of scope for this plan.

## File Map

- `.claude/skills/awaken/SKILL.md` — **Create** (new skill, ~80 lines)
- `SOUL/public/prompts/dag_orchestration.md` — **Modify** (append "Literal-Path Sub-Agent Contract" section, ~30 lines)
- `SOUL/public/prompts/rationalization-immunity.md` — **Modify** (append "Jump Tracker" section, ~25 lines)
- `.claude/skills/steal/SKILL.md` — **Modify** (patch dispatch prompt block to include `SOURCE_DIR`, `DEST_DIR`, `DEST_FILE_PATTERN` as literals)
- `SOUL/public/prompts/skill_routing.md` — **Modify** (add `awaken` skill entry under onboarding/new-repo route)

### Provenance watermark (P1 — touches every skill file)

The following files each receive a 2-line frontmatter addition (`origin:` and `source_version:` fields). They are listed separately because each is a standalone 1-minute edit:

- `.claude/skills/adversarial-dev/SKILL.md` — **Modify** (add frontmatter watermark)
- `.claude/skills/babysit-pr/SKILL.md` — **Modify** (add frontmatter watermark)
- `.claude/skills/clawvard-practice/SKILL.md` — **Modify** (add frontmatter watermark)
- `.claude/skills/doctor/SKILL.md` — **Modify** (add frontmatter watermark)
- `.claude/skills/persona/SKILL.md` — **Modify** (add frontmatter watermark)
- `.claude/skills/prime/SKILL.md` — **Modify** (add frontmatter watermark)
- `.claude/skills/steal/SKILL.md` — **Modify** (add frontmatter watermark — same file as step 4, do both edits in one pass)
- `.claude/skills/systematic-debugging/SKILL.md` — **Modify** (add frontmatter watermark)
- `.claude/skills/verification-gate/SKILL.md` — **Modify** (add frontmatter watermark)
- `.claude/skills/awaken/SKILL.md` — **Modify** (watermark included at creation in step 1)

---

## Steps

### Phase A — New `/awaken` skill (P0)

**1.** Create `.claude/skills/awaken/SKILL.md` with frontmatter block
(`name: awaken`, `description: "新仓库落地时强制执行发现仪式，禁止模板复制"`,
`origin: "R81 loki-skills-cli steal — forced re-discovery pattern"`,
`source_version: "2026-04-18"`)
and a 5-step body:

- Step 1 (Discovery): Run `cat README.md 2>/dev/null; cat CLAUDE.md 2>/dev/null; ls docs/ 2>/dev/null` to read project README, CLAUDE.md, and docs index. Gate: agent must be able to state the project's primary purpose in one sentence before continuing.
- Step 2 (Architecture trace): Spawn one sub-agent with `SOURCE_DIR="<absolute-path-of-new-repo>"` and `DEST_DIR="<absolute-path-of-new-repo>/.remember/"` to search for architecture decision records: `grep -r "ADR\|architecture\|AGENTS\|spec" $SOURCE_DIR --include="*.md" -l`. Sub-agent writes findings to `$DEST_DIR/onboard-trace-MMDD.md`.
- Step 3 (Convention articulation): Agent writes `.orchestrator-instance.md` in the project root. The file must contain: (a) project purpose in agent's own words (not copy-pasted), (b) three non-obvious conventions found during trace, (c) which Orchestrator skills are relevant to this repo. Gate: do not write this file until agent can explain each convention from memory, not by re-reading.
- Step 4 (Commit): Run `git add .orchestrator-instance.md && git commit -m "chore(onboard): Orchestrator awakens in <repo-slug>"` on branch `onboard/<repo-slug>`.
- Step 5 (Retrospective): Append a one-paragraph retrospective to `.remember/retrospectives.md` noting what surprised the agent about this repo's conventions.

Constraint block (in file): "BANNED: copying any section verbatim from README, CLAUDE.md, or any template. Write each section from understanding, not from paste."

→ verify: `cat .claude/skills/awaken/SKILL.md | grep -c "Gate:"` must print `2`

---

**2.** Add `awaken` route entry to `SOUL/public/prompts/skill_routing.md` under the "onboarding / new-repo" category (create the category if it does not exist):

```
| New repo / unfamiliar project → `/awaken` | Goal: force local convention discovery before any code changes |
```

→ verify: `grep -n "awaken" SOUL/public/prompts/skill_routing.md` prints at least one match
- depends on: step 1

---

### Phase B — Literal-path sub-agent contract (P0)

**3.** Append a new section `## Literal-Path Sub-Agent Contract` to `SOUL/public/prompts/dag_orchestration.md` with the following content:

```markdown
## Literal-Path Sub-Agent Contract

> Source: R81 loki-skills-cli steal (learn/SKILL.md:85-106). Prevents sub-agents from writing output to the source repo instead of the intended destination.

### Rule

When dispatching a Task agent that reads from one directory and writes to another, you MUST pass both paths as **absolute literal values** in the prompt — not as shell variables, not as relative paths, not as template placeholders.

**Correct**:
```
SOURCE_DIR="/d/Users/Administrator/Documents/GitHub/my-project"
DEST_DIR="/d/Users/Administrator/Documents/GitHub/orchestrator/docs/steal"
DEST_FILE_PATTERN="MMDD_<slug>-findings.md"
```

**Wrong**:
```
SOURCE_DIR="$(pwd)"          # resolves in caller's shell, not sub-agent's
DEST_DIR="../docs/steal"     # relative — sub-agent's cwd may differ
```

### Why

Claude Code sub-agents inherit the session's cwd at spawn time, which may differ from the parent's cwd if the parent used `cd`. A sub-agent given only `origin/` as SOURCE_DIR will `cd origin/` and write output there — corrupting the source.

### Mandatory Fields for Any Multi-Repo Dispatch

| Field | Type | Example |
|-------|------|---------|
| `SOURCE_DIR` | Absolute path | `/d/Users/.../my-project` |
| `DEST_DIR` | Absolute path | `/d/Users/.../orchestrator/docs/steal` |
| `DEST_FILE_PATTERN` | Filename with timestamp prefix | `MMDD_topic-findings.md` |

### Capture Pattern (copy-paste this before spawning)

```bash
SOURCE_DIR="$(git -C /d/path/to/source rev-parse --show-toplevel)"
DEST_DIR="/d/Users/Administrator/Documents/GitHub/orchestrator/docs/steal"
# Then pass $SOURCE_DIR and $DEST_DIR as literals in the Task prompt string — do not pass the variables.
```
```

→ verify: `grep -n "Literal-Path Sub-Agent Contract" SOUL/public/prompts/dag_orchestration.md` prints one match

---

**4.** Patch `.claude/skills/steal/SKILL.md` dispatch prompt block to include three new required fields immediately after the `[STEAL]` tag line:

Locate the existing dispatch prompt block (the section that constructs the agent prompt string) and insert after the `[STEAL]` opening:

```
SOURCE_DIR="<LITERAL absolute path of repo being stolen from — no variables>"
DEST_DIR="<LITERAL absolute path of orchestrator/docs/steal/ — no variables>"
DEST_FILE_PATTERN="MMDD_<slug>-steal.md"
```

Add a comment above the block: `# Literal-path contract (R81) — paths must be absolute literals, not variables`

→ verify: `grep -n "SOURCE_DIR\|DEST_DIR\|DEST_FILE_PATTERN" .claude/skills/steal/SKILL.md` prints three matches
- depends on: step 3

---

### Phase C — Jump Tracker (P0)

**5.** Append a new section `## Jump Tracker` to `SOUL/public/prompts/rationalization-immunity.md` with the following content:

```markdown
## Jump Tracker

> Source: R81 loki-skills-cli steal (recap/SKILL.md:132-170). Detects cumulative avoidance drift that per-excuse rationalization cannot catch.

### Taxonomy

Tag each topic transition in a session with one of five types:

| Tag | Meaning | Healthy? |
|-----|---------|---------|
| `spark` | New idea or thread that arrived organically | Yes |
| `complete` | Finished a task, moving to next | Yes |
| `return` | Came back to a parked thread | Yes |
| `park` | Intentional pause on a hard problem | Neutral |
| `escape` | Switched away from a hard problem without resolution | No |

### Health Rule

- Session health = OK if `escape` count < 3 AND `escape / total_jumps` < 40%.
- If `escape` count ≥ 3 OR `escape / total_jumps` ≥ 40%: surface the pattern immediately. Do not continue the current thread until the owner acknowledges.

### When to Use

- At the start of every `/doctor` invocation: reconstruct last session's jump list from conversation memory (no file reads needed — pure recall).
- Optional: invoke manually as `/prime --jump-check` (owner adds this trigger to `prime/SKILL.md` in a follow-up).

### Surface Format

When health threshold is breached, output:

```
[Jump Tracker] ⚠ escape-heavy session detected
Jumps: spark×N complete×N return×N park×N escape×N
Escape ratio: NN%
Last 3 escapes: <topic-1>, <topic-2>, <topic-3>
Recommendation: return to <most-recent-park> or explicitly abandon it.
```
```

→ verify: `grep -n "Jump Tracker" SOUL/public/prompts/rationalization-immunity.md` prints one match

---

**6.** Add a one-line `doctor` skill cross-reference to the existing `doctor/SKILL.md` pointing to the Jump Tracker:

Locate the "Memory / retrospective" or "Session review" section in `.claude/skills/doctor/SKILL.md`.
Add the line: `- Run Jump Tracker from \`SOUL/public/prompts/rationalization-immunity.md#jump-tracker\` — if escape count ≥ 3 surface it before proceeding.`

→ verify: `grep -n "Jump Tracker" .claude/skills/doctor/SKILL.md` prints one match
- depends on: step 5

---

### Phase D — Provenance watermarks (P1)

**7.** Read `.claude/skills/adversarial-dev/SKILL.md`, `.claude/skills/babysit-pr/SKILL.md`, `.claude/skills/clawvard-practice/SKILL.md` and confirm each has a YAML frontmatter block (lines starting with `---`). If present, insert after the last existing frontmatter key; if absent, prepend a new block.

Add to each:
```yaml
origin: "Orchestrator — earned through direct practice (see commit history)"
source_version: "2026-04-18"
```

→ verify: `grep -l "source_version" .claude/skills/adversarial-dev/SKILL.md .claude/skills/babysit-pr/SKILL.md .claude/skills/clawvard-practice/SKILL.md | wc -l` prints `3`

---

**8.** Read `.claude/skills/doctor/SKILL.md`, `.claude/skills/persona/SKILL.md`, `.claude/skills/prime/SKILL.md` and add the same watermark fields.

→ verify: `grep -l "source_version" .claude/skills/doctor/SKILL.md .claude/skills/persona/SKILL.md .claude/skills/prime/SKILL.md | wc -l` prints `3`
- depends on: step 7 (establish watermark format first)

---

**9.** Read `.claude/skills/steal/SKILL.md`, `.claude/skills/systematic-debugging/SKILL.md`, `.claude/skills/verification-gate/SKILL.md` and add the same watermark fields. (Note: `steal/SKILL.md` is already being modified in step 4 — do both edits in one pass to avoid double-read.)

→ verify: `grep -l "source_version" .claude/skills/steal/SKILL.md .claude/skills/systematic-debugging/SKILL.md .claude/skills/verification-gate/SKILL.md | wc -l` prints `3`
- depends on: step 7 (establish watermark format first)
- depends on: step 4 (steal/SKILL.md must be read before editing)

---

### Phase E — Post-action self-validation blocks (P1)

**10.** Append a `### Post-Action Self-Validation` subsection to the `Gate: Delete / Replace File` block in `CLAUDE.md` (main repo, not worktree — **owner applies this manually after reviewing the plan**; this step is marked OWNER-APPLY):

```markdown
### Post-Action Self-Validation — Delete / Replace File
Run after completing the delete/replace action:
[ ] `ls <expected-path>` returns "No such file" (deleted) or new content (replaced)
[ ] `grep -r "<old-import-or-ref>" . --include="*.py" --include="*.ts" --include="*.md"` returns zero matches
[ ] `git status` shows only the files listed in the File Map — no surprises
```

→ verify (owner): read `CLAUDE.md` and confirm the block appears under `Gate: Delete / Replace File`
- Note: This step is OWNER-APPLY. The implementer drafts the text; the owner decides whether to merge it into `CLAUDE.md`.

---

**11.** Append a `### Post-Action Self-Validation` subsection to the `Gate: Modify Core Config` block in `CLAUDE.md` (same OWNER-APPLY rule):

```markdown
### Post-Action Self-Validation — Modify Core Config
[ ] `git diff <config-file>` shows ONLY the lines specified in the plan — no extra whitespace changes, no unrelated deletions
[ ] The config file still parses: run `python -c "import yaml; yaml.safe_load(open('<file>'))"` for YAML, or `node -e "require('./<file>')"` for JSON/JS
[ ] `git log --oneline -1` shows the commit message matches the change
```

→ verify (owner): read `CLAUDE.md` and confirm the block appears under `Gate: Modify Core Config`
- depends on: step 10 (establishes the post-validation block pattern)
- Note: OWNER-APPLY.

---

--- PHASE GATE: Plan → Implement ---
[ ] Deliverable exists: `docs/plans/2026-04-18-loki-skills-cli-impl.md` committed on `steal/loki-skills-cli`
[ ] Acceptance criteria met: 11 steps, each with action verb + specific target + verify command; no banned phrases
[ ] No open questions: 7 assumptions documented above; OWNER-APPLY steps 10-11 clearly flagged
[ ] Owner review: **required** — steps 10-11 touch `CLAUDE.md` (core config); owner decides whether to apply

---

## Non-Goals

- **No vault/`ψ/` setup** — Orchestrator already has `.remember/` and `SOUL/private/`; a second vault layer would double-map state.
- **No MCP oracle integration** — `oracle_learn()` and `oracle_trace()` are loki-specific. Orchestrator's memory system is file-based; MCP is a future consideration.
- **No Bun CLI installer** — the 172-LOC `src/cli.ts` distribution mechanism is irrelevant for a single-repo setup.
- **No EIP-191 signed posts** — out of scope for single-owner context.
- **No `/feel` emotion log** — low ROI, owner-deferred.
- **No `/birth` child-repo spawning** — Orchestrator doesn't spawn child repos today.
- **No hook for auto-rewriting `source_version:`** — the steal report mentioned a pre-commit hook; this plan uses a manual initial stamp. Hook automation is a follow-up task.
- **No Thai-language skill descriptions** — owner uses Chinese; description language change is a cosmetic follow-up.

## Rollback

All changes are new markdown files or appended sections. No existing logic is altered in a way that breaks existing skills.

If a step produces bad output:

1. `git diff` to see exactly what changed.
2. For new files (step 1): `rm .claude/skills/awaken/SKILL.md` — no downstream consumers yet.
3. For appended sections (steps 3, 5): the section is a pure addition at the end of the file; delete from the appended heading to EOF using the Edit tool.
4. For patch to `steal/SKILL.md` (step 4): revert only the three new lines using the Edit tool — the rest of the file is unchanged.
5. For watermark additions (steps 7-9): each SKILL.md receives exactly two new lines; revert by deleting those two lines with the Edit tool.
6. Steps 10-11 are OWNER-APPLY and never touch files in this plan's scope — no rollback needed here.

There is no state machine, no database migration, and no compiled artifact. Every change is reversible in under 2 minutes with a targeted Edit call.
