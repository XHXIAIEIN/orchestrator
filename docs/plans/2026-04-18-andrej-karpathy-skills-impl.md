# Plan: R76 Karpathy Skills — Remaining P1 Implementations

## Status

**Case B — Forward plan for unimplemented P1 items.**

### What Was Already Done (do not re-implement)

| Commit | Item | Target File |
|--------|------|-------------|
| `d34b6dc` | P0 #1 Simplicity Pre-Gate — Gate 1 checklist item "Simplicity pre-check" | `SOUL/public/prompts/plan_template.md` |
| `d34b6dc` | P0 #2 Declarative Uplift — `declarative_uplift` type #6 in clarification gate | `SOUL/public/prompts/clarification.md` |
| `10c7d74` | P0 companion — Pre-Flight ASSUMPTIONS section in verification-gate | `.claude/skills/verification-gate/SKILL.md` |

All three P0s are done. This plan covers the **three P1 items** from steal report `docs/steal/R76-karpathy-guidelines-steal.md`.

---

## Goal

Implement three P1 patterns from R76: structured `[LEARN]` extraction tags in `.remember/` workflow, per-file `TL;DR` summary lines for context-constrained dispatch, and code-level before/after teaching pairs in rationalization-immunity. Done when: (1) `.remember/core-memories.md` documents `[LEARN]` format, (2) every file in `SOUL/public/prompts/` has a one-line `<!-- TL;DR: … -->` header tag, (3) `rationalization-immunity.md` has a "Code-Level Examples" section with 3+ before/after pairs.

## Context

Source: `docs/steal/R76-karpathy-guidelines-steal.md` § "P1 — Worth Doing"

- **P1-A: Self-Correction Loop with Approval Gate** — rohitg00 pattern. Agent marks errors with `[LEARN] [Category]: rule` during a session. Owner approves at review time. Approved items get promoted to `core-memories.md`. Not a SQLite backend (overkill at current scale); markdown is fine. Key lesson from rohitg00's v1 failure: no auto-capture without approval — one week of auto-capture produced contradictory rules.
- **P1-B: 100-Token Principle Card** — forrestchang pattern. Core constraint files get a compressed summary (<100 tokens) that can be injected into subagent dispatch instead of the full file. Current problem: large dispatch either gets the full ~200-line prompt (expensive) or nothing.
- **P1-C: Before/After Teaching Pairs** — forrestchang's EXAMPLES.md pattern. LLMs respond better to behavior examples than rule declarations. Current `rationalization-immunity.md` has only a mindset table, no code-level before/after pairs showing what bad vs correct code looks like.

## ASSUMPTIONS

1. The `.remember/` directory exists at the repo root and `core-memories.md` is the canonical long-term memory file. If it does not exist, Step 1 creates it.
2. `SOUL/public/prompts/` is the complete set of prompts that need TL;DR headers — no additional prompts exist in subdirectories.
3. The `<!-- TL;DR: … -->` HTML comment format is the correct choice: it is invisible in rendered markdown, survives copy-paste, and is grep-able.
4. "Subagent dispatch" means the `Agent tool call` flow described in `CLAUDE.md` — the TL;DR mechanism targets that injection point, not a runtime API call.
5. The before/after pairs for `rationalization-immunity.md` should target the most common rationalization categories: Testing/Verification, Reading Before Changing, and Git Operations (these three have the most historical violations based on existing entries).
6. `[LEARN]` entries should NOT auto-promote — all promotion requires owner to move the line from `today-*.md` to `core-memories.md` manually. Auto-promotion is explicitly forbidden (rohitg00 v1 failure).

---

## File Map

- `D:/Users/Administrator/Documents/GitHub/orchestrator/.remember/core-memories.md` — Modify (add `[LEARN]` format documentation block)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/plan_template.md` — Modify (add `<!-- TL;DR: … -->` header)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/clarification.md` — Modify (add TL;DR header)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/rationalization-immunity.md` — Modify (add TL;DR header + Code-Level Examples section)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/verification-gate.md` — Modify IF exists (add TL;DR header); skip otherwise (SKILL.md is the canonical file)
- All remaining 21 files in `SOUL/public/prompts/` — Modify (add TL;DR header each)

