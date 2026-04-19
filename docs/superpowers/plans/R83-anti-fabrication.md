# Plan: R83 P0#5 — Devin + Replit Anti-Fabrication Rule

> **Source pattern**: `docs/steal/R83-cl4r1t4s-steal.md` P0 #5 (Devin "Truthful and Transparent" + Replit "Data Integrity Policy").
> **For executors**: follow `SOUL/public/prompts/plan_template.md` conventions. Every step has a copy-paste `verify` command.

## Goal

`SOUL/public/prompts/rationalization-immunity.md` gains a new `## Data Fabrication` section containing a table with ≥ 7 trigger phrases and their correct behaviors; a new Stop hook `anti-fabrication.sh` scans `git diff HEAD` `+` lines for bare `mock`/`TODO`/`stub`/`FIXME`/`placeholder`/`fake` tokens, emits a `systemMessage` warning (not a block) when found outside whitelisted paths, and allows agent acknowledgement via `# legitimate-stub: <reason>` annotation. **Done** = a fixture commit containing `TODO: mock this` triggers the warning; a fixture commit containing `# legitimate-stub: upstream API not deployed yet` passes silently.

## Why This Scope

Devin, Replit, and Factory each arrived at the same rule independently (Triple Validation, 3/3 in the steal report). The current gap is narrow: `rationalization-immunity.md` bans completion lies (`should pass` banned) but has no row for upstream fabrication during the implementation phase. `verification-gate/SKILL.md` catches false completion claims at declaration time but not fabricated inputs written into the code itself.

Two-file intervention: (1) one new section in the prompt doc, (2) one new Stop hook wired into `settings.json`. Warning-over-block is deliberate — an agent that must hard-stop when it writes a fixture helper is broken; an agent that writes an unacknowledged `TODO: mock this` and claims "done" is lying.

Simplicity pre-check: minimum viable = 1 doc section + 1 hook script + 1 settings entry + 2 test fixtures = 4 artifacts. Plan below touches 5 files (adds integration test). Within 2x simplest.

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `SOUL/public/prompts/rationalization-immunity.md` | Add `## Data Fabrication` section with fabrication trigger table |
| Create | `.claude/hooks/anti-fabrication.sh` | Stop hook: scans `git diff HEAD` `+` lines for fabrication tokens; emits systemMessage warning; respects whitelist |
| Modify | `.claude/settings.json` | Append `anti-fabrication.sh` entry to existing `Stop.hooks` array |
| Create | `tests/hooks/fixtures/stub-commit-dirty.patch` | Fixture: patch with `TODO: mock this` line — must trigger warning |
| Create | `tests/hooks/fixtures/stub-commit-clean.patch` | Fixture: patch with `# legitimate-stub: upstream API not deployed yet` line — must pass silently |
| Create | `tests/hooks/test_anti_fabrication.sh` | Integration test: pipes each fixture through the hook, asserts warn vs pass |

No files outside the repo root. Protected files untouched: `CLAUDE.md`, `boot.md`, `SOUL/private/`, `docs/steal/`, other R83 plan files.

---

## Phase 1: Prompt-Level Rule

### Task 1: Fabrication table in rationalization-immunity.md

- [ ] **Step 1.** Read `SOUL/public/prompts/rationalization-immunity.md` in full to identify the exact line after the last `##` section (currently `## Meta-Rationalization`) where the new section will be inserted.
  → verify: `grep -n '^## ' SOUL/public/prompts/rationalization-immunity.md`

- [ ] **Step 2.** Insert a new `## Data Fabrication` section immediately before the `## Output Format` section in `SOUL/public/prompts/rationalization-immunity.md`. The section body is a markdown table with three columns (Rationalization | Rebuttal | Correct Behavior) and exactly 7 rows:

  | Rationalization | Rebuttal | Correct Behavior |
  |---|---|---|
  | "I'll use mock data for now" | "For now" never gets replaced. Mock data ships, real data never arrives. | Stop. Get real data or tell the owner explicitly what's blocked and why. |
  | "Stubbed this out, will return real later" | You will not return. The stub becomes the implementation. | Stop. Implement the real thing or surface the blocker. |
  | "Assuming the API returns X" | Assumptions baked into code are bugs waiting to be discovered in production. | Run the API call and handle its actual response, or block on inability to reach it. |
  | "For now let's just hardcode this" | "Just hardcoding" is a commitment with an invisible expiry date that always passes. | Use the real source or declare the dependency explicitly as unresolved. |
  | "Placeholder value, will fill in later" | Placeholders accumulate. There is no "later" in an agent's execution. | Fill it now with real data, or state to the owner that you cannot proceed without it. |
  | "TODO: implement this properly later" | A TODO in committed code is a lie: you committed something unfinished and claimed it done. | Either implement it now or do not commit the file. |
  | "Mocking \<service\> since I can't reach it" | Mocking an unreachable service produces a test that can never fail in a way that matters. | Tell the owner the service is unreachable and what that means for progress. Do not fake the interaction. |

  - depends on: step 1
  → verify: `grep -c 'legitimate-stub\|for now\|stubbed this out\|assuming the API\|hardcode\|placeholder value\|TODO: implement\|mocking.*since' SOUL/public/prompts/rationalization-immunity.md | grep -qvE '^0$'`

