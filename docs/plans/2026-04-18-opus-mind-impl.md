# Plan: opus-mind deterministic linter + governance patches (R79)

## Goal

`python3 .claude/skills/md-lint/scripts/audit.py CLAUDE.md --json` returns `verdict: BORDERLINE` or `GOOD` (score ≥ 8/11), AND any `Write`/`Edit` to `.claude/skills/*/SKILL.md` or `CLAUDE.md` is blocked by a pre-write hook when the same audit scores < 8/11. Five P0 patterns (linter core, self-audit gate, reframe detection, tier-label vocabulary, 3-pass redundancy) are written to specific files with no unverified placeholders.

## Context

Source: `docs/steal/R79-opus-mind-steal.md` — opus-mind (2026-04-17, Hybirdss).

What we stole:
- **Deterministic linter architecture** — 4 layers: static knowledge base (primitives/ patterns/ techniques/), no-LLM Python engine (audit.py / plan.py / fix.py / boost.py), SKILL.md router, self-audit BUILD.md gate. We adopt layers 2 + 3 + 4 only; layer 1 is distilled into 8-10 primitives.md under md-lint/references/.
- **11 regex invariants** locally adapted: hedge_density ≤ 0.25, number_density ≥ 0.10, decision ladder, reframe signal, narration-free, rationale-if-examples, consequences-per-directive, xml-balanced, default+exception pair, self-check-if-long, tier-label present. Domain adaptations: `<critical>` counts as tier-label (I10); Chinese hedge words ("可能"/"也许"/"大概") added to HEDGES list.
- **Negator + quote guard** — `_has_negator_context()` + `_QUOTE_SPAN_RE` prevent blacklist examples from self-triggering (the Draft-1 mistake in opus-mind).
- **Placeholder penalty** — `PLACEHOLDER_RE` detects `<FIXME>`/`[TODO]`/`???`/`TBD`/`tk tk` as a separate count outside the 11-invariant score.
- **Self-audit gate** — BUILD.md pattern: the skill's own SKILL.md must score ≥ 8/11 before it can be committed. Enforced via pre-write hook.
- **Reframe-as-signal** (primitive 09) — when inner dialogue softens a request to make it acceptable, the softening is the rejection trigger, not a compliance path. Added to rationalization-immunity.md.
- **Tier-label vocabulary** (pattern hard-tier-labels) — 4-level: NEVER / SEVERE VIOLATION / HARD LIMIT / DEFAULT. ALLCAPS + concrete number pairing.
- **3-pass redundancy** for high-stakes rules — same rule re-stated in 3 different framings (identity level / formal rule / gate self-check question) to survive long-context attention drift.

What we deliberately skipped:
- Layer 1 full primitives/patterns/techniques/ directory (906 lines) — distilled into 1 primitives.md.
- plan.py / fix.py / boost.py — out of scope for this plan; BOOST user-prompt coaching is P1.
- XML-namespace hierarchy (I7) — we use markdown + `<critical>`; XML migration not worth it now.
- Anti-slop 1-to-1 word-replacement (fix.py TIER1_REPLACEMENTS) — Chinese prompt context makes the English slop list irrelevant.

## ASSUMPTIONS

These items are deferred to owner because the wrong choice requires rebuilding:

1. **ASSUMPTION: threshold value** — Using 8/11 as the minimum passing score (BORDERLINE). opus-mind uses 6/6 (100%), but our CLAUDE.md and existing skills were written before this linter existed. If owner wants stricter (10/11) or looser (6/11), change `MIN_PASS` constant in `audit.py` before running baseline.

2. **ASSUMPTION: hook scope** — Pre-write hook currently targets `CLAUDE.md` and `.claude/skills/*/SKILL.md` only. If owner wants to expand to `boot.md` or `SOUL/public/prompts/*.md`, add those patterns to the hook's path-match regex before step 8.

3. **ASSUMPTION: settings.json hook key** — Using `hooks.PreToolUse` with `matcher: "Write|Edit"`. If `.claude/settings.json` already has a conflicting PreToolUse entry, the owner must resolve merge manually; this plan does not overwrite existing hooks.

4. **ASSUMPTION: existing skill baseline scores** — We don't know in advance which of the 7 existing skills will score worst. After step 13 produces `docs/steal/R79-opus-mind-baseline.md`, owner decides fix order. This plan does NOT rewrite any existing SKILL.md.