---

## Steps

### Phase 1: P1-A — [LEARN] Format in .remember/

**Step 1.** Read `.remember/core-memories.md` (full file) to understand current format and locate the best insertion point for the `[LEARN]` protocol block.
→ verify: `wc -l .remember/core-memories.md` returns non-zero; no error.

**Step 2.** Append a `## [LEARN] Protocol` section to `.remember/core-memories.md` with the following exact content (verbatim, no paraphrase):

```markdown
## [LEARN] Protocol

When a session produces a corrected behavior or a discovered rule, the executor writes:

```
[LEARN] [Category]: <rule in one sentence, imperative mood>
```

Categories: `Testing` | `Reading` | `Git` | `Context` | `Planning` | `Execution` | `Memory`

Rules appear in `today-*.md` entries automatically. Promotion requires owner action:
1. Owner copies the `[LEARN]` line from `today-*.md` to this file under the matching category header.
2. Owner removes the raw `[LEARN]` tag, leaving just the rule text.
3. Auto-promotion is FORBIDDEN — rohitg00 v1 produced contradictory rules in one week of auto-capture.

### Conflict resolution
Same category, conflicting rules → keep both with ISO timestamps. Owner resolves at next review.
Higher-evidence rule wins: verbatim > artifact > impression (matches evidence tier system).
```

→ verify: `grep -n "\[LEARN\]" .remember/core-memories.md` returns at least 3 lines (the section heading line, the format block line, and the "Auto-promotion is FORBIDDEN" line).
- depends on: step 1

**Step 3.** Read `CLAUDE.md` in the repo root and confirm it already references `.remember/` — if not, add one sentence to the "Memory Evidence Grading" section: "During sessions, mark discovered rules with `[LEARN] [Category]: rule` — see `.remember/core-memories.md` for promotion protocol."
→ verify: `grep -n "\[LEARN\]" CLAUDE.md` returns at least 1 line.
- depends on: step 2

--- PHASE GATE: P1-A → P1-B ---
- [ ] Deliverable exists: `.remember/core-memories.md` has `[LEARN] Protocol` section
- [ ] Format block is verbatim (grep confirms 3+ matching lines)
- [ ] CLAUDE.md references `[LEARN]` tag
- [ ] No auto-promotion mechanism added anywhere
- [ ] Owner review: not required (reversible markdown edit, <30 min)

---

### Phase 2: P1-B — 100-Token TL;DR Headers

**Step 4.** List all files in `SOUL/public/prompts/` and confirm count matches 25 files (from earlier read). For each file, determine the file's core purpose in ≤15 words.
→ verify: `ls SOUL/public/prompts/ | wc -l` returns 25.

**Step 5.** Add `<!-- TL;DR: <≤15 word summary of the file's core decision/behavior> -->` as line 1 to each of the following 25 files in `SOUL/public/prompts/`. The TL;DR must describe what decision the file governs, not what it is called. Full list with TL;DR text:

| File | TL;DR line |
|------|------------|
| `analyst.md` | `<!-- TL;DR: Synthesize findings into structured insight cards; never embed raw data. -->` |
| `batch_worker.md` | `<!-- TL;DR: Process items in parallel batches; report failures without halting batch. -->` |
| `chat.md` | `<!-- TL;DR: Conversational persona rules; tone, language, roast-first help-second. -->` |
| `clarification.md` | `<!-- TL;DR: Ask 0-1 questions; auto-convert imperatives to declarative criteria. -->` |
| `cognitive_modes.md` | `<!-- TL;DR: Four thinking modes (explore/plan/execute/review); switch on task type. -->` |
| `collaboration_modes.md` | `<!-- TL;DR: Three collaboration modes (plan/execute/review); scope and budget per mode. -->` |
| `compact_template.md` | `<!-- TL;DR: Compress session context; drop noise, keep decisions and blockers. -->` |
| `dag_orchestration.md` | `<!-- TL;DR: Build dependency graphs; parallelize independent nodes, gate on outputs. -->` |
| `dedup_matrix.md` | `<!-- TL;DR: Detect duplicate rules or memories; merge by evidence tier. -->` |
| `disk_state_loop.md` | `<!-- TL;DR: Manage disk state changes in a read-modify-write loop with rollback. -->` |
| `evaluator_fix_loop.md` | `<!-- TL;DR: Eval-driven iteration: score → fix worst issue → re-eval → repeat. -->` |
| `growth_loops.md` | `<!-- TL;DR: Identify compounding feedback loops; amplify positives, dampen negatives. -->` |
| `guardian_assessment.md` | `<!-- TL;DR: Score operation reversibility 0-100; block irreversible ops without approval. -->` |
| `insights.md` | `<!-- TL;DR: Extract non-obvious patterns from data; skip trivially obvious observations. -->` |
| `methodology_router.md` | `<!-- TL;DR: Route to correct methodology (debug/plan/audit/ship) by task type. -->` |
| `plan_template.md` | `<!-- TL;DR: All plans need Goal+FileMap+AtomicSteps+PhaseGates before first line of code. -->` |
| `profile.md` | `<!-- TL;DR: User preference profile; tone, style, working patterns observed. -->` |
| `rationalization-immunity.md` | `<!-- TL;DR: Lookup table: if inner monologue matches left column, execute right column. -->` |
| `rule_scoping.md` | `<!-- TL;DR: Scope rules to the narrowest applicable context; global rules are last resort. -->` |
| `scrutiny.md` | `<!-- TL;DR: Adversarial review mode; find the worst-case failure before shipping. -->` |
| `session_boundary.md` | `<!-- TL;DR: One phase per session; save deliverable + handoff prompt at boundary. -->` |
| `session_handoff.md` | `<!-- TL;DR: Handoff format: state + blockers + next-session startup prompt. -->` |
| `skill_routing.md` | `<!-- TL;DR: Route tasks to skills by type (bug/build/review/ship); not by keyword match. -->` |
| `synthesis_discipline.md` | `<!-- TL;DR: Synthesize across sources; never just concatenate; surface contradictions. -->` |
| `task.md` | `<!-- TL;DR: Task intake format; translate user request into executable spec. -->` |

→ verify for each file: `head -1 SOUL/public/prompts/<filename>` returns the `<!-- TL;DR:` line. Spot-check 5 files: `clarification.md`, `plan_template.md`, `rationalization-immunity.md`, `verification-gate.md` (if exists), `skill_routing.md`.
- depends on: step 4

--- PHASE GATE: P1-B → P1-C ---
- [ ] Deliverable exists: all 25 files in `SOUL/public/prompts/` have TL;DR on line 1
- [ ] Spot-check 5 files passes (grep confirms `<!-- TL;DR:` on line 1)
- [ ] TL;DR lines describe decisions, not file names
- [ ] Owner review: not required (additive, fully reversible)

---

### Phase 3: P1-C — Before/After Teaching Pairs in rationalization-immunity.md

**Step 6.** Read the full content of `SOUL/public/prompts/rationalization-immunity.md` to find the last section and the exact format of existing table rows.
→ verify: Read returns non-empty content; identify the last `##` heading line number.

**Step 7.** Append a `## Code-Level Examples` section to `SOUL/public/prompts/rationalization-immunity.md` with 5 before/after pairs targeting the three highest-violation categories (Testing/Verification, Reading Before Changing, Git Operations). Exact content:

```markdown
## Code-Level Examples

These pairs show what the rationalization looks like in actual code and diffs, not just mindset.
Format: ❌ what an LLM rationalizes into existence → ✅ what should have happened.

---

### Testing / Verification

**Rationalization**: "It's just a small change — the tests should still pass."

❌ Bad:
```python
# Changed one line in auth.py, declared done without running tests
def authenticate(user, password):
    return user.password_hash == hash(password)  # removed salt — "trivial fix"