- [ ] **Step 3.** Re-read `SOUL/public/prompts/rationalization-immunity.md` after the edit to confirm the new section appears between `## Meta-Rationalization` and `## Output Format`, and that the table renders with all 7 rows (count `|---|---|---|` separators — expect exactly 1 new one in the fabrication section).
  - depends on: step 2
  → verify: `awk '/^## Data Fabrication/,/^## Output Format/' SOUL/public/prompts/rationalization-immunity.md | grep -c '|---|---|---|' | grep -qE '^1$'`

---

--- PHASE GATE: Plan → Implement ---
- [ ] Every step has action verb + specific target + verify command
- [ ] No banned placeholder phrases (checked against Iron Rule table)
- [ ] Dependencies explicit on every multi-step task
- [ ] Total steps: 11 (within 5–30 range)
- [ ] Simplicity pre-check documented (see "Why This Scope" above)
- [ ] Owner has seen the plan → Owner review: **not required** (reversible; all changes are additive append or new file; `rationalization-immunity.md` edit is easily reverted; hook is warn-only, never blocks)

---

## Phase 2: Hook-Level Enforcement + Integration Test

### Task 2: Anti-fabrication Stop hook

- [ ] **Step 4.** Create `.claude/hooks/anti-fabrication.sh` with shebang `#!/bin/bash`. The script:
  1. Runs `git diff HEAD --unified=0 2>/dev/null` to get the diff of staged+unstaged changes; if exit code is non-zero (not in a git repo or no HEAD), exits 0 silently.
  2. Extracts only `+` lines (new content) from the diff: `grep '^+' | grep -v '^+++'`.
  3. Defines a whitelist: lines matching `tests/fixtures/|docs/|\.md:|# legitimate-stub:` are removed from the candidate set (`grep -vE`).
  4. Against the remaining lines, runs `grep -iE '(^|\s)(mock|TODO|stub|FIXME|placeholder|fake)(\s|:|$)'`.
  5. If any matches exist, collects the first 5 matching lines and prints JSON to stdout:
     ```json
     {"systemMessage":"ANTI-FABRICATION: New code contains unacknowledged fabrication markers (mock/TODO/stub/FIXME/placeholder/fake). Either resolve them now, or annotate each with '# legitimate-stub: <reason>' and explain in your completion declaration which stubs remain and why. Matched lines:\n<first 5 matches>"}
     ```
  6. If no matches, exits 0 silently.
  The script must NOT exit with a non-zero code — warning mode only; blocking would prevent legitimate commit workflows.
  → verify: `bash -n .claude/hooks/anti-fabrication.sh && test -f .claude/hooks/anti-fabrication.sh`

- [ ] **Step 5.** Make `.claude/hooks/anti-fabrication.sh` executable and add a `--selftest` mode gated by `[ "$1" = "--selftest" ]`. The selftest creates a temp file `$(mktemp)` containing `+  TODO: mock this endpoint`, sets `GIT_DIFF_OVERRIDE` env var (the hook checks this var when set and uses it as the diff input instead of `git diff HEAD`), runs the detection logic against it, asserts the word `ANTI-FABRICATION` appears in output, then removes the temp file. Selftest exits 0 on pass, 1 on fail.
  - depends on: step 4
  → verify: `chmod +x .claude/hooks/anti-fabrication.sh && bash .claude/hooks/anti-fabrication.sh --selftest | grep -q 'ANTI-FABRICATION'`

