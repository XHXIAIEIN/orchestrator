# Session Handoff — prompt-language-coach Phase 5+6 finisher

**Date:** 2026-04-26
**Origin handoff:** `SOUL/public/prompts/session_handoff_worktree_pipeline_phase_c.md` session 8 (Batch A closeout — closed eureka / tlotp-monorepo / x1xhlol-system-prompts).
**Master plan:** `docs/superpowers/plans/2026-04-19-worktree-pipeline-closure.md`
**Topic plan:** `.claude/worktrees/steal-prompt-language-coach/docs/plans/2026-04-18-prompt-language-coach-impl.md`

---

## Goal (no menu)

Drive `prompt-language-coach` from "Phase 1+2+3+4 done" to **MERGE-ready** by completing Phase 5 (2 steps) + Phase 6 (2 steps) = **4 step-commits total**, then add the standard `docs(plan): prompt-language-coach — completion log` close-out commit. After that, this topic is mechanically Phase D-eligible in the next merge round.

This session does **only the finisher dispatch + receipt**. It does NOT do Phase D (merge) — D is a separate session (per CLAUDE.md "Phase Separation: One Phase Per Session").

---

## State (verified at session-8 close)

```
worktree:  .claude/worktrees/steal-prompt-language-coach
branch:    steal/prompt-language-coach
HEAD:      9215530 feat(steal/prompt-language-coach): Phase 4 — create reusable triviality_filter.md snippet
ahead:     5 commits (f7d2f52 → 9215530)
dirty:     none
```

Commit chain so far:
- `f7d2f52` docs(steal): R80 prompt-language-coach steal report
- `556b871` docs(plan): implementation plan for prompt-language-coach steal
- `2fd1449` Phase 1 — `SOUL/tools/marker_upsert.py` tool
- `2dfc64f` Phase 2 — ambient upsert in `session-start.sh`
- `63316b8` Phase 3 — permanence reminder in `post-compact.sh`
- `9215530` Phase 4 — `SOUL/public/prompts/triviality_filter.md` snippet

---

## Scope — exactly 4 steps + 1 close-out commit

Per topic plan (lines 188-265), Phase 5+6 = steps 7-10:

| Step | Phase | Action | Verify |
|---|---|---|---|
| 7 | 5 | Insert triviality-filter reference block in **verification-spec/SKILL.md** AND **verification-check/SKILL.md** (see ⚠ below — original plan said `verification-gate/SKILL.md` but that skill has been split since the plan was written). Use the same `<!-- triviality-filter:start --> ... <!-- triviality-filter:end -->` block from the plan. Insert near the top, after frontmatter and protocol heading, before the main "IRON LAW" / first major content paragraph. | `grep -c 'triviality-filter:start' .claude/skills/verification-spec/SKILL.md` → `1`; `grep -c 'triviality-filter:start' .claude/skills/verification-check/SKILL.md` → `1` |
| 8 | 5 | Insert the same block in **`.claude/skills/steal/SKILL.md`** before the first `##` heading. ⚠ NOTE: SKILL.md was rewritten to a 22-line `@import` shell during session 8's tlotp merge (`dfe78fb`). The first `##` doesn't exist anymore — the file ends with 5 `@skills/steal/sections/...` lines. Insert the block right before the `# Steal — Systematic Knowledge Extraction` H1, OR right after the H1 + intro paragraphs and before the `Core mindset` bullets. Pick the same anchoring you used in step 7 for consistency. | `grep -c 'triviality-filter:start' .claude/skills/steal/SKILL.md` → `1` |
| 9 | 6 | End-to-end verify: run `session-start.sh`, confirm `~/.claude/CLAUDE.md` contains the `orchestrator:ambient:start` marker block + hook output ≤ 10 lines. | Hook output line count + grep for marker on `~/.claude/CLAUDE.md` |
| 10 | 6 | `marker_upsert.py` idempotency: run upsert twice, assert exactly 1 marker block in CLAUDE.md. | Python one-liner from plan line 254-265 — must print `IDEMPOTENT PASS` |

After all 4 step-commits land, add a 5th commit:

```
docs(plan): prompt-language-coach — completion log
```