```

✅ Correct:
```bash
# Run the exact test suite before declaring done
pytest tests/test_auth.py -v
# Read FULL output — not just "X passed"
# Investigate every warning before claiming green
```

---

### Reading Before Changing

**Rationalization**: "I've seen this pattern before — I know how it works."

❌ Bad:
```python
# Assumed function signature from the name, didn't read the body
result = validate_input(data)  # added call — turns out validate_input raises on None, not returns False
```

✅ Correct:
```bash
# Read the function before calling it
grep -n "def validate_input" src/validators.py
# Then read lines N to N+20 to see return type, exceptions, side effects
```

---

### Git Operations

**Rationalization**: "A quick reset will fix this — I'll just start clean."

❌ Bad:
```bash
git reset --hard HEAD~1  # lost 2 hours of uncommitted exploration work
```

✅ Correct:
```bash
git diff HEAD  # read what's actually different
git stash      # backup uncommitted work first
# Diagnose the specific issue from the diff
# Fix surgically — don't nuke the branch
```

---

### Scope Creep

**Rationalization**: "I'll just clean this up while I'm here — it's obviously broken."

❌ Bad:
```diff
-def process(items):
-    for i in items: do_thing(i)
+def process(items: list[Item]) -> None:  # added types
+    for i in items:
+        do_thing(i)  # added line break
+        log.debug(f"processed {i}")  # added logging — "obviously needed"
```

✅ Correct:
```diff
# Only the line the task required
-    for i in items: do_thing(i)
+    for item in items: do_thing(item)  # renamed per task requirement
# Every other line: untouched
```

---

### Completion Claims

**Rationalization**: "Based on the changes, this should work — I'm confident."

❌ Bad (in agent output):
```
I've updated the rate limiter. Based on the changes, requests should now be
limited to 100/minute. I'm confident this is correct.
```

✅ Correct (in agent output):
```
Ran: curl -s -o /dev/null -w "%{http_code}" -X POST localhost:8000/api/test
Result after 101 requests: 429 Too Many Requests
All 47 tests pass (pytest output above, 0 failures, 0 warnings).
Task complete.
```
```

→ verify: `grep -c "❌ Bad" SOUL/public/prompts/rationalization-immunity.md` returns 5.
- depends on: step 6

--- PHASE GATE: P1-C → Done ---
- [ ] Deliverable exists: `rationalization-immunity.md` has `## Code-Level Examples` section
- [ ] 5 before/after pairs present (grep confirms 5 "❌ Bad" markers)
- [ ] Each pair has a named rationalization, a bad code block, and a correct code block
- [ ] No existing table rows modified (only appended)
- [ ] Owner review: not required (additive, fully reversible)

---

## Non-Goals

- SQLite backend for memory storage — markdown + grep is sufficient at current scale (<100 entries). Revisit when `core-memories.md` exceeds 100 entries.
- Automated `[LEARN]` detection or promotion — auto-capture is explicitly forbidden.
- Changing the `verification-gate` SKILL.md — it already has the Pre-Flight ASSUMPTIONS section from commit `10c7d74`.
- Adding TL;DR to non-prompt files (SKILL.md files, constraint files) — those are active execution files, not summary-injected context.
- Implementing SkillKit cross-agent translation (P2, reference only).
- Renaming collaboration_modes to Write/Select/Compress/Isolate (P2, reference only).

## Rollback

All three phases are purely additive (append-only or prepend-only markdown edits):

- **P1-A rollback**: Delete the `## [LEARN] Protocol` block from `.remember/core-memories.md` and remove the `[LEARN]` sentence from `CLAUDE.md`. No state side-effects.
- **P1-B rollback**: `sed -i '1d' SOUL/public/prompts/*.md` removes the first line from all prompt files (removes all TL;DR headers).
- **P1-C rollback**: Delete lines from `## Code-Level Examples` to end-of-file in `rationalization-immunity.md`.

Estimated rollback time: <5 minutes per phase.
