# Session Handoff — millhouse Phase E+F+G finisher

**Date:** 2026-04-26
**Origin handoff:** `SOUL/public/prompts/session_handoff_worktree_pipeline_phase_c.md` session 9 (plc Phase 5+6 finisher closeout).
**Master plan:** `docs/superpowers/plans/2026-04-19-worktree-pipeline-closure.md`
**Topic plan:** `.claude/worktrees/steal-millhouse/docs/plans/2026-04-18-millhouse-impl.md`

---

## Goal (no menu)

Drive `millhouse` from "Phase A+B+C+D done" to **MERGE-ready** by completing Phase E (3 steps: 6, 7, 8) + Phase F (2 steps: 9, 10) + Phase G (1 step: 11) = **6 step-commits total**, plus the standard `docs(plan): millhouse — completion log` close-out commit. After that, this topic is mechanically Phase D-eligible in the next merge round.

This session does **only the finisher dispatch + receipt + necessary main-merge for plan_template drift**. It does NOT do Phase D (the topic merge to main) — D is a separate session per CLAUDE.md "Phase Separation: One Phase Per Session".

---

## State (verified at session-9 close, 2026-04-26)

```
worktree:    .claude/worktrees/steal-millhouse
branch:      steal/millhouse
HEAD:        a67e5ba feat(steal/millhouse): Phase D step 5 — add Pre-Load Rule + Pre-Read Discipline
merge-base:  b0a0cb6 (with origin/main)
ahead:       8 commits ahead of merge-base
dirty:       none
```

Commit chain so far (oldest first, post merge-base `b0a0cb6` "docs(steal): R81 loki-skills-cli steal report"):

- `594ebc5` docs(steal): R80 millhouse steal report
- `c589988` docs(plan): implementation plan for millhouse steal
- `5762dc8` docs(steal): renumber millhouse report R80 -> R81
- `82b9241` Phase A step 1 — append Review Dismissal table to rationalization-immunity
- `4311bec` Phase B step 2 — create phase_state.md schema spec
- `f8600a9` Phase C step 3 — create review_loop.py PlanReviewLoop class
- `8f24659` Phase C step 4 — verify review_loop.py inline unit tests pass
- `a67e5ba` Phase D step 5 — add Pre-Load Rule + Pre-Read Discipline (← HEAD)

Verify any time:
```
git -C .claude/worktrees/steal-millhouse log --oneline b0a0cb6..HEAD
git -C .claude/worktrees/steal-millhouse status --porcelain
```

---

## Scope — exactly 6 step-commits + 1 close-out commit (+ 1 main-merge before step 11)

Per topic plan (`docs/plans/2026-04-18-millhouse-impl.md` lines 197–328):