- [ ] **Step 6.** Read `.claude/settings.json` to locate the `Stop.hooks` array (currently has 6 entries ending with `block-protect.sh cleanup`). Append one new entry using `jq` to insert before the last element (so the anti-fabrication check runs before `block-protect.sh cleanup`):
  ```bash
  jq '.hooks.Stop[0].hooks |= . + [{"type":"command","command":"bash .claude/hooks/anti-fabrication.sh","timeout":5}]' \
    .claude/settings.json > .claude/settings.json.new && mv .claude/settings.json.new .claude/settings.json
  ```
  - depends on: step 5
  → verify: `jq -e '.hooks.Stop[0].hooks | map(select(.command | contains("anti-fabrication"))) | length == 1' .claude/settings.json`

### Task 3: Fixture patches + integration test

- [ ] **Step 7.** Create `tests/hooks/fixtures/stub-commit-dirty.patch` as a minimal unified diff file. Content:
  ```
  diff --git a/src/service.py b/src/service.py
  --- a/src/service.py
  +++ b/src/service.py
  @@ -0,0 +1,3 @@
  +def get_data():
  +    # TODO: mock this endpoint until API is ready
  +    return {"result": "fake"}
  ```
  This fixture represents a commit that should trigger the anti-fabrication warning.
  → verify: `test -f tests/hooks/fixtures/stub-commit-dirty.patch && grep -q 'TODO: mock this' tests/hooks/fixtures/stub-commit-dirty.patch`

- [ ] **Step 8.** Create `tests/hooks/fixtures/stub-commit-clean.patch` as a minimal unified diff file. Content:
  ```
  diff --git a/src/service.py b/src/service.py
  --- a/src/service.py
  +++ b/src/service.py
  @@ -0,0 +1,3 @@
  +def get_data():
  +    # legitimate-stub: upstream API not deployed yet, tracked in issue #42
  +    return {"result": "placeholder"}
  ```
  This fixture represents a commit with an acknowledged stub that should pass silently.
  → verify: `test -f tests/hooks/fixtures/stub-commit-clean.patch && grep -q 'legitimate-stub' tests/hooks/fixtures/stub-commit-clean.patch`

- [ ] **Step 9.** Create `tests/hooks/test_anti_fabrication.sh` (executable bash). Three test cases using `GIT_DIFF_OVERRIDE` to inject fixture content:

  **Case 1 — dirty commit triggers warning**:
  Set `GIT_DIFF_OVERRIDE` to the content of `stub-commit-dirty.patch`, source the hook logic (or call `bash anti-fabrication.sh` with the env var set), capture stdout, assert it contains `ANTI-FABRICATION`. Print `PASS: dirty commit triggers warning` or `FAIL: dirty commit — no warning emitted`.

  **Case 2 — clean (annotated) commit passes silently**:
  Set `GIT_DIFF_OVERRIDE` to the content of `stub-commit-clean.patch`, run the hook, assert stdout is empty (exit 0, no systemMessage). Print `PASS: clean commit passes silently` or `FAIL: clean commit — false positive warning`.

  **Case 3 — docs-only change passes silently**:
  Set `GIT_DIFF_OVERRIDE` to a single `+` line `+docs/ TODO: document this section`, run the hook, assert stdout is empty (the `docs/` whitelist filter suppresses it). Print `PASS: docs-only passes silently` or `FAIL: docs path — false positive`.

  Script exits 1 if any case fails, 0 if all pass.
  - depends on: steps 5, 7, 8
  → verify: `chmod +x tests/hooks/test_anti_fabrication.sh && bash tests/hooks/test_anti_fabrication.sh | tee /dev/stderr | grep -c 'PASS' | grep -qE '^3$'`

- [ ] **Step 10.** Read `tests/hooks/test_anti_fabrication.sh` to confirm all three cases are present and the exit-code logic is correct (grep for `exit 1` inside a failure branch, confirm `exit 0` at the end).
  - depends on: step 9
  → verify: `grep -c 'PASS:' tests/hooks/test_anti_fabrication.sh | grep -qE '^3$' && grep -q 'exit 1' tests/hooks/test_anti_fabrication.sh`

### Task 4: Documentation cross-link

- [ ] **Step 11.** Add a one-line cross-reference to `.claude/skills/verification-gate/SKILL.md` in the `## Common Rationalizations` table. Insert a new row after the existing `"I'm tired, this is the last task"` row:

  | "I'll stub this out and mark it done" | Stubs committed as working code are fabrication, not implementation. The anti-fabrication Stop hook will surface them. | Either implement now or annotate with `# legitimate-stub: <reason>` and disclose in your completion declaration. |

  - depends on: step 2
  → verify: `grep -q "stub this out and mark it done" .claude/skills/verification-gate/SKILL.md`

