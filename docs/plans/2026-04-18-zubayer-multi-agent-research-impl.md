# Plan: Zubayer Multi-Agent Research — P0 Pattern Implementation

## Goal

Three independent hardening tasks land on `main`: (1) `allowed-tools` physical guardrails in 3 high-risk skills, (2) quantified Quality Gate with failure-attribution respawn in `verification-gate` skill, (3) LLM-classifier-based intent router in `scripts/intent_router.py` wired into `routing-hook.sh` for compound-intent detection and skill activation.

## Context

Source: R79 steal report (`docs/steal/R79-zubayer-multi-agent-research-steal.md`).

Key theft targets:
- **P0-1** — `allowed-tools` frontmatter in SKILL.md is Claude Code runtime enforcement (not prompt suggestion). Currently 0 of our 9 skills use it.
- **P0-2** — Weighted 4-dimension quality gate (100 pt, 85% pass threshold) + "fail → attribute → respawn only the guilty agent" loop. Our `verification-gate` SKILL.md has five evidence steps but no weights, no respawn strategy, no iteration cap.
- **P0-3** — `UserPromptSubmit` hook for intent routing. We already have `routing-hook.sh` → `scripts/route_prompt.py`, but it only classifies CHAT/NO_TOKEN/DIRECT/AGENT. It does not identify which skill to activate, and it does not detect compound intents. We skip the source's 30+ keyword regex (lock-in trap) and use a `haiku-4-5` classifier call instead.

## ASSUMPTIONS

- `allowed-tools` is honoured by Claude Code runtime at the SKILL.md `frontmatter` level — this is the source's claim (Triple Validation passed 3/3). If not enforced in the version deployed here, P0-1 steps produce no runtime effect but also cause no regression.
- `claude` CLI is available on PATH for the `haiku-4-5` intent-classifier call in P0-3; if unavailable the hook must degrade silently (already required by existing hook contract).
- The `steal` synthesis phase should be restricted from using `Edit` (not just `Write`) to prevent in-place mutation of the main repo. Source's constraint was `Write`-only exclusion; we extend to `Edit` based on our repo's risk profile.
- `adversarial-dev` agents currently have unconstrained tool access — the frontmatter shows no `allowed-tools` key and the SKILL.md body does not explicitly say "you cannot write files."
- `route_prompt.py` classifier call (`from src.gateway.classifier import classify`) and its import path remain stable — P0-3 adds a new file, not a replacement.
- Haiku API costs for intent routing: at ~100 tokens/call and typical usage, cost is negligible. If owner has cost concerns, the classifier call can be gated behind a `INTENT_ROUTER_ENABLED=1` env var — add this as a follow-up, not in this plan.
- No test suite exists for `.claude/hooks/` or `.claude/skills/` — verification is done via manual invocation / grep / YAML parse rather than pytest.

## File Map

- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/steal/SKILL.md` — Modify (add `allowed-tools` to frontmatter)
- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/verification-gate/SKILL.md` — Modify (add `allowed-tools` to frontmatter + append "Failure Attribution & Respawn" section)
- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/adversarial-dev/SKILL.md` — Modify (add `allowed-tools` to frontmatter)
- `/d/Users/Administrator/Documents/GitHub/orchestrator/scripts/intent_router.py` — Create (new LLM-based intent classifier)
- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/routing-hook.sh` — Modify (add intent-router call after existing `route_prompt.py`)
- `/d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/plan_template.md` — Modify (add "Quality Weights" field spec + `.trash/` atomic-copy note)

---

## Phase A — allowed-tools Physical Guardrails (P0-1)

### Step 1. Add `allowed-tools` to `steal/SKILL.md` frontmatter

Open `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/steal/SKILL.md`.
The current frontmatter (lines 1-4) is:
```yaml
---
name: steal
description: "..."
---
```

Insert one line after `description:`:
```yaml
allowed-tools: Task, Read, Glob, Bash, TodoWrite, Write
```

Rationale: steal skill needs `Write` to produce the steal report. Exclude `Edit` — the steal synthesis phase must write new files, never silently mutate existing ones. `Bash` is needed for git/grep during research.