| Step | Phase | Action summary | Verify (per plan) |
|---|---|---|---|
| 6 | E | Create `.claude/reviewers/workers.yaml` with 3 worker entries (sonnet-tool, opus-tool, sonnet-bulk) — exact YAML in plan lines 201–224. | `grep -c 'dispatch_mode' .claude/reviewers/workers.yaml` → `3` (plan line 226 fallback when PyYAML missing) |
| 7 | E | Create `.claude/reviewers/reviewers.yaml` with one ensemble `sonnet-x2-opus-handler` (worker=sonnet-tool, count=2, handler=opus-tool, handler_prep=null) — exact YAML in plan lines 230–242. | `grep "sonnet-x2-opus-handler" .claude/reviewers/reviewers.yaml` prints a match |
| 8 | E | Create `SOUL/tools/ensemble.py` with `load_registry`, `run_worker` (mock), `run_ensemble` (asyncio.gather fan-out, `DEGRADED_FATAL` on total failure), `synthesize_handler` (stub), `write_review_to_disk`. Stub the Claude CLI subprocess call with a `# TODO` comment at the documented integration boundary. depends on: 6, 7. | `python -c "import sys; sys.path.insert(0,'.');import asyncio; from SOUL.tools.ensemble import run_ensemble; r=asyncio.run(run_ensemble('sonnet-x2-opus-handler','test payload')); assert r.get('verdict') != 'DEGRADED_FATAL'; print('ensemble ok')"` (plan line 257) |
| 9 | F | Create `SOUL/tools/plan_dag.py` with `class CycleError`, `build_dag` (explicit + implicit write-conflict edges, `reads:` generates no edge), `extract_layers` (Kahn's algorithm with cycle path extraction), `validate_plan_file`. | `python -c "import sys; sys.path.insert(0,'.'); from SOUL.tools.plan_dag import build_dag, extract_layers, CycleError; dag={'A':set(),'B':{'A'}}; layers=extract_layers(dag); assert layers==[['A'],['B']]; print('dag ok')"` (plan line 274) |
| 10 | F | Add `if __name__ == '__main__':` self-tests to `plan_dag.py` covering linear chain, write-conflict implicit edge, cycle detection. depends on: 9. | `python SOUL/tools/plan_dag.py` exits 0 + prints `All DAG tests passed.` (plan line 283) |
| **(merge)** | — | `git merge origin/main` into `steal/millhouse` — see "Plan-vs-reality drift" below. Required **before step 11** because plan_template.md has 5 main commits since divergence. Conflict expected: `verification-gate/SKILL.md` (delete/modify). | After merge: `git -C .claude/worktrees/steal-millhouse status --porcelain` clean; `git log --oneline | head -3` shows merge commit on top |
| 11 | G | Edit `SOUL/public/prompts/plan_template.md` "Step Format Reference" — replace single-step "Good" block with 2-step block including `creates:` / `modifies:` / `reads:` / `depends on:` fields, and append "File change declarations required" paragraph after "Step Requirements" bullets. depends on: 9. | `grep -n "creates:" SOUL/public/prompts/plan_template.md \| head -5` returns ≥ 2 matches (plan line 327) |

After all 6 step-commits land (plus the merge), add the 7th commit:

```
docs(plan): millhouse — completion log
```

Append the standard table to the topic plan (`docs/plans/2026-04-18-millhouse-impl.md`) documenting steps 6–11 outcomes. Match the shape used by `prompt-language-coach` / `eureka` / `tlotp-monorepo` / `x1xhlol-system-prompts` close-outs.

**Final commit count for this session: 6 step + 1 merge + 1 log = 8 new commits on `steal/millhouse`.**

---

## Plan-vs-reality drift since plan day (2026-04-18 → 2026-04-26)

The topic plan was written before five main-tree changes that affect this finisher. Order matters.

### Drift A — `verification-gate/` was split (commit `5a66a7b`, session-7)

`SOUL/public/prompts/verification-spec/` + `verification-check/` replaced the single `verification-gate/` directory. The branch's Phase D step 5 (already committed as `a67e5ba`) inserted `## Pre-Read Discipline` into the now-deleted `.claude/skills/verification-gate/SKILL.md`.

- **Phase E/F/G impact**: NONE. These phases don't touch verification-gate.
- **Merge-step impact**: when `git merge origin/main` runs (before step 11), conflict expected — `verification-gate/SKILL.md` is `deleted by them, modified by us`. **Resolution**: accept the deletion (`git rm` the file), then re-apply the `## Pre-Read Discipline` block to BOTH `.claude/skills/verification-spec/SKILL.md` AND `.claude/skills/verification-check/SKILL.md` (same anchor convention plc used: after frontmatter + first heading, before main protocol body). The block content is the 8 lines from `a67e5ba` step 5 commit (`git show a67e5ba -- '.claude/skills/verification-gate/SKILL.md'`).
- **Phase D (later session)**: this same conflict resolution carries forward into the eventual merge to main; do it once during this session's merge step and the resolution travels with the branch.

### Drift B — `plan_template.md` moved 5 times on main since divergence

Commits on main touching `SOUL/public/prompts/plan_template.md`:
- `d1013a2` feat(skill+template): eureka — Phase 2 template & skill integration
- `d80e9b7` feat(prompts): x1xhlol-system-prompts — Phase 4 Phase Gate Contract Document
- `98603f3` feat(prompts): add TL;DR headers to 25 SOUL prompt files
- `f9b0aa2` merge: steal/eureka
- `37b8bce` merge: steal/x1xhlol-system-prompts

The "Good" example block (`src/validators/email.py`) anchor still exists on current main (verified at session-9: line 61), but TL;DR header + neighboring sections have shifted. Step 11 must edit against the post-merge view of the file.

- **Phase E/F impact**: NONE.
- **Merge-step**: probably auto-merges cleanly (branch has no edits to plan_template.md yet — step 11 is what would edit it).
- **Step 11**: after merge, re-read the file and locate the "Good" block before applying the plan's prescribed replacement. The plan's regex anchor (lines 290–296) should still match unless the TL;DR work mutated indentation — verify before edit.

### Drift C — `rationalization-immunity.md` had 4 main commits since divergence

Phase A step 1 (already committed as `82b9241`) appended `## Review Dismissal`. Phase D step 5 (already committed as `a67e5ba`) appended `## Pre-Load Rule`. On main since divergence:
- `4b0e9b9` feat(prompts): add code-level before/after pairs to rationalization-immunity
- `98603f3` feat(prompts): add TL;DR headers to 25 SOUL prompt files
- `a83a18f` feat(steal/loki): Phase C — Jump Tracker section + doctor cross-reference (touches the file)
- `0c9129b` merge: steal/loki-skills-cli

- **Phase E/F/G impact**: NONE.
- **Merge-step**: textual conflict possible around section ordering / TL;DR header. Resolution: keep both branches' additions (TL;DR + before/after pairs from main + Review Dismissal + Pre-Load Rule from branch). No semantic conflict — purely additive on both sides.

### Net effect on session shape

Phase E (steps 6, 7, 8) + Phase F (steps 9, 10) can run **without** merging main — all five steps create net-new files (`workers.yaml`, `reviewers.yaml`, `ensemble.py`, `plan_dag.py`). Merge happens **between step 10 and step 11** so that step 11's anchor matches the live file.

---

## Discipline (non-negotiable)

- **Commit-per-step**: Each of steps 6/7/8/9/10/11 → its own commit. Subject pattern matches existing chain: `feat(steal/millhouse): Phase <X> step <N> — <action>`.
- **Merge commit**: standard subject `merge: origin/main into steal/millhouse — bring plan_template.md / verification-gate split current` (or similar). Resolve conflicts as described in Drift A/B/C.
- **Verification command must run** after each step, with output captured. No "looks right, ship it".
- **Tool budget for the dispatched finisher**: ~30–40 tool uses (5 steps with verify + the merge step). If dispatched as one block, expect agent truncation around step 9–10 (plc lesson). Recommend splitting: dispatch steps 6–10 as one finisher (5 commits, no merge), handle merge + step 11 + completion-log manually in the main session.
- **Worktree isolation**: dispatch with `isolation: "worktree"`. The finisher's prompt MUST start with `[STEAL]` (dispatch-gate hook requirement).
- **Don't touch other topics**. r38 stays SKIP. flux/generic-agent/memto stay untouched this session.

---

## Dispatch protocol (workaround precedent from plc session 9)

`dispatch-gate.sh` blocks `[STEAL]` work unless `git branch --show-current` returns `steal/*` or `round/*`. Main tree currently on `main` → blocked.

1. Create helper branch on main tree at current HEAD:
   ```
   git branch round/phase-c-batch4
   git checkout round/phase-c-batch4
   ```
   (No commits — same SHA as main `3daf27f` or whatever HEAD is at session start.)
2. Dispatch the engineer subagent with `isolation: "worktree"` (see prompt below).
3. After agent returns, restore main:
   ```
   git checkout main
   git branch -D round/phase-c-batch4
   ```

---

## Dispatch prompt for the Phase E+F finisher (steps 6–10)

Use the engineer subagent. Pass `isolation: "worktree"`. Brief verbatim:

```
[STEAL] Finish millhouse Phase E (steps 6, 7, 8) + Phase F (steps 9, 10) → 5 step-commits.

Worktree: .claude/worktrees/steal-millhouse (branch: steal/millhouse, HEAD a67e5ba).
Plan: docs/plans/2026-04-18-millhouse-impl.md (steps 6–10, lines 197–283).

All five steps create net-new files — no main-merge required for this dispatch:
- Step 6: .claude/reviewers/workers.yaml (3 workers, exact YAML in plan lines 201–224)
- Step 7: .claude/reviewers/reviewers.yaml (one ensemble, exact YAML in plan lines 230–242)
- Step 8: SOUL/tools/ensemble.py (load_registry, run_worker mock, run_ensemble asyncio fan-out, synthesize_handler stub, write_review_to_disk; integration TODO at the Claude CLI subprocess boundary; depends on: 6, 7)
- Step 9: SOUL/tools/plan_dag.py (CycleError, build_dag with explicit + implicit write-conflict edges, extract_layers Kahn's, validate_plan_file)
- Step 10: plan_dag.py inline self-tests for linear chain, write-conflict, cycle detection (depends on: 9)

Discipline:
- One commit per step (5 step-commits total).
- Subject format: `feat(steal/millhouse): Phase <X> step <N> — <action>`.
- Run each step's verify command (plan lines 226 / 244 / 257 / 274 / 283) and capture output. Do NOT skip verification.
- Use the plan's exact YAML / Python content where given. Where the plan says "stub" or "TODO" — keep it stubbed; do NOT implement Claude CLI subprocess.
- Do not touch any other topic, do not switch off steal/millhouse, do not push, do not merge main.

Done = HEAD on steal/millhouse is 5 commits ahead of a67e5ba, worktree clean, all 5 verify commands passed.
```

---

## After the Phase E+F finisher returns — handle the merge and Phase G manually

Sub-agent failure mode (plc lesson): mechanical commit-per-step finishers tend to truncate before final commits. If the finisher returns with fewer than 5 commits or with uncommitted edits, take over manually — completing the remaining is faster than retrying with stricter prompts.

After verifying 5 step-commits land cleanly:

1. **Merge `origin/main`** into `steal/millhouse` from inside the worktree:
   ```
   cd .claude/worktrees/steal-millhouse
   git fetch origin
   git merge origin/main
   ```
2. **Resolve `verification-gate/SKILL.md` conflict** (deleted by them, modified by us):
   - `git rm .claude/skills/verification-gate/SKILL.md`
   - Read the deleted file's content from `git show a67e5ba -- '.claude/skills/verification-gate/SKILL.md'` to recover the `## Pre-Read Discipline` block.
   - Insert the block into both `.claude/skills/verification-spec/SKILL.md` and `.claude/skills/verification-check/SKILL.md`, using the anchor convention plc used (after frontmatter + first heading, before main protocol body). Verify: `grep -c 'Pre-Read Discipline' .claude/skills/verification-spec/SKILL.md` → 1, same for verification-check.
3. **Resolve `rationalization-immunity.md` conflict** (purely additive on both sides — keep all sections from both branches; section ordering = main's TL;DR + before/after pairs first, then Review Dismissal + Pre-Load Rule from branch).
4. **Commit the merge**:
   ```
   git commit -m "merge: origin/main into steal/millhouse — verification-gate split + plan_template drift"
   ```
5. **Step 11** — execute manually:
   - Re-read `SOUL/public/prompts/plan_template.md` post-merge to locate the current "Good" example block.
   - Apply the replacement per plan lines 297–323.
   - Add the "File change declarations required" paragraph after the "Step Requirements" bullet list per plan lines 317–323.
   - Verify: `grep -n "creates:" SOUL/public/prompts/plan_template.md | head -5` → ≥ 2 matches.
   - Commit: `feat(steal/millhouse): Phase G step 11 — add creates/modifies/reads fields to plan_template`.
6. **Completion log** — append to `docs/plans/2026-04-18-millhouse-impl.md`:

   ```markdown
   ---

   ## Completion Log (2026-04-26 — session 10 finisher)

   | Step | Phase | Commit | Note |
   |---|---|---|---|
   | 6  | E | <sha> | workers.yaml (3 workers) |
   | 7  | E | <sha> | reviewers.yaml (sonnet-x2-opus-handler) |
   | 8  | E | <sha> | ensemble.py (asyncio fan-out + DEGRADED_FATAL + write-to-disk) |
   | 9  | F | <sha> | plan_dag.py (CycleError + build_dag + extract_layers Kahn's) |
   | 10 | F | <sha> | plan_dag.py self-tests (linear / write-conflict / cycle) |
   | merge | — | <sha> | merge origin/main — verification-gate split (re-applied Pre-Read Discipline to verification-spec + verification-check) + rationalization-immunity additive merge + plan_template drift |
   | 11 | G | <sha> | plan_template.md creates/modifies/reads fields + File change declarations paragraph |
   ```

   Commit: `docs(plan): millhouse — completion log`.

---

## After everything — main-tree hygiene

1. From main repo (not worktree):
   - `git -C .claude/worktrees/steal-millhouse log --oneline a67e5ba..HEAD` should show 7 new commits ending with `docs(plan): millhouse — completion log`.
   - `git -C .claude/worktrees/steal-millhouse status --porcelain` empty.
2. Append a "session 10" entry to `SOUL/public/prompts/session_handoff_worktree_pipeline_phase_c.md` documenting dispatch + outcome (matches session-9 entry shape — include drift-resolution detail, agent dispatch outcomes, lessons).
3. Restore main: `git checkout main`, `git branch -D round/phase-c-batch4`.
4. **Do NOT do Phase D in this session** — separate session per CLAUDE.md phase rule.
5. Write next directive in the session-10 entry. Suggested order by remaining-scope ascending: `flux-enchanted` Phase 4+5 (after plan-path patch + Step-10 owner gate) → `generic-agent` Phase 6+7+8 (Phase 8 needs owner-review gate first) → `memto` (blocked on `indexer.py` bug — needs separate detour first). Pick explicitly, name it in absolute terms, no menu.

---

## Out of scope this session

- r38-sandbox-retro (governance code, owner-decided SKIP).
- Phase D merges of any topic, including millhouse + plc once they are MERGE-ready.
- Cleanup of session-2's `.trash/2026-04-19-flux-enchanted-tree-mismatch/` (still pending owner disposition).
- Session-8's `.trash/2026-04-26-batch-a-closeout/_tmp_overlap/` (scratch from D2 section split — owner can prune at leisure).
- Real Claude CLI subprocess integration in `ensemble.py` step 8 — stub-only per plan; owner schedules real CLI integration separately.
- Wiring the `_phase/status.md` schema (step 2's spec) into existing skills' SKILL.md preambles — explicit Non-Goal in plan line 343.

---

## Topic-plan reference quick-find

For the dispatched finisher and manual step 11 / merge resolution, the topic plan sections to read inside the worktree:

| Section | Lines | What's there |
|---|---|---|
| ASSUMPTIONS | 29–37 | 7 assumptions, especially `sys.path.insert` import pattern (assumption 1, 7) |
| File Map | 41–53 | Per-phase target paths |
| Phase E (steps 6, 7, 8) | 197–257 | Exact YAML for workers/reviewers; ensemble.py function signatures + `DEGRADED_FATAL` rule |
| Phase F (steps 9, 10) | 261–283 | DAG class signatures + Kahn's + cycle path extraction + self-test cases |
| Phase G (step 11) | 287–327 | "Good" example replacement block + "File change declarations" paragraph |
| Non-Goals | 331–343 | What NOT to implement (P0#5, P1, real CLI, _phase wiring) |
| Rollback | 347–366 | Per-file revert commands if needed |