---

--- PHASE GATE: Implement → Verify ---
- [ ] All 11 verify commands executed and passing
- [ ] `git diff` contains only the 6 files in the File Map (no collateral edits)
- [ ] Case 1 (dirty) triggers warning; Case 2 (annotated) passes; Case 3 (docs) passes
- [ ] `settings.json` is valid JSON: `jq empty .claude/settings.json` exits 0
- [ ] `bash -n .claude/hooks/anti-fabrication.sh` exits 0 (syntax clean)

--- PHASE GATE: Verify → Commit ---
- [ ] `settings.json` valid JSON confirmed
- [ ] Hook selftest passes: `bash .claude/hooks/anti-fabrication.sh --selftest | grep -q ANTI-FABRICATION`
- [ ] All 3 integration test cases pass: `bash tests/hooks/test_anti_fabrication.sh | grep -c PASS | grep -qE '^3$'`
- [ ] Commit message: `feat(governance): R83 P0#5 — anti-fabrication rule in rationalization-immunity + Stop hook`
- [ ] Cross-reference in commit body: `Refs: docs/steal/R83-cl4r1t4s-steal.md:49` (the P0 #5 row)

---

## Dependencies on Other R83 Plans

| Slug | Coupling | Direction |
|------|----------|-----------|
| P0#1: `R83-dia-trust-tagging` | Independent. Trust-tagging targets external content ingestion; anti-fabrication targets implementation-phase code output. No shared files. | None |
| P0#2: `R83-droid-phase-gate` | Weak. The phase-gate hook (`phase-gate.sh`) enforces env-bootstrap ordering; the anti-fabrication hook (`anti-fabrication.sh`) scans code content. Both attach to Stop/PreToolUse, both use `jq` to write `settings.json`. **Sequencing**: if both plans run in the same session, use separate `jq` operations on `settings.json` and re-read between edits to avoid merge conflicts. | Coordinate `settings.json` edits only |
| P0#3: `R83-manus-typed-events` | Potential. If P0#3 adds `event_type` frontmatter to `rationalization-immunity.md` (treating it as a `knowledge` event), the fabrication section written here must carry that frontmatter. **Action**: when P0#3 lands, add `event_type: knowledge` to the frontmatter of `SOUL/public/prompts/rationalization-immunity.md` — one line addition, no rework of the fabrication content. | Frontmatter retrofit if P0#3 lands first |
| P0#4: `R83-droid-intent-gate` | None. Intent-gate classifies incoming messages (diagnostic vs implementation); anti-fabrication scans outgoing code at commit time. Different layers, no shared code paths. | None |
| P0#5: `R83-anti-fabrication` | This plan. | — |

**Recommended ship order**: P0#5 can ship independently. It has no upstream dependencies. If P0#2 ships first, re-read `settings.json` before Step 6 to avoid overwriting P0#2's additions.

---

## Known Limits / Deferred Items

- `ASSUMPTION: git diff HEAD covers both staged and unstaged changes in the working tree. In detached HEAD states (fresh worktree before first commit), the hook exits 0 silently rather than false-positive on every file.` Validate during Step 5 selftest.
- Scope excludes scanning `PreToolUse(Edit|Write)` on the fly. Rationale: checking on write would fire on legitimate test fixture construction and produce false positives with no context about the surrounding commit. Stop-hook scanning with `git diff HEAD` gives the agent a full picture of what it has written across the turn before declaring done.
- Scope excludes Python's `unittest.mock` and `pytest-mock` import-level mocking patterns (e.g., `from unittest import mock`). These are standard test infrastructure, not fabrication. The current regex `(mock|TODO|stub|...)` fires on the word `mock` — this will produce false positives in `tests/` directories. **Mitigation**: add `tests/` to the whitelist regex in Step 4 alongside `tests/fixtures/`. The plan step already lists `tests/fixtures/` — extend it to `tests/` broadly.
- The `GIT_DIFF_OVERRIDE` env-var injection approach in the selftest and integration test is a test-only shim. Production hook always uses `git diff HEAD`. The shim must be removed if the hook is ever promoted to a shared library.

## Effort Estimate

- Task 1 (rationalization-immunity.md fabrication section): 25 min
- Task 2 (anti-fabrication.sh hook + selftest + settings wire-up): 40 min
- Task 3 (fixture patches + integration test): 35 min
- Task 4 (verification-gate cross-link): 10 min
- **Total: ~110 min ≈ 2h** (matches steal report estimate of ~2h, shortest P0).