→ verify: `python3 -c "import yaml, pathlib; fm = pathlib.Path('/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/steal/SKILL.md').read_text(); block = fm.split('---')[1]; d = yaml.safe_load(block); assert 'allowed-tools' in d, 'key missing'; tools = d['allowed-tools']; assert 'Edit' not in tools, f'Edit should be excluded, got: {tools}'; print('OK:', tools)"`

### Step 2. Add `allowed-tools` to `verification-gate/SKILL.md` frontmatter

Open `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/verification-gate/SKILL.md`.
The current frontmatter (lines 1-4) is:
```yaml
---
name: verification-gate
description: "..."
---
```

Insert after `description:`:
```yaml
allowed-tools: Read, Bash, Glob, TodoRead
```

Rationale: verification is read-only audit. `Bash` for running test commands. Explicitly excluding `Write`, `Edit`, `Task` (no sub-spawning) — verification-gate must be a terminal step that observes, not modifies.

→ verify: `python3 -c "import yaml, pathlib; fm = pathlib.Path('/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/verification-gate/SKILL.md').read_text(); d = yaml.safe_load(fm.split('---')[1]); tools = d['allowed-tools']; assert 'Write' not in tools and 'Edit' not in tools and 'Task' not in tools, f'Unexpected tools: {tools}'; print('OK:', tools)"`

### Step 3. Add `allowed-tools` to `adversarial-dev/SKILL.md` frontmatter

Open `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/adversarial-dev/SKILL.md`.
The current frontmatter (lines 1-6) is:
```yaml
---
name: adversarial-dev
description: "..."
user_invocable: true
argument-hint: "..."
---
```

Insert after `argument-hint:`:
```yaml
allowed-tools: Task, Read, Glob, TodoWrite, TodoRead
```

Rationale: adversarial-dev operates through sub-agents (`Task`). The orchestrator role must not write code directly — it spawns Generator and Evaluator agents. Excluding `Write`, `Edit`, `Bash` from the top-level skill forces all code execution through sub-agent `Task` calls.

→ verify: `python3 -c "import yaml, pathlib; fm = pathlib.Path('/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/adversarial-dev/SKILL.md').read_text(); d = yaml.safe_load(fm.split('---')[1]); tools = d['allowed-tools']; assert 'Write' not in tools and 'Edit' not in tools and 'Bash' not in tools, f'Should exclude Write/Edit/Bash, got: {tools}'; print('OK:', tools)"`

### Step 4. Add companion prompt note inside each SKILL.md body