with the standard table appended to the topic plan documenting steps 7-10 outcomes (matches how `eureka` / `tlotp-monorepo` / `x1xhlol-system-prompts` closed out — see those plans for the table shape).

---

## Discipline (non-negotiable)

- **Commit-per-step**: Each of steps 7/8/9/10 → its own commit. Subject pattern matches the existing chain: `feat(steal/prompt-language-coach): Phase <N> — <step description>`.
- **Verification command must run** after each step, with output captured in the commit body or session log. No "looks right, ship it".
- **Tool budget ceiling = 25-30 tool uses for the dispatched finisher** (per session-6 lesson). 4 steps with verify commands is comfortably under that.
- **Worktree isolation**: dispatch with `isolation: "worktree"` so the finisher gets an isolated copy. The finisher's prompt must start with `[STEAL]` (dispatch-gate hook requirement).
- **Don't touch other topics**. r38 stays SKIP. flux/generic-agent/memto/millhouse stay untouched this session.

---

## Dispatch prompt for the finisher

Use the engineer subagent. Pass `isolation: "worktree"`. Brief verbatim:

```
[STEAL] Finish prompt-language-coach Phase 5+6 (4 steps) → MERGE-ready.

Worktree: .claude/worktrees/steal-prompt-language-coach (branch: steal/prompt-language-coach, HEAD 9215530).
Plan: docs/plans/2026-04-18-prompt-language-coach-impl.md (steps 7-10, lines 188-265).

Critical heads-up:
- Plan step 7 names `verification-gate/SKILL.md`, but that skill was split into `verification-spec/SKILL.md` + `verification-check/SKILL.md` on 2026-04-26 (commit 5a66a7b). Insert the triviality-filter block into BOTH new SKILL files. Use a sensible anchor (after frontmatter + first heading, before main protocol body) and keep the anchor consistent.
- Plan step 8 targets `.claude/skills/steal/SKILL.md`, which was rewritten during the session-8 tlotp merge to a 22-line `@import` shell. The original "first `##` heading" anchor is gone. Insert the triviality-filter block before the H1 OR right after the H1 + intro, before the `Core mindset` bullets — same anchor convention you chose in step 7.

Discipline:
- One commit per step (4 step-commits + 1 completion-log commit = 5 commits total).
- Subject format: `feat(steal/prompt-language-coach): Phase <N> — <action>`.
- Run each step's verify command and capture the output. Do NOT skip verification.
- After step 10 passes, append the Phase 5+6 completion table to the topic plan and commit as `docs(plan): prompt-language-coach — completion log`.
- Do not touch any other topic, do not switch off the steal/prompt-language-coach branch, do not push.

Done = HEAD on steal/prompt-language-coach is 5 commits ahead of 9215530, worktree clean, all 4 verify commands passed.
```

---

## After the finisher returns

1. Read its result. Verify in the main tree (not the worktree) that:
   - `git -C .claude/worktrees/steal-prompt-language-coach log --oneline 9215530..HEAD` shows 5 new commits ending in `docs(plan): prompt-language-coach — completion log`.
   - `git -C .claude/worktrees/steal-prompt-language-coach status --porcelain` is empty.
2. Append a "session 9" entry to `SOUL/public/prompts/session_handoff_worktree_pipeline_phase_c.md` documenting the dispatch + outcome (matches session-7 / session-8 entry shape).
3. **Do NOT do Phase D in this session** — separate session per CLAUDE.md phase rule.
4. Write the next directive: which Batch B topic comes next. Suggested order by remaining-scope ascending: `millhouse` Phase E+F+G → `flux-enchanted` Phase 4+5 (after plan-path patch) → `generic-agent` Phase 6+7+8 (Phase 8 needs owner-review gate first) → `memto` (blocked on `indexer.py` bug — needs separate detour first). Pick the next topic explicitly, name it in absolute terms, no menu.

---

## Out of scope this session

- r38-sandbox-retro (governance code, owner-decided SKIP).
- Phase D merges of any topic, including plc once it's MERGE-ready.
- Cleanup of session-2's `.trash/2026-04-19-flux-enchanted-tree-mismatch/` (still pending owner disposition).
- Session-8's `.trash/2026-04-26-batch-a-closeout/_tmp_overlap/` (scratch from D2 section split — owner can prune at leisure).