5. **ASSUMPTION: Chinese hedge word list** — Draft includes "可能", "也许", "大概", "应该", "不确定", "或许" as Chinese hedge tokens. Owner may add or remove entries before baseline run.

## File Map

- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/SKILL.md` — Create
- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/scripts/__init__.py` — Create
- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/scripts/audit.py` — Create
- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/references/primitives.md` — Create
- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/tests/__init__.py` — Create
- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/tests/fixtures/good_8of11.md` — Create
- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/tests/fixtures/bad_hedges.md` — Create
- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/tests/test_audit.py` — Create
- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/md-lint-pre-write.sh` — Create
- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/settings.json` — Modify (add PreToolUse hook entry)
- `/d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/rationalization-immunity.md` — Modify (append Reframe Detection section)
- `/d/Users/Administrator/Documents/GitHub/orchestrator/CLAUDE.md` — Modify (insert Tier Label Vocabulary section before `<critical>`)
- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/boot.md` — Modify (append 1-line rollback identity declaration)
- `/d/Users/Administrator/Documents/GitHub/orchestrator/docs/steal/R79-opus-mind-baseline.md` — Create (generated by step 13)

## Steps

### Phase A — Linter core (P0 #1 + domain-aware required + placeholder penalty + negator/quote guard)

**Step 1.** Create `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/scripts/audit.py` with the following regex tables at module top-level:
- `HEDGES = re.compile(r'\b(probably|might|may|perhaps|could|possibly|when appropriate|if needed|maybe|可能|也许|大概|应该|不确定|或许)\b', re.I)`
- `NARRATION = re.compile(r'\b(I will|let me|I\'ll|I\'m going to|I\'m now|首先我|接下来我|然后我)\b', re.I)`
- `LADDER_SIGNALS = re.compile(r'(Step 0|Step 1|first.{0,20}check|if.{0,30}else|→ NO|→ YES)', re.I)`
- `REFRAME_SIGNALS = re.compile(r'(reframe|softening|if you find yourself|soft.{0,20}request)', re.I)`
- `CONSEQUENCE_SIGNALS = re.compile(r'\b(will result in|causes|leads to|means that|penalty|violation|破坏|导致|违反)\b', re.I)`
- `EXAMPLE_SIGNALS = re.compile(r'(e\.g\.|for example|such as|例如|比如|\(good\)|\(bad\))', re.I)`
- `RATIONALE_SIGNALS = re.compile(r'\b(because|reason|why|the point is|原因|因为|所以)\b', re.I)`
- `NUMBER_CONSTRAINT = re.compile(r'(\d+\s*(ms|s|h|min|LOC|lines?|tokens?|%|\/\d+|x\b)|≤\s*\d+|≥\s*\d+|<\s*\d+|>\s*\d+)', re.I)`
- `DIRECTIVE_VERBS = re.compile(r'^[-*] \*\*(NEVER|ALWAYS|DO NOT|MUST|SHALL|STOP|禁止|必须|不得)\b', re.M)`
- `XML_OPEN = re.compile(r'<(?!FIXME|TODO)[a-zA-Z][^/>\s]*[^/]>')`
- `XML_CLOSE = re.compile(r'</[a-zA-Z][^>]*>')`
- `TIER_LABEL_RE = re.compile(r'\b(NEVER|SEVERE VIOLATION|HARD LIMIT|NON-NEGOTIABLE|ABSOLUTE|<critical>)', re.I)`
- `PLACEHOLDER_RE = re.compile(r'(<FIXME>|\[TODO\]|\?\?\?|TBD\b|tk tk)', re.I)`
- `NEGATOR_PATTERNS = re.compile(r'\b(does not|never|refuse|must not|cannot|不得|禁止)\b', re.I)`
- `_QUOTE_SPAN_RE = re.compile(r'[\'"`]{1,3}.{1,120}[\'"`]{1,3}')`

Also add helper `_has_negator_context(line: str) -> bool` and `_match_outside_quotes(pattern, text: str) -> list`.

→ verify: `python3 -c "import ast, sys; ast.parse(open('/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/scripts/audit.py').read()); print('syntax OK')"`

**Step 2.** Add `_iter_violations(text: str, pattern, label: str) -> list[dict]` and `_iter_findings(text: str, pattern, label: str) -> list[dict]` to `audit.py`. `_iter_violations` skips matches where `_has_negator_context(line)` is True OR `_match_outside_quotes` shows the match is inside a quote span. `_iter_findings` counts pure presence without suppression. Both return `[{"label": label, "line": n, "text": matched_text}]`.
- depends on: step 1
→ verify: `python3 -c "
import sys; sys.path.insert(0,'/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/scripts')
from audit import _iter_violations, NARRATION
result = _iter_violations(\"Claude does not say 'let me do this'\", NARRATION, 'I4')
assert result == [], f'negator guard failed: {result}'
print('negator guard OK')
"`

**Step 3.** Add invariant scoring functions `score_I1` through `score_I11` to `audit.py`, each returning `(passed: bool, detail: str)`:
- `score_I1(text)`: hedge_count / directive_count ≤ 0.25 AND number_count / directive_count ≥ 0.10; THIN if directive_count < 3 (auto-pass).
- `score_I2(text)`: decision-ladder present (LADDER_SIGNALS ≥ 1) when directive_count ≥ 6.
- `score_I3(text)`: REFRAME_SIGNALS ≥ 1 when text contains "refusal" / "jailbreak" / "拒绝" at least twice.
- `score_I4(text)`: NARRATION violations == 0 (uses `_iter_violations`).
- `score_I5(text)`: if EXAMPLE_SIGNALS ≥ 1 then RATIONALE_SIGNALS ≥ 1.
- `score_I6(text)`: CONSEQUENCE_SIGNALS count ≥ floor(directive_count / 10).
- `score_I7(text)`: XML_OPEN count == XML_CLOSE count (balanced).
- `score_I8(text)`: at least one "DEFAULT:" or "default behavior:" pattern AND one "exception"/"EXCEPTION"/"例外" on a separate line within 5 lines.
- `score_I9(text)`: if directive_count ≥ 12 then text contains "self-check" / "自检" / "verify:".
- `score_I10(text)`: TIER_LABEL_RE ≥ 1.
- `score_I11(text)`: text contains "Tier [0-9]" or "tier [0-9]" or "Commitment Hierarchy" or "优先级".
- depends on: step 2
→ verify: `python3 -c "
import sys; sys.path.insert(0,'/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/scripts')
from audit import score_I4
passed, _ = score_I4(\"Claude does not say 'let me'\")
assert passed, 'I4 should pass with negator guard'
print('I4 guard OK')
"`

**Step 4.** Add `audit_file(path: str) -> dict` to `audit.py` that: reads file, runs I1-I11, collects `placeholder_count` via `PLACEHOLDER_RE`, computes `total_pass = sum(r[0] for r in results)`, assigns `verdict` as: THIN if line_count < 10 or directive_count < 3; POOR if total_pass < 6; BORDERLINE if 6 ≤ total_pass ≤ 9; GOOD if total_pass ≥ 10. Returns JSON-serializable dict with keys: `path`, `line_count`, `directive_count`, `total_pass`, `verdict`, `pass` (dict I1→bool), `detail` (dict I1→str), `placeholder_count`. Add `if __name__ == "__main__"` CLI: `python3 audit.py <path> [--json]`.
- depends on: step 3
→ verify: `python3 /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/scripts/audit.py /d/Users/Administrator/Documents/GitHub/orchestrator/CLAUDE.md --json | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'verdict' in d and len(d['pass'])==11, d"`

**Step 5.** Create `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/tests/fixtures/good_8of11.md` with exactly: 45 lines, 1 `<critical>` block (satisfies I10), 2 decision ladders using `→ NO:` / `→ YES:` (satisfies I2), 4 numbers with units like `≤ 300 LOC` / `≥ 8/11` / `< 2h` / `3 retries` (satisfies I1 number_density), 1 self-check line "→ verify:" (satisfies I9), 1 rationale sentence starting "Because" (satisfies I5), 3 consequence phrases using "leads to" / "results in" / "penalty" (satisfies I6), xml `<critical>` balanced with `</critical>` (I7), 1 "DEFAULT:" line followed by "exception:" within 3 lines (I8), "Tier 1" / "Tier 2" tokens (I11), zero hedge words, zero NARRATION tokens.
- depends on: step 4
→ verify: `python3 /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/scripts/audit.py /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/tests/fixtures/good_8of11.md --json | python3 -c "import sys,json; d=json.load(sys.stdin); s=sum(d['pass'].values()); assert s>=8, f'only {s}/11: {d[\"pass\"]}'"`

**Step 6.** Create `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/tests/fixtures/bad_hedges.md` with: 12 directive lines (NEVER/MUST/DO NOT × 4 each), 6 hedge words ("probably", "might", "when appropriate", "if needed", "可能", "也许"), zero numbers with units, no tier labels, no XML. This ensures I1 fails (hedge_density > 0.25) and I10 fails.
- depends on: step 4
→ verify: `python3 /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/scripts/audit.py /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/tests/fixtures/bad_hedges.md --json | python3 -c "import sys,json; d=json.load(sys.stdin); assert not d['pass']['I1_hedge_number'], f'I1 should fail: {d}'"`

**Step 7.** Create `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/tests/test_audit.py` with 4 pytest test functions:
- `test_good_fixture_passes()`: `audit_file("tests/fixtures/good_8of11.md")["total_pass"] >= 8`
- `test_bad_hedges_fails_I1()`: `audit_file("tests/fixtures/bad_hedges.md")["pass"]["I1_hedge_number"] == False`
- `test_negator_guard()`: raw call `score_I4("Claude does not say 'let me do this'")` returns `(True, ...)` — narration inside negation context must not trigger I4.
- `test_placeholder_counted_separately()`: text `"## Rules\n- NEVER skip <FIXME>\n"` → `audit_file` result has `placeholder_count >= 1` AND the FIXME does NOT cause I4 to fail.
- depends on: step 5, step 6
→ verify: `cd /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint && python3 -m pytest tests/test_audit.py -v 2>&1 | tail -10`

### Phase B — Self-audit gate (P0 #2)

**Step 8.** Create `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/md-lint-pre-write.sh`. The script: reads hook payload from stdin as JSON using `python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))"`, assigns result to `$TARGET_PATH`. If `$TARGET_PATH` matches `*/SKILL.md` or `*CLAUDE.md` (using bash `case`), write the `tool_input.content` field to a temp file `/tmp/md-lint-check-$$.md`, run `python3 /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/scripts/audit.py /tmp/md-lint-check-$$.md --json`, capture `total_pass` via `python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d['total_pass']>=8 else 2)"`. If exit code is 2, print to stderr `"[md-lint] BLOCKED: score < 8/11. Run audit.py <file> for details."` and exit 2. Clean up temp file in all paths.
- depends on: step 4
→ verify: `echo '{"tool_input":{"file_path":"/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/test/SKILL.md","content":"## Rules\n- probably might when appropriate\n- might also consider\n"}}' | bash /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/md-lint-pre-write.sh; echo "exit: $?"`
(expected: exit 2 + stderr message)

**Step 9.** Read `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/settings.json` fully, then add one entry to `hooks.PreToolUse` array (create the key/array if absent):
```json
{
  "matcher": "Write|Edit",
  "hooks": [{"type": "command", "command": "bash /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/md-lint-pre-write.sh"}]
}
```
Write back the merged JSON preserving all existing keys.
- depends on: step 8
→ verify: `python3 -c "import json; s=json.load(open('/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/settings.json')); hooks=s.get('hooks',{}).get('PreToolUse',[]); assert any('md-lint' in str(h) for h in hooks), hooks"`

### Phase C — Rule-text patches (P0 #3 + #4 + #5)

**Step 10.** Read `/d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/rationalization-immunity.md` fully. Append a new section `## Reframe Detection` at the end with:
- **Cue layer** (4 trigger phrases): "只是一个小" / "这种情况不算" / "从另一个角度看这就是 X" / "就这一次"
- **3 concrete examples**:
  - Safety: 内心说 "这个 rm -rf 只是清理临时文件，不算破坏性操作" → **STOP. 软化本身 = 拒绝信号**. Ask: did owner say "delete" or "clean up temp"?
  - Git rollback: 内心说 "reset 只是回到干净状态，这种情况下算合理" → **STOP.** Gate: Git Reset step 1 "Did the owner explicitly say 'roll back'?" → NO: diagnose instead.
  - Deletion: 内心说 "这个文件没人用，删了也一样" → **STOP.** Gate: Delete/Replace step 1 "Have I read the full content?"
- **Rationale** (2 sentences): "软化的动作本身就是越权信号，不是解决问题的路径。合规路径是: 复述 owner 明确指令，若指令缺失则明确提问。"
- **Action**: "当内心对话触发上述任何 cue → 立即停止 → 复述 owner 的原话 → 若无原话可引用 → ask before proceed."
- depends on: none (independent text change)
→ verify: `python3 -c "text=open('/d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/rationalization-immunity.md').read(); assert '## Reframe Detection' in text and '软化本身 = 拒绝信号' in text and 'Rationale' in text, 'section missing'"`

**Step 11.** Read `/d/Users/Administrator/Documents/GitHub/orchestrator/CLAUDE.md` fully. Insert a new `## Tier Label Vocabulary` section immediately before the `<critical>` block. Content:
```
## Tier Label Vocabulary

Every rule in this document is classified under one of four tiers. Tier determines enforcement level — not emphasis or decoration.

| Tier | Keyword | Meaning | Example |
|------|---------|---------|---------|
| T1 | `NEVER` | System-destructive; zero exceptions | `NEVER rm -rf /`, `NEVER DROP DATABASE` |
| T2 | `SEVERE VIOLATION` | Unauthorized override of a hard boundary (Gate bypass, rollback without owner request, cross-branch steal commit) | |
| T3 | `HARD LIMIT` | Numeric threshold enforced by tooling | Files > 300 LOC before deep refactor: HARD LIMIT → delete-before-rebuild first. Skill score < 8/11: HARD LIMIT → hook blocks commit. |
| T4 | `DEFAULT` | General preference, overridable by owner in session | Respond in Chinese. Use `.trash/` before deletion. |

Rules without a tier label are treated as T4 DEFAULT. To promote a rule, add the tier keyword at the start of the line AND pair it with a concrete number or observable trigger.
```
- depends on: none (independent text change)
→ verify: `python3 -c "text=open('/d/Users/Administrator/Documents/GitHub/orchestrator/CLAUDE.md').read(); assert '## Tier Label Vocabulary' in text and 'SEVERE VIOLATION' in text and 'HARD LIMIT' in text, 'section missing'"`

**Step 12.** Read `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/boot.md` fully. Append to the end (after the last line) a single new line:
```
rollback 是禁区（T2 SEVERE VIOLATION）。唯一例外：owner 明确说 "roll back" / "reset" / "revert"。其他任何情况一律用 git diff 诊断，不执行 reset。
```
- depends on: none (independent text change)
→ verify: `python3 -c "text=open('/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/boot.md').read(); assert 'rollback 是禁区' in text and 'T2 SEVERE VIOLATION' in text, 'line missing'"`

### Phase D — Dogfood + baseline (P0 #2 self-audit validation)

**Step 13.** Create `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/SKILL.md`. The file must include: yaml frontmatter with `name: md-lint`, `version: 0.1.0`, `description`; Identity section (role: deterministic linter for SKILL.md and CLAUDE.md); How You Work section with 3 routing flows (LINT / DOGFOOD / BASELINE) using first-match-wins ladder with `→ verify:` per flow; Output Format section showing the `--json` schema with all keys; Quality Bar section listing the 11 invariants by name; Boundaries section listing what this skill does NOT do (no LLM scoring, no fix.py, no anti-slop rewriter). Total length 60-120 lines. Zero hedge words. At least 1 `<critical>` block, 1 decision ladder, 3 numbers with units, 1 "DEFAULT:" + "exception:" pair.
- depends on: step 4
→ verify: `python3 /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/scripts/audit.py /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/SKILL.md --json | python3 -c "import sys,json; d=json.load(sys.stdin); s=sum(d['pass'].values()); assert s>=8, f'self-audit FAILED: {s}/11 — {d[\"pass\"]}'"` (HARD LIMIT: if this fails, rewrite SKILL.md before proceeding)

**Step 14.** Run audit on the 7 existing skills + CLAUDE.md and write results to `/d/Users/Administrator/Documents/GitHub/orchestrator/docs/steal/R79-opus-mind-baseline.md`. The baseline file must be structured as a markdown table with columns: `file`, `line_count`, `directive_count`, `score`, `verdict`, `top_failures`. Generate via:
```bash
python3 - <<'EOF'
import json, subprocess, sys, pathlib
files = list(pathlib.Path('/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills').glob('*/SKILL.md'))
files.append(pathlib.Path('/d/Users/Administrator/Documents/GitHub/orchestrator/CLAUDE.md'))
rows = []
for f in sorted(files):
    r = json.loads(subprocess.check_output(['python3',
        '/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/scripts/audit.py',
        str(f), '--json']))
    fails = [k for k,v in r['pass'].items() if not v]
    rows.append((str(f.relative_to('/d/Users/Administrator/Documents/GitHub/orchestrator')),
                 r['line_count'], r['directive_count'], f"{r['total_pass']}/11",
                 r['verdict'], ', '.join(fails[:3]) or 'none'))
print('| file | lines | directives | score | verdict | top failures |')
print('|------|-------|------------|-------|---------|--------------|')
for row in rows:
    print('| ' + ' | '.join(str(x) for x in row) + ' |')
EOF
```
Paste output into `R79-opus-mind-baseline.md` under heading `# Baseline — 2026-04-18`.
- depends on: step 4
→ verify: `python3 -c "text=open('/d/Users/Administrator/Documents/GitHub/orchestrator/docs/steal/R79-opus-mind-baseline.md').read(); assert '# Baseline' in text and '/11' in text and 'verdict' in text, 'baseline missing'"`

## Phase Gates

--- PHASE GATE: A → B ---
[ ] Deliverable exists: `audit.py` returns valid JSON with all 11 invariant keys on `CLAUDE.md`
[ ] Acceptance criteria met: `good_8of11.md` scores ≥ 8/11; `bad_hedges.md` fails I1; negator guard test passes; placeholder count is separate from I4
[ ] No open questions: threshold constants set to `MIN_PASS = 8`; Chinese hedges in HEDGES list confirmed
[ ] Owner review: not required — pure Python, no external effects, reversible

--- PHASE GATE: B → C ---
[ ] Deliverable exists: `md-lint-pre-write.sh` exits 2 when fed bad_hedges fixture content; `settings.json` has md-lint hook entry
[ ] Acceptance criteria met: hook does NOT block writes to files outside SKILL.md/CLAUDE.md patterns; exit code 0 for passing content
[ ] No open questions: settings.json key format confirmed against existing file structure
[ ] Owner review: **REQUIRED** — hooks affect every Write/Edit call. Show owner hook code + settings diff before enabling.

--- PHASE GATE: C → D ---
[ ] Deliverable exists: 3 files edited (rationalization-immunity.md, CLAUDE.md, boot.md); grep counts confirm new sections present
[ ] Acceptance criteria met: no banned placeholder phrases in any of the 3 new sections; all verify commands pass
[ ] No open questions: tier vocabulary is exactly 4 levels (T1-T4); Reframe Detection section has all 3 required sub-sections (cue/examples/rationale)
[ ] Owner review: not required — content changes are fully revertible

--- PHASE GATE: D → DONE ---
[ ] Deliverable exists: `SKILL.md` self-audit passes ≥ 8/11; baseline table has ≥ 8 rows
[ ] Acceptance criteria met: no pre-existing skill was modified; baseline scores ranked worst-to-best for follow-up prioritization
[ ] No open questions: baseline reveals which skill scores worst — ranked list ready for owner
[ ] Owner review: **REQUIRED** — baseline exposes technical debt in all existing skills; owner decides fix priority and whether to enforce hook immediately or after fixing worst offenders first

## Non-Goals

- Writing `plan.py`, `fix.py`, `boost.py` (BOOST user-prompt coaching is P1 #6, separate plan)
- Rewriting any existing `.claude/skills/*/SKILL.md` to pass the linter (baseline reveals debt; fix order is owner's call)
- Migrating CLAUDE.md or SKILL.md files from markdown to XML namespace hierarchy (P2 reference-only)
- Implementing the 10-slot user-prompt BOOST checker (P1 #6)
- Backfilling cue+example+rationale for all 12 existing rationalization entries (P1 #10; Step 10 adds the Reframe section only)
- Anti-slop 1-to-1 English word replacement (P2; Chinese context makes the word list irrelevant)
- Pushing to remote (this plan commits to `steal/opus-mind` only; `git push` is owner-triggered)

## Rollback

All changes in this plan are reversible without data loss:

- **Steps 1-7** (new files under `.claude/skills/md-lint/`): `rm -rf /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/md-lint/` restores state. No existing file touched.
- **Step 8** (new hook file): `rm /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/md-lint-pre-write.sh`.
- **Step 9** (settings.json modification): Before editing, back up: `cp settings.json settings.json.bak`. Restore: `cp settings.json.bak settings.json`. The hook will silently skip if the `.sh` file is absent anyway.
- **Steps 10-12** (text appended to rationalization-immunity.md, CLAUDE.md section inserted, boot.md line appended): Each is a targeted append/insert. Reverse by removing the added block. `git diff` isolates exactly which lines were added.
- **Step 13-14** (new SKILL.md + baseline.md): Pure new files. `rm` restores state.

If the pre-write hook causes unexpected write blocks after Step 9: comment out the hook entry in `settings.json` (set `"command": "# disabled"`) — writes proceed immediately, no restart needed.