For each of the three skills modified in steps 1-3, insert a one-line warning immediately after the first `#` heading (following the source's pattern of making the constraint visible inside the prompt as well as in the runtime).

In `steal/SKILL.md` after the `# Steal — Systematic Knowledge Extraction` heading, add:
```
> **Tool constraint**: You do NOT have `Edit` tool access. New steal reports must be created with `Write`; never silently mutate existing docs.
```

In `verification-gate/SKILL.md` after the IRON LAW block (line 14), add:
```
> **Tool constraint**: You do NOT have `Write` or `Edit` tool access. This skill is read-only audit. If you need to record a finding, ask the owner to create a file.
```

In `adversarial-dev/SKILL.md` after the `# Adversarial Development` heading, add:
```
> **Tool constraint**: You do NOT have `Write`, `Edit`, or `Bash` tool access. All code generation and execution must go through sub-agent `Task` calls.
```

→ verify for all three:
```bash
grep -n "Tool constraint" \
  /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/steal/SKILL.md \
  /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/verification-gate/SKILL.md \
  /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/adversarial-dev/SKILL.md
```
Expected: 3 lines, one per file.

--- PHASE GATE: Phase A → Phase B ---
[ ] Deliverable exists: all 3 SKILL.md files have `allowed-tools:` in frontmatter (steps 1-3 verify commands pass)
[ ] Deliverable exists: all 3 SKILL.md files have `Tool constraint` prompt note (step 4 grep returns 3 lines)
[ ] No open questions: tool lists are per-skill rationale above
[ ] Owner review: not required (plan IS the approval; change is reversible by removing the frontmatter key)

---

## Phase B — Quantified Quality Gate + Failure Attribution (P0-2)

### Step 5. Add "Quality Gate Weights" block to `verification-gate/SKILL.md`

- depends on: step 2

Open `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/verification-gate/SKILL.md`.
Append the following section after the existing `## Application Scope` section (the last section, ~line 132):

```markdown
## Quality Gate Weights

When verifying a multi-step plan or multi-agent output, score against these four dimensions.
Default weights (can be overridden per-task in the plan header):

| Dimension     | Weight | What it covers |
|---------------|--------|----------------|
| Correctness   |  40 pt | Code compiles, tests pass, happy path + primary edge case succeed |
| Scope         |  25 pt | No unrelated changes; every changed line traces to the task requirement |
| Evidence      |  20 pt | Every completion claim cites actual command output (not "should work") |
| Style         |  15 pt | Matches existing codebase style; no orphan imports/vars from this change |

**Pass threshold: 85 pt (out of 100).**

### Failure Attribution Protocol

If total score < 85:

1. **Identify the lowest-scoring dimension.** Name it explicitly: "Correctness: 28/40 — `test_edge_case` fails."
2. **Name the file and step that owns the failure.** "Failure originates in step 3 (added null check in `src/validators/email.py`, line 42)."
3. **Respawn only the guilty step.** Do not re-run all steps. Spawn a targeted re-execution of the failing step, prepending the failure condition to the prompt: "Previous attempt failed: email validator accepted empty string as valid. Fix the null check at line 42."
4. **Cap at 3 respawn iterations.** If after 3 targeted respawns the score is still < 85, stop and escalate to the owner with: the current score, which dimension is failing, and what was tried.

### Override

To use non-default weights for a specific task, declare in the plan header:
```yaml
quality_weights:
  correctness: 50
  scope: 20
  evidence: 15
  style: 15
```
The gate will use these weights instead of the defaults. Weights must sum to 100.
```

→ verify: `grep -n "Quality Gate Weights\|Failure Attribution Protocol\|Pass threshold\|Cap at 3" /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/verification-gate/SKILL.md`
Expected: 4 matching lines, all in the newly appended section.

### Step 6. Add "Quality Weights" field to `plan_template.md`

Open `/d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/plan_template.md`.
After the `## Goal` section spec (line ~16: `{One sentence, verifiable...}`), insert a new optional field:

```markdown
## Quality Weights (optional)
Override the verification-gate default weights for this plan.
Omit to use defaults (Correctness 40 / Scope 25 / Evidence 20 / Style 15).
```yaml
quality_weights:
  correctness: 40
  scope: 25
  evidence: 20
  style: 15
```
Weights must sum to 100. Declare before the File Map.
```

→ verify: `grep -n "Quality Weights" /d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/plan_template.md`
Expected: 1 line containing "Quality Weights".

### Step 7. Add atomic `.trash/` copy-then-verify note to `plan_template.md`

- depends on: step 6

Open `/d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/plan_template.md`.
Find the `## Boundaries` section (last section). Append the following note after the existing bullets:

```markdown
- **`.trash/` move must be atomic**: Before `mv` to `.trash/`, first `cp -r <src> .trash/<dest>` and verify the copy succeeded (`diff -rq <src> .trash/<dest>` exits 0). Only then `rm -rf <src>`. If the `cp` fails, `rm -rf .trash/<dest>` to avoid a partial copy. This is the archive-script atomicity pattern from R79.
```

→ verify: `grep -n "atomic\|cp -r\|diff -rq" /d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/plan_template.md`
Expected: 1 line containing all three strings proximity (the new note line).

--- PHASE GATE: Phase B → Phase C ---
[ ] Deliverable exists: `verification-gate/SKILL.md` has `Quality Gate Weights` section (step 5 grep returns 4 lines)
[ ] Deliverable exists: `plan_template.md` has `Quality Weights` field (step 6 grep returns 1 line)
[ ] Deliverable exists: `plan_template.md` has `.trash/` atomicity note (step 7 grep returns 1 line)
[ ] No open questions: default weights (40/25/20/15) and 85pt threshold are confirmed from source
[ ] Owner review: not required

---

## Phase C — LLM Intent Router Hook (P0-3)

### Step 8. Create `scripts/intent_router.py` with haiku classifier

Create `/d/Users/Administrator/Documents/GitHub/orchestrator/scripts/intent_router.py` with the following content:

```python
"""Intent router — classify user prompt into primary skill + compound detection.

Called by .claude/hooks/routing-hook.sh after route_prompt.py.
Uses claude-haiku-4-5 (fast, cheap) to classify intent.

Input:  stdin JSON with { "prompt": "...", "cwd": "...", ... }
Output: JSON with { "additionalContext": "..." } | empty

Classification output schema:
  {
    "primary_skill": "<skill-name or null>",
    "is_compound": true | false,
    "secondary_skill": "<skill-name or null>",
    "confidence": "high" | "low"
  }

Skill names recognized:
  steal, verification-gate, adversarial-dev, systematic-debugging,
  prime, doctor, persona, babysit-pr, clawvard-practice

Compound intent rule (from R79 source):
  - is_compound=true only when BOTH intents are strong (user explicitly names two actions)
  - "build a research tool" → NOT compound (compound noun, single planning action)
  - "research X then build Y" → compound (two explicit verbs + two targets)
  - Confidence=low on primary → pass through without injection
"""
import json
import os
import subprocess
import sys
from pathlib import Path

# Recognised skill names (must match .claude/skills/ directory names)
KNOWN_SKILLS = {
    "steal", "verification-gate", "adversarial-dev",
    "systematic-debugging", "prime", "doctor", "persona",
    "babysit-pr", "clawvard-practice",
}

_CLASSIFICATION_PROMPT = """\
You are a skill router for an AI assistant system. Classify the user prompt below.

Available skills: steal, verification-gate, adversarial-dev, systematic-debugging, prime, doctor, persona, babysit-pr, clawvard-practice

Rules:
1. primary_skill: the single best matching skill, or null if none match well.
2. is_compound: true ONLY if the user explicitly requests TWO distinct actions targeting TWO different objects (e.g. "research X then build Y"). A compound noun ("build a research tool") is NOT compound — set is_compound=false.
3. secondary_skill: the second skill if is_compound=true, else null.
4. confidence: "high" if primary intent is unambiguous, "low" if unclear or the prompt is too vague.

Respond ONLY with a JSON object — no prose, no markdown fences:
{"primary_skill": "...", "is_compound": false, "secondary_skill": null, "confidence": "high"}

User prompt:
"""

_COMPOUND_CLARIFICATION_TEMPLATE = (
    "[Intent Router] Your prompt looks like it has two distinct goals:\n"
    "  1. {skill_a} — {desc_a}\n"
    "  2. {skill_b} — {desc_b}\n\n"
    "Which should I focus on first? (Or say 'both in sequence' to run them in order.)"
)

_SKILL_DESCRIPTIONS = {
    "steal": "extract transferable patterns from an external project",
    "verification-gate": "audit and verify completed work with evidence",
    "adversarial-dev": "generator/evaluator loop for rigorous QA",
    "systematic-debugging": "structured root-cause debugging of a failing system",
    "prime": "prime the context with memory and state before a long task",
    "doctor": "diagnose and fix code health issues",
    "persona": "apply a specific persona or communication style",
    "babysit-pr": "monitor and shepherd a pull request to merge",
    "clawvard-practice": "structured practice on a coding challenge",
}


def _call_haiku(prompt: str) -> dict | None:
    """Call claude-haiku-4-5 synchronously. Returns parsed JSON or None on failure."""
    full_prompt = _CLASSIFICATION_PROMPT + prompt

    env = os.environ.copy()
    try:
        result = subprocess.run(
            ["claude", "-p", full_prompt, "--model", "claude-haiku-4-5",
             "--max-tokens", "120", "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=4,          # must stay under hook's 5s timeout
            env=env,
        )
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        # Strip any accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception:
        return None


def _build_skill_reminder(skill: str) -> str:
    """Build a <system-reminder> block that activates the named skill."""
    desc = _SKILL_DESCRIPTIONS.get(skill, skill)
    return (
        f"[Intent Router] This prompt matches the `{skill}` skill "
        f"({desc}). Activate it now by reading "
        f"`.claude/skills/{skill}/SKILL.md` and following its protocol."
    )


def route_intent(prompt: str) -> dict | None:
    """Classify and return routing context, or None for pass-through."""
    classification = _call_haiku(prompt)
    if not classification:
        return None  # haiku unavailable — silent pass-through

    primary = classification.get("primary_skill")
    is_compound = classification.get("is_compound", False)
    secondary = classification.get("secondary_skill")
    confidence = classification.get("confidence", "low")

    # Low confidence or unknown skill → pass through
    if confidence == "low" or primary not in KNOWN_SKILLS:
        return None

    # Compound + both skills known → ask for clarification
    if is_compound and secondary in KNOWN_SKILLS:
        desc_a = _SKILL_DESCRIPTIONS.get(primary, primary)
        desc_b = _SKILL_DESCRIPTIONS.get(secondary, secondary)
        return {
            "additionalContext": _COMPOUND_CLARIFICATION_TEMPLATE.format(
                skill_a=primary, desc_a=desc_a,
                skill_b=secondary, desc_b=desc_b,
            )
        }

    # Single clear intent → inject skill activation reminder
    return {"additionalContext": _build_skill_reminder(primary)}


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        hook_input = json.loads(raw)
        prompt = hook_input.get("prompt", "")
        if not prompt.strip():
            sys.exit(0)

        decision = route_intent(prompt)
        if decision:
            print(json.dumps(decision, ensure_ascii=False))

    except Exception:
        sys.exit(0)  # Hook must never crash


if __name__ == "__main__":
    main()
```

→ verify: `python3 -c "import ast, pathlib; ast.parse(pathlib.Path('/d/Users/Administrator/Documents/GitHub/orchestrator/scripts/intent_router.py').read_text()); print('syntax OK')" && python3 -c "import sys; sys.stdin = open('/dev/null'); sys.path.insert(0, '/d/Users/Administrator/Documents/GitHub/orchestrator'); import scripts.intent_router as m; print('import OK')"`

### Step 9. Wire `intent_router.py` into `routing-hook.sh`

- depends on: step 8

Open `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/routing-hook.sh`.
Current content (full file, 13 lines):
```bash
#!/bin/bash
# Hook: UserPromptSubmit — conversation-level routing
# ...
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
python "$PROJECT_ROOT/scripts/route_prompt.py" 2>/dev/null
```

Replace the last line to add a second classifier that merges both outputs. The hook must emit at most one JSON object. Strategy: run `route_prompt.py` first; if it returns non-empty output, use that (existing behaviour preserved). If it returns empty, run `intent_router.py`.

Replace:
```bash
python "$PROJECT_ROOT/scripts/route_prompt.py" 2>/dev/null
```
With:
```bash
# Read stdin once, pipe to both classifiers in order of priority
INPUT=$(cat)

# Tier 1: existing task-type router (NO_TOKEN / DIRECT / AGENT)
TIER1=$(echo "$INPUT" | python "$PROJECT_ROOT/scripts/route_prompt.py" 2>/dev/null)
if [ -n "$TIER1" ]; then
  echo "$TIER1"
  exit 0
fi

# Tier 2: intent router — skill activation + compound detection
echo "$INPUT" | python "$PROJECT_ROOT/scripts/intent_router.py" 2>/dev/null
```

→ verify: `bash -n /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/routing-hook.sh && echo "syntax OK"` followed by: `echo '{"prompt":"steal this repo","cwd":"."}' | bash /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/routing-hook.sh` (expect either a JSON with `additionalContext` mentioning "steal" skill, or empty output if haiku unavailable — both are valid).

### Step 10. Add smoke test for `intent_router.py` pass-through safety

Create `/d/Users/Administrator/Documents/GitHub/orchestrator/scripts/test_intent_router_passthrough.py` with:

```python
"""Smoke test: intent_router must silently pass through on bad/missing input."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

# Patch subprocess so test runs without a real 'claude' binary
import scripts.intent_router as m


def test_passthrough_on_haiku_failure():
    with patch("scripts.intent_router._call_haiku", return_value=None):
        result = m.route_intent("research this repo and then build a tool")
    assert result is None, f"Expected None passthrough, got {result}"


def test_passthrough_on_low_confidence():
    with patch("scripts.intent_router._call_haiku", return_value={
        "primary_skill": "steal", "is_compound": False,
        "secondary_skill": None, "confidence": "low"
    }):
        result = m.route_intent("maybe do something")
    assert result is None


def test_single_skill_injection():
    with patch("scripts.intent_router._call_haiku", return_value={
        "primary_skill": "steal", "is_compound": False,
        "secondary_skill": None, "confidence": "high"
    }):
        result = m.route_intent("偷师这个项目")
    assert result is not None
    assert "steal" in result["additionalContext"]


def test_compound_clarification():
    with patch("scripts.intent_router._call_haiku", return_value={
        "primary_skill": "steal", "is_compound": True,
        "secondary_skill": "adversarial-dev", "confidence": "high"
    }):
        result = m.route_intent("research this repo then build an adversarial test suite")
    assert result is not None
    ctx = result["additionalContext"]
    assert "steal" in ctx and "adversarial-dev" in ctx


if __name__ == "__main__":
    test_passthrough_on_haiku_failure()
    test_passthrough_on_low_confidence()
    test_single_skill_injection()
    test_compound_clarification()
    print("All 4 smoke tests passed.")
```

→ verify: `python3 /d/Users/Administrator/Documents/GitHub/orchestrator/scripts/test_intent_router_passthrough.py`
Expected output: `All 4 smoke tests passed.`

--- PHASE GATE: Phase C → Done ---
[ ] Deliverable exists: `scripts/intent_router.py` passes syntax + import check (step 8 verify)
[ ] Deliverable exists: `routing-hook.sh` is syntactically valid and passes bash -n (step 9 verify)
[ ] Deliverable exists: 4 smoke tests pass (step 10 verify)
[ ] No open questions: haiku unavailability gracefully degrades to pass-through (test_passthrough_on_haiku_failure covers this)
[ ] Owner review: not required

---

## Non-Goals

- No implementation of P1 patterns (AskUserQuestion conflict handling for steal, archive transactional shell script, current/history state split) — they are in steal report as P1, not P0.
- No replacement of existing `route_prompt.py` — the intent router is additive (Tier 2 fallback), not a replacement.
- No port of the source's `spec-workflow-orchestrator` multi-agent pipeline — we already have `plan_template.md` + subagent dispatch; the source's sequential planning pipeline (spec-analyst → spec-architect → spec-planner) adds nothing we lack.
- No TS quality-gates file — source's own HONEST_REVIEW.md says it's a disconnected orphan.
- No migration of the regex keyword list from `skill-rules.json` — assessed as lock-in trap; LLM classifier replaces it.
- No changes to `SOUL/private/` — P0 patterns are infrastructure, not identity.

## Rollback

Each phase is independently reversible:

**Phase A** (allowed-tools): Remove the `allowed-tools:` key from the three SKILL.md frontmatters and the `Tool constraint` prompt note. No runtime state changed.
```bash
# Example rollback for steal/SKILL.md — repeat for other two
# Remove the allowed-tools line from frontmatter (edit manually or via sed)
sed -i '/^allowed-tools:/d' .claude/skills/steal/SKILL.md
sed -i '/^> \*\*Tool constraint\*\*/d' .claude/skills/steal/SKILL.md
```

**Phase B** (Quality Gate): Remove the `## Quality Gate Weights` section from `verification-gate/SKILL.md` and the two additions to `plan_template.md`. Grep + manual delete.

**Phase C** (Intent Router): Revert `routing-hook.sh` to single-line `python ... route_prompt.py`, delete `scripts/intent_router.py` and `scripts/test_intent_router_passthrough.py`. All reversible with standard `mv` to `.trash/` before deletion.

No database migrations, no environment variables, no external service calls introduced — full rollback is always available.
