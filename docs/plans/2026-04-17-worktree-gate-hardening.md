# Plan: Worktree-Gate Hardening — Stop Main-Repo Branch Hijacks

## Goal

`dispatch-gate.sh` and `guard.sh` block any `[STEAL]` agent dispatch or
`git checkout/switch -b steal/*` executed from the main repo's cwd
(`git rev-parse --show-toplevel` equals the repo root, not under
`.claude/worktrees/`), so the main workspace's branch + uncommitted
changes can never be hijacked again.

Verifiable outcome: from the main repo root, `git checkout -b steal/demo`
fails via guard block; from `.claude/worktrees/steal-demo/`, same command
is allowed.

## Context (what we learned this session)

- 2026-04-17 18:30-18:39: external /ralph-loop switched the main repo
  through 8 `steal/*` branches, cherry-picked and auto-committed steal
  reports, stashed our uncommitted `SOUL/tools/compiler.py` changes under
  `stash@{0}: On steal/memto: WIP: compiler on steal/memto`.
- Current `dispatch-gate.sh` only checks `git branch --show-current`. A
  main repo that got hijacked *to* `steal/foo` passes the gate —
  the pollution itself satisfies the check.
- 97c5ec8 (`feat(steal): enforce worktree isolation`) added the
  Layer-0 constraint doc and rewrote the gate error message, but the
  enforcement predicate itself was not changed.
- Uncommitted work was recovered this time via `git stash show -p >
  .trash/20260417-learnings-split/compiler.patch` + manual worktree
  + rebase + fast-forward. Owner wants automation so the next hijack
  gets blocked at the tool-call layer.

## ASSUMPTIONS (defer to owner if wrong)

- **A1** (context pack per-machine): `.claude/context/learnings/*.md` not
  being tracked is a feature — `SOUL/private/identity.md` is per-instance
  and compiler output is per-instance. This plan does NOT add any
  cross-machine sync for context packs. If owner wants multi-machine
  sync, that's a separate plan.
- **A2** (external /ralph-loop untouchable): the /ralph-loop plugin lives
  outside this repo and we do not modify its code. We only harden the
  gate at our side so any caller (loop, manual, sub-agent) is subject
  to the same check.
- **A3** (cwd check ≙ worktree check): `git rev-parse --show-toplevel`
  returning a path under `<main-repo>/.claude/worktrees/steal-*` is
  sufficient evidence of being inside a dedicated worktree. No need
  to parse `git worktree list` on every hook call.

## File Map

- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/dispatch-gate.sh` — Modify
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/guard.sh` — Modify (add Bash matcher for `git checkout -b steal/*` from main cwd)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/guard-rules.conf` — Modify (add one `block` rule)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/steal/constraints/worktree-isolation.md` — Modify (replace "Violation indicators" list with the new predicate)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/tests/hooks/test_dispatch_gate_worktree.sh` — Create (smoke test, stdin-driven)

## Steps

### Phase 1: Write the predicate

1. Add helper `is_in_main_repo()` at top of `.claude/hooks/dispatch-gate.sh`
   after line 7 (after the `INPUT=` read). Body:
   ```bash
   is_in_main_repo() {
     local top; top=$(git rev-parse --show-toplevel 2>/dev/null)
     [ -z "$top" ] && return 1                   # not in a git repo
     # Inside any worktree? git rev-parse returns the worktree root,
     # not the main repo — if path contains /.claude/worktrees/ we're OK
     case "$top" in
       */.claude/worktrees/*) return 1 ;;        # in a worktree, not main
       *) return 0 ;;                            # else in main repo
     esac
   }
   ```
   → verify: `bash -c 'source .claude/hooks/dispatch-gate.sh 2>/dev/null; declare -f is_in_main_repo'`
     prints the function body.

### Phase 2: Wire predicate into [STEAL] check

2. Replace dispatch-gate.sh lines 15-20 (the current `if [STEAL]` block)
   with a predicate that fails when BOTH conditions are true: tag is
   `[STEAL]` AND `is_in_main_repo` returns 0. Keep the branch-name check
   as a secondary fallback (catches main-repo cwd with branch hijacked
   to `steal/foo`):
   ```bash
   if echo "$PROMPT" | grep -qF '[STEAL]'; then
     if is_in_main_repo; then
       echo '{"decision":"block","reason":"[STEAL] work must run from inside .claude/worktrees/steal-<topic>, not the main repo cwd. Current cwd is main. Create a worktree: git worktree add .claude/worktrees/steal-<topic> -b steal/<topic> && cd .claude/worktrees/steal-<topic>. For sub-agent dispatch, also pass isolation: \"worktree\" in the Agent tool call."}'
       exit 0
     fi
   fi
   ```
   - depends on: step 1
   → verify (main-repo cwd, should block):
     ```bash
     echo '{"tool_input":{"prompt":"[STEAL] demo"}}' | bash .claude/hooks/dispatch-gate.sh | grep -q 'must run from inside'
     ```
   → verify (worktree cwd, should NOT block on the [STEAL] predicate):
     ```bash
     git worktree add .claude/worktrees/steal-smoke -b steal/smoke HEAD && \
       cd .claude/worktrees/steal-smoke && \
       echo '{"tool_input":{"prompt":"[STEAL] demo"}}' | bash ../../hooks/dispatch-gate.sh | grep -qv 'must run from inside'; \
       cd - && git worktree remove .claude/worktrees/steal-smoke --force && git branch -D steal/smoke
     ```

### Phase 3: Block `git checkout -b steal/*` at the Bash layer

3. Add one rule to `.claude/hooks/guard-rules.conf` after line 65
   (`git\s+checkout\s+--\s+\.` row). Use existing `block` verb:
   ```
   block	git\s+(checkout|switch)\s+-b\s+(steal|round)/	Creating steal/* or round/* branches from the main repo is banned. Use: git worktree add .claude/worktrees/<topic> -b steal/<topic>. The main workspace's branch and uncommitted work must stay untouched.
   ```
   - depends on: none
   → verify:
     `grep -c 'checkout|switch.*-b.*(steal|round)' .claude/hooks/guard-rules.conf` returns `1`.

4. Confirm `.claude/hooks/guard.sh` actually consults guard-rules.conf for
   `block` verb on Bash tool calls (read the file top-to-bottom, look for
   `block` verb handling). If guard.sh only handles `ask`, add a `block`
   branch modeled on the existing `ask` one, so the new rule becomes
   enforceable (not just advisory).
   - depends on: step 3
   → verify: `grep -n '\bblock\b' .claude/hooks/guard.sh` shows at least
     one line that emits a JSON `"decision":"block"` response.

5. If step 4 shows guard.sh already handles `block`, skip. Otherwise add
   the block handler right after the existing `ask` handler, following
   the same shape:
   ```bash
   if [ "$verb" = "block" ]; then
     echo "{\"decision\":\"block\",\"reason\":\"$message\"}"
     exit 0
   fi
   ```
   Insert at the location found in step 4's read.
   - depends on: step 4
   → verify: same as step 2 second check but using
     `echo '{"tool_input":{"command":"git checkout -b steal/demo"}}' | bash .claude/hooks/guard.sh | grep -q 'must stay untouched'`
     from the main repo root.

### Phase 4: Update the Layer-0 constraint doc

6. Rewrite `.claude/skills/steal/constraints/worktree-isolation.md`
   "Violation indicators" section (lines 34-39 of the current file). Replace
   the four-bullet list with the new machine-checkable predicate:
   ```markdown
   ## Violation indicators (machine-checked by dispatch-gate.sh + guard.sh)

   1. **cwd is main repo + prompt contains [STEAL]** — dispatch-gate.sh
      blocks. The predicate is: `git rev-parse --show-toplevel` does NOT
      contain `/.claude/worktrees/`.
   2. **Bash command is `git checkout -b steal/*` or `git switch -b steal/*`
      from any cwd** — guard.sh blocks via guard-rules.conf. Use
      `git worktree add -b steal/<topic>` instead.
   3. **Post-steal: main repo's branch is `steal/*` or `round/*`** — means
      the main workspace was hijacked somewhere. Recovery: backup uncommitted
      work with `git stash` + `git stash show -p > .trash/<date>/recovery.patch`,
      then `git checkout main`, then `git stash pop` or re-apply patch.
   ```
   - depends on: none
   → verify: `grep -c 'machine-checked' .claude/skills/steal/constraints/worktree-isolation.md` returns `1`.

### Phase 5: Smoke test

7. Create `tests/hooks/test_dispatch_gate_worktree.sh` covering 3 cases:
   (a) main repo + `[STEAL]` → blocks with "must run from inside";
   (b) main repo + no tag → no block;
   (c) worktree cwd + `[STEAL]` → no block on the worktree predicate
   (may still block on branch name if branch doesn't match, that's fine).

   Script body — each case runs `dispatch-gate.sh` with a canned stdin
   JSON, asserts `grep -q` on the output. Use `set -euo pipefail`.
   - depends on: steps 1, 2
   → verify: `bash tests/hooks/test_dispatch_gate_worktree.sh && echo PASS`
     exits 0 and prints PASS.

### Phase 6: Commit

8. From a worktree off main: `git worktree add .claude/worktrees/gate-harden -b refactor/worktree-gate-hardening main`, cd in, stage all files from the File Map, commit with a message referencing this plan path.
   - depends on: all prior steps verified in the worktree
   → verify: `git log -1 --stat` shows the 4 expected files (excluding the
     test if it's in a location `.gitignore`'d — check first).

--- PHASE GATE: Plan → Implement ---
[ ] Every step has action verb + specific target + verify command
[ ] No banned placeholder phrases
[ ] Dependencies explicit (steps 2, 4, 5, 7, 8 have `depends on`)
[ ] Steps 2-5 min each
[ ] Owner has seen the plan — **required before implementation next session**

## Non-Goals (deferred)

- Cross-machine context pack sync (see ASSUMPTION A1).
- Modifying the external /ralph-loop plugin (see ASSUMPTION A2).
- Retroactive cleanup of the 17 existing `steal-*` worktrees — they're
  fine as-is, the new gate only affects future dispatches.
- Migrating `.claude/boot.md` or `.claude/context/` out of gitignore.

## Rollback

If any step breaks existing `[STEAL]` flows, revert with:
`git revert <commit-sha>` on the refactor branch. No data loss risk —
hooks are text files, no state migration.
