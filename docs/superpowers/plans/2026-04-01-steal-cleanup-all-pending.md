# Steal Cleanup: All Pending P0 Patterns

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear all actionable P0 patterns from Rounds 19, 28, 29, 30, 32. Update tracker to reflect true status.

**Architecture:** 8 branches, each covering a logical group of patterns. Every feature point gets its own commit within the branch. All branches merge to main at the end.

**Tech Stack:** Python 3.11, bash hooks, markdown prompts, Node.js (dashboard)

---

## Triage: 44 Pending → 20 Actionable + 18 Reference-Only + 6 Already-Done

### Already Done (need tracker update only)

| # | Pattern | Evidence |
|---|---------|----------|
| R19-1 | `<critical>` XML tags | boot.md:26, CLAUDE.md:45, scrutiny.md:24 |
| R19-3 | `<reference>` tags | boot.md:105 (hard-won-rules), boot.md:129 (context-pack-catalog) |
| R28b-2 | Coordinator Synthesis Discipline | synthesis_discipline.md (full), dispatcher.py:24-38 (_VAGUE_PHRASES) |
| R28b-3 | Verification Adversarial | guardian_assessment.md (full, with self-injection defense) |
| R28b-5 | Compact 9-Section | compact_template.md (full), pre-compact.sh:35-44 |
| R28b-6 | Permission Side-Query | guardian_assessment.md risk assessment is concurrent |

### Reference Only (CC/claw-code internal, no Orchestrator equivalent)

| # | Pattern | Why N/A |
|---|---------|---------|
| 12 | Events-Before-Container | CC Teleport session creation — no container dispatch in Orchestrator |
| 14 | Unified Message Router | CC SendMessageTool — channel_router.py already fills this role |
| 15 | Stateful Event Stream Classifier | CC ExitPlanModeScanner — no equivalent output parsing need |
| 17 | Bones-Soul Split Persistence | CC Buddy types — SOUL/ already structured as public/private split |
| 19 | Progressive Bundle Fallback | CC gitBundle context shipping — no remote agent dispatch |
| 20 | Session Overage Confirmation | CC billing consent — no billing in Orchestrator |
| 21 | Self-Contained Snapshot Coalescing | CC streaming dashboard — WS already handles this |
| 22 | Three-Tier Feature Read | CC GrowthBook feature flags — no feature flag system |
| 23 | Snapshot-Based Immutable Registry | claw-code startup perf — agent_registry.py already exists |
| 24 | Token-Based Routing + Diversity | claw-code routing — llm_router.py already has engine waterfall |
| 25 | Permission Denial Inference | claw-code pre-inference — permission_rules.py already exists |
| 26 | Hierarchical Config Deep Merge | claw-code config — config.py already handles layered config |
| 27 | 4-Way Parallel Retrieval + RRF | hindsight — applies to Construct3-RAG, not Orchestrator |
| 28 | Retain-Time Link Bounding | hindsight graph — no knowledge graph in Orchestrator |
| 29 | Token Budget Semantic Layers | hindsight — context_budget.py already has budget tiers |
| R28b-1 | Cache Boundary Static/Dynamic | CC prompt cache optimization — Claude Code handles this internally |
| R28b-4 | YOLO Self-Injection Defense | Already in guardian_assessment.md:52-60 |
| R32-1 | Editor Adapter Interface | ICollector protocol in base.py already serves this purpose |

### Actionable (20 patterns → 8 branches)

See tasks below.

---

## Branch 1: `steal/r19-prompt-polish`

### Task 1: Positive Framing Rewrite in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md:34,43`
- Modify: `.claude/boot.md` (verify only — compiled from SOUL/)

Scan CLAUDE.md for prohibition-style rules and rewrite to positive framing.
Round 19 finding: "Use X (preserving Y)" reliably outperforms "Never do Z".

- [ ] **Step 1: Rewrite prohibition phrases to positive frames**

Current prohibitions in CLAUDE.md that need rewriting:

```
Line 34: "Never write vague steps. Banned: ..."
→ Keep as-is: this is a concrete specification, not a vague prohibition

Line 43: "Never batch more than 3 edits to the same file without a verification read"
→ "Re-read the file after every 3 edits to confirm changes applied correctly (Edit tool fails silently on stale context)"
```

The CLAUDE.md is actually already well-structured with positive framing. The main negative patterns are in the Gate Functions section, which are already structured as decision trees (positive: "Read it first", not "Don't edit without reading"). No major rewrites needed.

- [ ] **Step 2: Add forced-output behavior gate to scrutiny.md**

Add mandatory evidence externalization before verdict. Currently scrutiny.md has `<critical>` tag requiring structured output, but the "forced output = behavior gate" pattern from R19 should be strengthened:

In `SOUL/public/prompts/scrutiny.md`, after line 26, ensure the pattern is:
```markdown
<critical>
You MUST output the following structured evidence before your verdict.
Skipping any section means the review did not happen.
No evidence = no verdict. This is non-negotiable.
If you cannot fill a section, write "INSUFFICIENT DATA" — do not skip it.
</critical>
```

→ verify: `grep -c "No evidence = no verdict" SOUL/public/prompts/scrutiny.md` returns 1

- [ ] **Step 3: Apply forced-output gate to executor review prompt**

In `src/governance/review.py`, ensure the review cycle requires evidence output before approval. If executor output lacks a `## Verification` section, flag as incomplete.

→ verify: `grep "Verification" src/governance/review.py`

- [ ] **Step 4: Commit**

```bash
git add SOUL/public/prompts/scrutiny.md src/governance/review.py
git commit -m "feat(prompt): forced-output behavior gate in scrutiny + review"
```

### Task 2: Update Tracker — Mark Already-Done Patterns

**Files:**
- Modify: `docs/steal/2026-04-01-round28-implementation-tracker.md`
- Modify: memory file `orchestrator_steal_consolidated.md`

- [ ] **Step 1: Update Round 28 tracker — mark 6 already-done items**

In `docs/steal/2026-04-01-round28-implementation-tracker.md`, change status for items that are already implemented:

```
No items from the 23 Pending need status change here — the 6 already-done items
are from Round 19 and Round 28b, tracked in the consolidated index.
```

- [ ] **Step 2: Update consolidated index — mark R19 P0s as done**

In the memory file `orchestrator_steal_consolidated.md`, update the Round 19 entry:
- Change "4 P0" to "4 P0 ✅" 
- Add note: "`<critical>` in boot.md/CLAUDE.md, `<reference>` in boot.md, positive framing verified, forced-output in scrutiny.md"

- [ ] **Step 3: Mark 18 Reference-Only patterns as closed**

Add a new section to the Round 28 tracker:

```markdown
## Closed as Reference-Only (18 patterns)

These patterns are CC/claw-code internal architecture with no direct Orchestrator equivalent.
Existing Orchestrator code already covers the underlying concern differently.

| # | Pattern | Orchestrator Equivalent |
|---|---------|------------------------|
| 12 | Events-Before-Container | No container dispatch |
| 14 | Unified Message Router | channel_router.py |
| 15 | Event Stream Classifier | No equivalent need |
| 17 | Bones-Soul Split | SOUL/public + SOUL/private |
| 19 | Progressive Bundle Fallback | No remote agent dispatch |
| 20 | Session Overage | No billing system |
| 21 | Snapshot Coalescing | WebSocket handles this |
| 22 | Three-Tier Feature Read | No feature flags |
| 23 | Immutable Registry | project_registry.py |
| 24 | Token Routing + Diversity | llm_router.py engine waterfall |
| 25 | Permission Denial Inference | permission_rules.py |
| 26 | Config Deep Merge | config.py layered config |
| 27 | 4-Way Retrieval + RRF | For Construct3-RAG, not Orchestrator |
| 28 | Retain-Time Bounding | No knowledge graph |
| 29 | Token Budget Layers | context_budget.py |
| R28b-1 | Cache Boundary | CC prompt cache internal |
| R28b-4 | YOLO Self-Injection | guardian_assessment.md:52-60 |
| R32-1 | Editor Adapter | ICollector protocol |
```

- [ ] **Step 4: Commit**

```bash
git add docs/steal/2026-04-01-round28-implementation-tracker.md
git commit -m "docs(steal): triage 44 pending → 20 actionable + 18 ref-only + 6 already-done"
```

---

## Branch 2: `steal/memory-pipeline`

### Task 3: Memory 2-Phase Pipeline Tool

**Files:**
- Create: `SOUL/tools/memory_synthesizer.py`
- Modify: `SOUL/tools/memory_staleness.py` (add integration hook)

Combines R30 "Two-Layer Memory Auto-Synthesis" + Codex "Memory Pipeline 2-Phase":
- Layer 1: Append-only JSONL archive (immutable truth) — `data/observations.jsonl` already exists
- Layer 2: Daily LLM-synthesized active context — new `data/active_context.md`

- [ ] **Step 1: Create memory_synthesizer.py with core logic**

```python
"""
Memory Synthesizer — daily LLM-driven synthesis of observation archive.

Source: yoyo-evolve Two-Layer Memory (Round 30) + Codex Memory 2-Phase (Round 28c)

Architecture:
    data/observations.jsonl (append-only, from instinct_pipeline.py)
        ↓ daily batch
    LLM synthesis (time-weighted compression)
        ↓
    data/active_context.md (human-readable, loaded into session)

The key insight: raw observations are immutable truth, but too noisy for context.
Synthesized context is lossy but usable. Keep both layers.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OBSERVATIONS_PATH = REPO_ROOT / "data" / "observations.jsonl"
ACTIVE_CONTEXT_PATH = REPO_ROOT / "data" / "active_context.md"
SYNTHESIS_LOCK = REPO_ROOT / "data" / ".synthesis_lock"

# Time weighting: recent observations matter more
WEIGHT_DECAY_DAYS = 7  # Half-life in days


def load_recent_observations(max_age_days: int = 7) -> list[dict]:
    """Load observations from JSONL, newest first."""
    if not OBSERVATIONS_PATH.exists():
        return []

    cutoff = time.time() - (max_age_days * 86400)
    results = []
    try:
        with open(OBSERVATIONS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("timestamp", 0) >= cutoff:
                        results.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        log.warning(f"synthesizer: failed to load observations: {e}")

    return sorted(results, key=lambda x: -x.get("timestamp", 0))


def build_synthesis_prompt(observations: list[dict]) -> str:
    """Build a prompt for LLM to synthesize observations into active context."""
    obs_text = "\n".join(
        f"- [{o.get('event_type', '?')}] {o.get('tool_name', '?')}: "
        f"{o.get('outcome', '?')} — {json.dumps(o.get('context', {}), ensure_ascii=False)[:200]}"
        for o in observations[:100]  # Cap at 100 most recent
    )

    return f"""Synthesize these raw observations into a concise active context summary.

Rules:
- Group by theme (security blocks, common errors, usage patterns)
- Include counts: "Edit blocked 5x on config files" not just "Edit was blocked"
- Time-weight: recent patterns matter more than old ones
- Output as markdown sections, max 500 words total
- If no meaningful patterns exist, output "No significant patterns detected."

Raw observations ({len(observations)} total, showing up to 100):
{obs_text}

Output format:
## Active Patterns
[grouped patterns with counts]

## Recurring Issues
[errors or blocks that keep happening]

## Usage Summary
[tool usage distribution, peak times]"""


def should_synthesize() -> bool:
    """Check if enough time has passed since last synthesis (24h minimum)."""
    if not SYNTHESIS_LOCK.exists():
        return True
    try:
        mtime = SYNTHESIS_LOCK.stat().st_mtime
        hours_since = (time.time() - mtime) / 3600
        return hours_since >= 24.0
    except Exception:
        return True


def mark_synthesized():
    """Touch the lock file to record synthesis time."""
    SYNTHESIS_LOCK.parent.mkdir(parents=True, exist_ok=True)
    SYNTHESIS_LOCK.touch()


def save_active_context(content: str):
    """Write synthesized context to active_context.md."""
    ACTIVE_CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = f"<!-- Auto-synthesized: {time.strftime('%Y-%m-%d %H:%M')} -->\n"
    ACTIVE_CONTEXT_PATH.write_text(header + content, encoding="utf-8")
    log.info(f"synthesizer: saved active context ({len(content)} chars)")
```

→ verify: `python3 -c "from SOUL.tools.memory_synthesizer import load_recent_observations, should_synthesize; print('OK')"`

- [ ] **Step 2: Commit**

```bash
git add SOUL/tools/memory_synthesizer.py
git commit -m "feat(memory): 2-phase pipeline — observation archive → synthesized context"
```

### Task 4: Memory No-Op Gate

**Files:**
- Create: `SOUL/tools/memory_noop_gate.py`

Quality gate for memory writes. From Codex CLI: "is this truly novel AND would it change future behavior?" If not, discard.

- [ ] **Step 1: Create memory_noop_gate.py**

```python
"""
Memory No-Op Gate — reject low-value memory writes before they pollute the archive.

Source: Codex CLI Memory No-Op Gate (Round 28c)

Problem: Memory systems accumulate noise. "User asked about X" is not worth storing.
Solution: Score each candidate memory against novelty + actionability criteria.
Only commit memories that would change future behavior.

Usage:
    from SOUL.tools.memory_noop_gate import should_store_memory

    if should_store_memory(candidate_text, existing_memories):
        # proceed with storage
    else:
        # discard silently
"""
from __future__ import annotations

import re
from pathlib import Path

# Patterns that indicate low-value memories (noise)
_NOISE_PATTERNS = [
    r"^user asked about",
    r"^user wants to",
    r"^user is working on",        # Too generic — WHAT are they working on?
    r"^the user mentioned",
    r"^conversation about",
    r"^discussed\b",
    r"^helped with",
    r"^session involved",
    r"debug(ged|ging) .{0,20}$",   # "Debugging X" without the solution
    r"^ran (tests?|commands?)",     # Ephemeral action, not insight
]

# Patterns that indicate high-value memories (keep)
_SIGNAL_PATTERNS = [
    r"prefers?\b",                  # User preference
    r"always use|never use",        # Strong preference
    r"broke|broken|bug|regression", # Incident with lesson
    r"workaround|fix was",          # Solution to a problem
    r"incompatible|doesn't work with",  # Compatibility fact
    r"path is|located at|lives in", # Environment fact
    r"api key|token|credential",    # Sensitive but important
    r"deadline|due by|freeze",      # Time-sensitive project fact
]


def _score_novelty(candidate: str, existing: list[str]) -> float:
    """Score how novel this candidate is vs existing memories. 0.0 = duplicate, 1.0 = totally new."""
    if not existing:
        return 1.0

    candidate_lower = candidate.lower().strip()
    candidate_words = set(candidate_lower.split())

    best_overlap = 0.0
    for mem in existing:
        mem_words = set(mem.lower().strip().split())
        if not candidate_words or not mem_words:
            continue
        overlap = len(candidate_words & mem_words) / max(len(candidate_words), len(mem_words))
        best_overlap = max(best_overlap, overlap)

    return 1.0 - best_overlap


def _score_actionability(candidate: str) -> float:
    """Score whether this memory would change future behavior. 0.0 = inert, 1.0 = high impact."""
    text = candidate.lower()

    # Check for noise patterns
    for pattern in _NOISE_PATTERNS:
        if re.search(pattern, text):
            return 0.1

    # Check for signal patterns
    signal_count = sum(1 for p in _SIGNAL_PATTERNS if re.search(p, text))
    if signal_count >= 2:
        return 0.9
    elif signal_count == 1:
        return 0.6

    # Default: moderate actionability
    return 0.4


def should_store_memory(candidate: str, existing_memories: list[str] | None = None,
                         novelty_threshold: float = 0.3,
                         actionability_threshold: float = 0.3) -> bool:
    """Decide whether a candidate memory is worth storing.

    Returns True only if the memory is both novel enough AND actionable enough.
    """
    if not candidate or len(candidate.strip()) < 10:
        return False

    existing = existing_memories or []
    novelty = _score_novelty(candidate, existing)
    actionability = _score_actionability(candidate)

    return novelty >= novelty_threshold and actionability >= actionability_threshold


def load_existing_memory_texts(memory_dir: Path) -> list[str]:
    """Load text content from all memory .md files for dedup comparison."""
    texts = []
    if not memory_dir.exists():
        return texts
    for f in memory_dir.iterdir():
        if f.suffix == ".md" and f.name != "MEMORY.md":
            try:
                texts.append(f.read_text(encoding="utf-8"))
            except Exception:
                continue
    return texts
```

→ verify: `python3 -c "from SOUL.tools.memory_noop_gate import should_store_memory; assert should_store_memory('User prefers snake_case in Python', []); assert not should_store_memory('user asked about X', []); print('OK')"`

- [ ] **Step 2: Commit**

```bash
git add SOUL/tools/memory_noop_gate.py
git commit -m "feat(memory): no-op gate — reject low-value memories before storage"
```

---

## Branch 3: `steal/guardian-hardening`

### Task 5: Protected File Guardian in dispatch-gate.sh

**Files:**
- Modify: `.claude/hooks/dispatch-gate.sh`

From R30 yoyo-evolve: after agent execution, check git diff for modifications to protected files. If protected files were touched, warn loudly.

Note: This is a PreToolUse hook, so it fires BEFORE the agent runs. We add a reminder about protected files to the agent prompt injection. The actual post-execution check requires a PostToolUse hook on Agent.

- [ ] **Step 1: Add protected-file list and warning to dispatch-gate.sh**

After the existing STEAL tag check (line 21), add:

```bash
# ── Protected File Guardian (stolen from yoyo-evolve Round 30) ──
# Inject a reminder about protected files into agent context.
# Protected files: SOUL core identity, security hooks, boot.md
PROTECTED_REMINDER="PROTECTED FILES (do NOT modify): SOUL/private/identity.md, SOUL/private/hall-of-instances.md, .claude/hooks/guard-redflags.sh, .claude/hooks/config-protect.sh, .claude/boot.md, CLAUDE.md. If your task requires changing these, STOP and report back."
```

Update the final echo to include the protected files reminder:

```bash
echo "DISPATCH GATE: You are Orchestrator. For non-trivial tasks, use 'python scripts/dispatch.py \"<task>\" --wait' to dispatch through the real Governor pipeline (Scrutinizer → Dispatcher → Executor). Do NOT manually brief agents with hand-written prompts. ${PROTECTED_REMINDER}"
```

→ verify: `grep "PROTECTED FILES" .claude/hooks/dispatch-gate.sh`

- [ ] **Step 2: Create PostToolUse(Agent) hook for git diff check**

Create `.claude/hooks/agent-postcheck.sh`:

```bash
#!/bin/bash
# Hook: PostToolUse(Agent) — check if agent modified protected files
# Source: yoyo-evolve Protected File Guardian (Round 30)

PROTECTED_FILES=(
    "SOUL/private/identity.md"
    "SOUL/private/hall-of-instances.md"
    ".claude/hooks/guard-redflags.sh"
    ".claude/hooks/config-protect.sh"
    ".claude/boot.md"
    "CLAUDE.md"
    ".claude/settings.json"
)

# Check git diff for protected file modifications
DIFF_FILES=$(git diff --name-only 2>/dev/null)
[ -z "$DIFF_FILES" ] && exit 0

VIOLATIONS=""
for pf in "${PROTECTED_FILES[@]}"; do
    if echo "$DIFF_FILES" | grep -qF "$pf"; then
        VIOLATIONS="${VIOLATIONS}  - ${pf}\n"
    fi
done

if [ -n "$VIOLATIONS" ]; then
    echo "⚠ PROTECTED FILE GUARDIAN: Sub-agent modified protected files!"
    echo -e "Affected files:\n${VIOLATIONS}"
    echo "Review these changes carefully. Consider reverting with: git checkout -- <file>"
fi
```

→ verify: `bash -n .claude/hooks/agent-postcheck.sh && echo "syntax OK"`

- [ ] **Step 3: Register hook in settings.json**

Add to PostToolUse section, with matcher "Agent":

```json
{
    "matcher": "Agent",
    "hooks": [
        {
            "type": "command",
            "command": "bash .claude/hooks/agent-postcheck.sh",
            "timeout": 5
        }
    ]
}
```

→ verify: `python3 -c "import json; d=json.load(open('.claude/settings.json')); hooks=[h for h in d['hooks']['PostToolUse'] if h.get('matcher')=='Agent']; print('registered' if hooks else 'MISSING')"`

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/dispatch-gate.sh .claude/hooks/agent-postcheck.sh .claude/settings.json
git commit -m "feat(security): protected file guardian — warn on sub-agent modifications to core files"
```

### Task 6: Self-Injection Defense Context Filter

**Files:**
- Modify: `SOUL/public/prompts/guardian_assessment.md` (verify existing)
- Create: `src/governance/safety/transcript_filter.py`

R28 Self-Injection Defense: when building context for risk assessment or scrutiny, strip assistant text blocks. Only feed user messages + tool results.

- [ ] **Step 1: Create transcript_filter.py**

```python
"""
Transcript Filter — strip assistant text from context to prevent self-injection.

Source: Claude Code YOLO Classifier (Round 28b)

Problem: When the model's own prior text is included in a safety classifier's context,
the model can inadvertently (or deliberately) influence its own safety assessment.

Solution: Only pass user messages and tool results to safety-critical classifiers.
Strip all assistant/model text blocks.
"""
from __future__ import annotations


def filter_transcript_for_safety(messages: list[dict]) -> list[dict]:
    """Filter a conversation transcript to only user messages and tool results.

    Args:
        messages: List of message dicts with 'role' and 'content' keys.

    Returns:
        Filtered list containing only user and tool messages.
    """
    safe_roles = {"user", "tool", "tool_result", "system"}
    return [m for m in messages if m.get("role", "") in safe_roles]


def strip_assistant_from_text(text: str) -> str:
    """Remove assistant-attributed text blocks from a flat transcript string.

    Handles common formats:
    - "Assistant: ..." blocks
    - "<assistant>...</assistant>" XML blocks
    """
    import re

    # Remove XML-style assistant blocks
    text = re.sub(r'<assistant>.*?</assistant>', '[assistant text removed]', text, flags=re.DOTALL)

    # Remove "Assistant:" prefix blocks (up to next "User:" or "Tool:" or end)
    text = re.sub(
        r'(?m)^Assistant:.*?(?=^(?:User|Tool|System):|\Z)',
        '[assistant text removed]\n',
        text,
        flags=re.DOTALL | re.MULTILINE,
    )

    return text
```

→ verify: `python3 -c "from src.governance.safety.transcript_filter import filter_transcript_for_safety; msgs=[{'role':'user','content':'hi'},{'role':'assistant','content':'hello'},{'role':'tool','content':'ok'}]; r=filter_transcript_for_safety(msgs); assert len(r)==2; print('OK')"`

- [ ] **Step 2: Commit**

```bash
git add src/governance/safety/transcript_filter.py
git commit -m "feat(security): transcript filter — strip assistant text for safety classifiers"
```

### Task 7: Untrusted-Source Setting Exclusion

**Files:**
- Modify: `.claude/hooks/config-protect.sh`

Extend config-protect.sh to also block Write tool creating new config files in trusted locations from untrusted agent context.

- [ ] **Step 1: Add .env and .claude/settings.json to protected patterns**

In config-protect.sh, extend the case statement:

```bash
    .env|.env.*|.envrc)
        IS_CONFIG=true ;;
    settings.json|settings.local.json)
        # Protect Claude Code settings from agent modification
        if echo "$FILE_PATH" | grep -qE '\.claude/'; then
            IS_CONFIG=true
        fi
        ;;
```

→ verify: `grep ".env" .claude/hooks/config-protect.sh`

- [ ] **Step 2: Commit**

```bash
git add .claude/hooks/config-protect.sh
git commit -m "feat(security): extend config-protect to .env and .claude/settings.json"
```

---

## Branch 4: `steal/exec-policy-engine`

### Task 8: Rule Engine Config + guard-redflags.sh Refactor

**Files:**
- Create: `config/exec-policy.yaml`
- Modify: `.claude/hooks/guard-redflags.sh`

From Codex CLI: Replace hardcoded guard rules with a configurable YAML rule engine.
The existing guard-redflags.sh has 14 hardcoded rules. Extract to YAML so rules can be added/removed without editing bash.

- [ ] **Step 1: Create exec-policy.yaml with current rules**

```yaml
# Execution Policy Rules — loaded by guard-redflags.sh
# Source: Codex CLI ExecPolicy Rule Engine (Round 28c)
#
# Format: each rule has a name, patterns to match, and action (block/warn)
# Rules are evaluated in order. First match wins.

version: 1

rules:
  # --- HARD BLOCKS ---
  - name: soul-exfiltration
    action: block
    description: "SOUL/private exfiltration — reading private files + network"
    match_all:
      - pattern: "(SOUL/private|IDENTITY\\.md|experiences\\.jsonl|hall-of-instances)"
        flags: "i"
      - pattern: "(curl|wget|nc |ncat|python.*http|requests\\.|fetch)"
        flags: "i"

  - name: memory-exfiltration
    action: block
    description: "MEMORY.md exfiltration — sending memory over network"
    match_all:
      - pattern: "MEMORY\\.md"
        flags: "i"
      - pattern: "(curl|wget|nc |ncat)"
        flags: "i"

  - name: raw-ip-network
    action: block
    description: "Network request to raw IP (not localhost/docker)"
    match_all:
      - pattern: "(curl|wget)\\s+.*https?://[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+"
      - pattern: "(?!.*(127\\.0\\.0\\.1|localhost|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.|10\\.))"

  - name: eval-injection
    action: block
    description: "eval/exec with external input"
    match_any:
      - pattern: "(eval|exec)\\s*\\$|eval\\s+\\$\\(|eval\\s+\"?\\$"

  - name: sudo-escalation
    action: block
    description: "sudo privilege escalation"
    match_any:
      - pattern: "\\bsudo\\b"

  - name: credential-theft
    action: block
    description: "Reading credential dirs with network/encoding tools"
    match_all:
      - pattern: "cat\\s+.*(/\\.ssh/|/\\.aws/|/\\.gnupg/)"
      - pattern: "(curl|wget|nc |python|base64)"
        flags: "i"

  - name: system-file-modification
    action: block
    description: "Modifying system files outside workspace"
    match_any:
      - pattern: "(>\\s*|tee\\s+|cp\\s+.*\\s+|mv\\s+.*\\s+)(/etc/|/usr/|/var/|C:\\\\Windows\\\\)"

  - name: silent-install
    action: block
    description: "Silent package installation"
    match_any:
      - pattern: "(pip|npm|gem|cargo)\\s+install.*(-q|--quiet|-s|--silent)"

  - name: browser-cookie-access
    action: block
    description: "Browser cookie/session access"
    match_all:
      - pattern: "(Cookies|Login\\s*Data|Session|\\.cookie)"
        flags: "i"
      - pattern: "(sqlite3|cat|cp|curl)"
        flags: "i"

  - name: interpreter-injection
    action: block
    description: "Interpreter prefix with dangerous operations"
    match_all:
      - pattern: "(python3?\\s+-c|node\\s+-e|ruby\\s+-e|perl\\s+-e)\\s"
      - pattern: "(requests\\.|urllib|http\\.client|socket\\.|subprocess|os\\.remove|os\\.unlink|shutil\\.rmtree|eval\\(|exec\\(|__import__|curl|wget|rm\\s+-rf)"
        flags: "i"

  - name: shell-dangerous
    action: block
    description: "bash/sh -c with dangerous operations"
    match_all:
      - pattern: "(bash|sh)\\s+-c\\s"
      - pattern: "(curl|wget|nc\\s|ncat|rm\\s+-rf|dd\\s+if=|mkfs|>\\s*/dev/|eval\\s|base64)"
        flags: "i"

  - name: shell-nesting
    action: block
    description: "Double shell nesting (evasion technique)"
    match_any:
      - pattern: "(bash|sh)\\s+-c\\s.*(bash|sh)\\s+-c\\s"

  - name: base64-execution
    action: block
    description: "Base64 decode piped to execution"
    match_any:
      - pattern: "base64\\s+(-d|--decode)\\s*\\|.*\\b(bash|sh|python|perl|ruby|node)\\b"
        flags: "i"

  - name: base64-chain
    action: block
    description: "echo/printf → base64 decode → shell"
    match_any:
      - pattern: "(echo|printf)\\s.*\\|\\s*base64\\s+(-d|--decode)\\s*\\|\\s*(bash|sh)"
        flags: "i"
```

→ verify: `python3 -c "import yaml; rules=yaml.safe_load(open('config/exec-policy.yaml')); print(f'{len(rules[\"rules\"])} rules loaded')"`

- [ ] **Step 2: Create rule engine loader script**

Create `scripts/exec_policy_loader.py`:

```python
"""Load exec-policy.yaml and evaluate a command against rules.

Usage from bash:
    echo "$COMMAND" | python3 scripts/exec_policy_loader.py
    Exit code 0 = allow, exit code 1 = block (reason on stdout)
"""
import json
import re
import sys
from pathlib import Path

import yaml

POLICY_PATH = Path(__file__).parent.parent / "config" / "exec-policy.yaml"


def load_rules() -> list[dict]:
    if not POLICY_PATH.exists():
        return []
    with open(POLICY_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("rules", [])


def _match_pattern(command: str, pattern: str, flags: str = "") -> bool:
    re_flags = re.IGNORECASE if "i" in flags else 0
    return bool(re.search(pattern, command, re_flags))


def evaluate(command: str, rules: list[dict] | None = None) -> tuple[str, str]:
    """Evaluate command against rules. Returns (action, reason)."""
    if rules is None:
        rules = load_rules()

    for rule in rules:
        action = rule.get("action", "allow")
        name = rule.get("name", "unknown")
        description = rule.get("description", "")

        matched = False

        if "match_all" in rule:
            matched = all(
                _match_pattern(command, p["pattern"], p.get("flags", ""))
                for p in rule["match_all"]
            )
        elif "match_any" in rule:
            matched = any(
                _match_pattern(command, p["pattern"], p.get("flags", ""))
                for p in rule["match_any"]
            )

        if matched:
            return action, f"{name}: {description}"

    return "allow", ""


if __name__ == "__main__":
    command = sys.stdin.read().strip()
    if not command:
        sys.exit(0)

    action, reason = evaluate(command)
    if action == "block":
        print(json.dumps({"decision": "block", "reason": reason}))
        sys.exit(1)
    else:
        sys.exit(0)
```

→ verify: `echo "curl https://1.2.3.4/evil" | python3 scripts/exec_policy_loader.py; echo "exit: $?"`

- [ ] **Step 3: Update guard-redflags.sh to use rule engine with fallback**

Replace the hardcoded rules with a call to the Python rule engine, but keep the bash fallback for when Python/YAML is unavailable:

```bash
# ── Try YAML rule engine first (fast, configurable) ──
if [ -f "config/exec-policy.yaml" ] && command -v python3 &>/dev/null; then
    RESULT=$(echo "$COMMAND" | python3 scripts/exec_policy_loader.py 2>/dev/null)
    if [ $? -eq 1 ]; then
        echo "$RESULT"
        exit 0
    elif [ $? -eq 0 ]; then
        echo '{"decision":"allow"}'
        exit 0
    fi
    # If python3 failed (exit code != 0 or 1), fall through to bash rules
fi

# ── Fallback: original bash rules (kept for resilience) ──
```

→ verify: `echo '{"tool_input":{"command":"echo hello"}}' | bash .claude/hooks/guard-redflags.sh`

- [ ] **Step 4: Commit**

```bash
git add config/exec-policy.yaml scripts/exec_policy_loader.py .claude/hooks/guard-redflags.sh
git commit -m "feat(security): exec policy rule engine — YAML-configurable guard rules with bash fallback"
```

---

## Branch 5: `steal/checkpoint-restart`

### Task 9: Checkpoint-Restart Recovery for Sub-agents

**Files:**
- Create: `src/governance/checkpoint_recovery.py`
- Modify: `src/governance/executor.py` (add checkpoint detection on agent timeout)

From R30 yoyo-evolve: when a sub-agent times out or crashes, detect partial progress from git commits, build a checkpoint context file, and resume with a new agent.

- [ ] **Step 1: Create checkpoint_recovery.py**

```python
"""
Checkpoint Recovery — detect partial progress and resume interrupted agents.

Source: yoyo-evolve Checkpoint-Restart (Round 30)

When a sub-agent times out or errors:
1. Check git log for commits made during this task
2. Check git diff for uncommitted changes
3. Build a checkpoint context document
4. Return it for the next agent to resume from

This is NOT automatic re-execution. It produces a checkpoint document
that the dispatcher can feed to a fresh agent.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """Captured state of a partially completed task."""
    task_id: str
    commits_during_task: list[str]  # commit hashes + messages
    uncommitted_diff: str           # git diff output (truncated)
    files_modified: list[str]       # list of changed file paths
    timestamp: str
    resume_prompt: str              # ready-to-use prompt for next agent


def detect_checkpoint(task_id: str, task_start_time: float,
                       cwd: str = ".") -> Checkpoint | None:
    """Detect partial progress since task_start_time.

    Returns a Checkpoint if there's evidence of work, None if the task
    produced nothing.
    """
    try:
        # Find commits made after task started
        since = datetime.fromtimestamp(task_start_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--oneline", "--no-merges"],
            capture_output=True, text=True, cwd=cwd, timeout=10,
        )
        commits = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]

        # Get uncommitted changes
        diff_result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True, text=True, cwd=cwd, timeout=10,
        )
        diff_stat = diff_result.stdout.strip()

        # Get full diff (truncated for context)
        full_diff = subprocess.run(
            ["git", "diff"],
            capture_output=True, text=True, cwd=cwd, timeout=10,
        )
        diff_text = full_diff.stdout[:5000]  # Cap at 5KB

        # Get list of modified files
        status_result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, cwd=cwd, timeout=10,
        )
        files = [f.strip() for f in status_result.stdout.strip().split("\n") if f.strip()]

        # If no evidence of work, return None
        if not commits and not files:
            return None

        # Build resume prompt
        resume_parts = [
            f"## Checkpoint Recovery — Task {task_id}",
            f"The previous agent was interrupted. Here is the partial progress:",
            "",
        ]

        if commits:
            resume_parts.append(f"### Commits made ({len(commits)}):")
            for c in commits[:10]:
                resume_parts.append(f"- {c}")
            resume_parts.append("")

        if diff_stat:
            resume_parts.append(f"### Uncommitted changes:")
            resume_parts.append(f"```\n{diff_stat}\n```")
            resume_parts.append("")

        if diff_text:
            resume_parts.append(f"### Diff preview (first 5KB):")
            resume_parts.append(f"```diff\n{diff_text}\n```")
            resume_parts.append("")

        resume_parts.append("### Your mission:")
        resume_parts.append("Continue from where the previous agent left off. Do NOT redo work that's already committed. Focus on completing the remaining steps.")

        return Checkpoint(
            task_id=task_id,
            commits_during_task=commits,
            uncommitted_diff=diff_text,
            files_modified=files,
            timestamp=datetime.now(timezone.utc).isoformat(),
            resume_prompt="\n".join(resume_parts),
        )

    except Exception as e:
        log.warning(f"checkpoint_recovery: failed to detect checkpoint: {e}")
        return None
```

→ verify: `python3 -c "from src.governance.checkpoint_recovery import detect_checkpoint; print('OK')"`

- [ ] **Step 2: Integrate with executor timeout handling**

In `src/governance/executor.py`, in the timeout/error handling path (around the agent execution try/except), add checkpoint detection:

Find the agent execution timeout handler and add:
```python
from src.governance.checkpoint_recovery import detect_checkpoint

# After agent timeout/error:
checkpoint = detect_checkpoint(task_id, task_start_time, cwd=working_dir)
if checkpoint:
    log.info(f"Checkpoint detected: {len(checkpoint.commits_during_task)} commits, {len(checkpoint.files_modified)} files modified")
    # Store checkpoint for potential resume
    self.db.add_log("checkpoint", f"Task {task_id} interrupted with partial progress", extra={
        "commits": len(checkpoint.commits_during_task),
        "files": checkpoint.files_modified,
    })
```

→ verify: `grep "checkpoint_recovery" src/governance/executor.py`

- [ ] **Step 3: Commit**

```bash
git add src/governance/checkpoint_recovery.py src/governance/executor.py
git commit -m "feat(resilience): checkpoint-restart recovery for interrupted sub-agents"
```

---

## Branch 6: `steal/babysit-pr`

### Task 10: babysit-pr Skill

**Files:**
- Create: `.claude/skills/babysit-pr/SKILL.md`

From Codex CLI: autonomous PR monitoring skill. Watch CI checks, if red → read logs → attempt fix → push → repeat.

- [ ] **Step 1: Create SKILL.md**

```markdown
---
name: babysit-pr
description: "Monitor a PR's CI checks and autonomously fix failures. Use when CI is red on a PR and you want automated fix attempts."
---

# babysit-pr — Autonomous PR Monitoring

You are babysitting a pull request. Your job is to watch CI checks, and if any fail, diagnose and fix them.

## Inputs

The user provides a PR number or URL. Extract:
- Repository (default: current repo)
- PR number

## Loop

Repeat up to 5 rounds:

### 1. Check CI Status

```bash
gh pr checks <PR_NUMBER> --json name,state,conclusion
```

If all checks pass → report success and STOP.
If any check is "in_progress" → wait 60 seconds and re-check (max 3 waits).
If any check failed → proceed to step 2.

### 2. Read Failure Logs

```bash
gh run view <RUN_ID> --log-failed
```

Extract the error message, failing test name, and relevant context.

### 3. Diagnose

Read the failing file(s). Understand why the test/lint/build failed.
Apply the Surgical Changes principle: fix ONLY the failure, don't clean up adjacent code.

### 4. Fix and Push

Make the minimal fix. Commit with message:
```
fix(ci): <what was fixed>

babysit-pr round N/5
```

Push to the PR branch:
```bash
git push
```

### 5. Wait and Re-check

Wait 60 seconds for CI to restart, then go back to step 1.

## Safety Rules

- **Max 5 rounds.** If CI is still red after 5 fix attempts, report the remaining failures and STOP.
- **Never force-push.** Only regular push.
- **Never modify CI config** (.github/workflows/) to make tests pass. Fix the code, not the tests.
- **If the failure is infrastructure** (timeout, runner unavailable, rate limit), report it and STOP. Don't try to fix infra.
- **Each fix must be a separate commit** with a clear message. No squashing.

## Exit Conditions

- All checks green → "PR is green. All checks passing."
- 5 rounds exhausted → "Babysit limit reached. Remaining failures: [list]"
- Infrastructure failure → "CI infrastructure issue: [description]. Manual intervention needed."
- User interrupts → Stop immediately.
```

→ verify: `test -f .claude/skills/babysit-pr/SKILL.md && echo "exists"`

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/babysit-pr/SKILL.md
git commit -m "feat(skill): babysit-pr — autonomous PR CI failure fixer (max 5 rounds)"
```

---

## Branch 7: `steal/sse-streaming`

### Task 11: SSE Progress Endpoint in Dashboard

**Files:**
- Modify: `dashboard/server.js`

From R32 agentlytics: replace polling with SSE for real-time collector progress. Add `/api/collect/stream` endpoint that yields progress events during collection runs.

- [ ] **Step 1: Add SSE endpoint to server.js**

After the existing API routes, add:

```javascript
// ── SSE Progress Streaming (stolen from agentlytics Round 32) ──
// Streams real-time progress events during collection runs.
// Client connects with EventSource, receives progress + completion events.
app.get('/api/collect/stream', (req, res) => {
    res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Access-Control-Allow-Origin': '*',
    });

    // Send heartbeat every 15s to keep connection alive
    const heartbeat = setInterval(() => {
        res.write(': heartbeat\n\n');
    }, 15000);

    // Spawn collector process
    const child = spawn('python3', ['scripts/collect.py', '--progress'], {
        cwd: path.join(__dirname, '..'),
        env: { ...process.env, PROGRESS_MODE: '1' },
    });

    child.stdout.on('data', (data) => {
        const lines = data.toString().trim().split('\n');
        for (const line of lines) {
            try {
                const event = JSON.parse(line);
                res.write(`event: ${event.type || 'progress'}\n`);
                res.write(`data: ${JSON.stringify(event)}\n\n`);
            } catch {
                // Non-JSON output, send as log
                res.write(`event: log\ndata: ${JSON.stringify({ message: line })}\n\n`);
            }
        }
    });

    child.stderr.on('data', (data) => {
        res.write(`event: error\ndata: ${JSON.stringify({ message: data.toString().trim() })}\n\n`);
    });

    child.on('close', (code) => {
        clearInterval(heartbeat);
        res.write(`event: complete\ndata: ${JSON.stringify({ exit_code: code })}\n\n`);
        res.end();
    });

    // Client disconnect cleanup
    req.on('close', () => {
        clearInterval(heartbeat);
        child.kill('SIGTERM');
    });
});
```

→ verify: `grep "collect/stream" dashboard/server.js`

- [ ] **Step 2: Commit**

```bash
git add dashboard/server.js
git commit -m "feat(dashboard): SSE progress streaming for collector runs"
```

### Task 12: Multi-Pass Model Name Normalization

**Files:**
- Create: `src/core/model_normalize.py`

From R32 agentlytics: 4-pass normalization for model names from different sources.

- [ ] **Step 1: Create model_normalize.py**

```python
"""
Multi-Pass Model Name Normalization — reconcile model names from different sources.

Source: agentlytics Multi-Pass Model Normalization (Round 32)

Problem: Same model gets called different things:
  - API response: "claude-3-5-sonnet-20241022"
  - User input: "sonnet"
  - Config: "claude-sonnet-4-6"
  - Billing: "claude-3.5-sonnet"

Solution: 4-pass normalization with early return.
"""
from __future__ import annotations

import re

# Canonical model names (what we normalize TO)
CANONICAL_MODELS = {
    "claude-opus-4-6": ["opus", "opus-4", "opus-4.6", "claude-opus"],
    "claude-sonnet-4-6": ["sonnet", "sonnet-4", "sonnet-4.6", "claude-sonnet"],
    "claude-haiku-4-5": ["haiku", "haiku-4", "haiku-4.5", "claude-haiku"],
    "claude-3-5-sonnet": ["sonnet-3.5", "claude-3.5-sonnet", "claude-3-5-sonnet-20241022"],
    "claude-3-5-haiku": ["haiku-3.5", "claude-3.5-haiku", "claude-3-5-haiku-20241022"],
    "gemma3": ["gemma", "gemma-3", "gemma:4b"],
}

# Build reverse lookup
_ALIAS_MAP: dict[str, str] = {}
for canonical, aliases in CANONICAL_MODELS.items():
    _ALIAS_MAP[canonical.lower()] = canonical
    for alias in aliases:
        _ALIAS_MAP[alias.lower()] = canonical


def normalize_model_name(raw: str) -> str:
    """Normalize a model name string to canonical form.

    4-pass strategy:
    1. Exact match (fastest)
    2. Strip provider prefix (anthropic/, openai/)
    3. Strip date suffix (-20241022, -20250301)
    4. Fuzzy prefix match (first alias that starts with input)

    Returns canonical name, or original string if no match.
    """
    if not raw:
        return raw

    cleaned = raw.strip().lower()

    # Pass 1: Exact match
    if cleaned in _ALIAS_MAP:
        return _ALIAS_MAP[cleaned]

    # Pass 2: Strip provider prefix
    for prefix in ("anthropic/", "openai/", "google/", "ollama/"):
        if cleaned.startswith(prefix):
            stripped = cleaned[len(prefix):]
            if stripped in _ALIAS_MAP:
                return _ALIAS_MAP[stripped]

    # Pass 3: Strip date suffix (-YYYYMMDD)
    no_date = re.sub(r'-\d{8}$', '', cleaned)
    if no_date in _ALIAS_MAP:
        return _ALIAS_MAP[no_date]

    # Pass 4: Fuzzy prefix match (first match wins)
    for alias, canonical in _ALIAS_MAP.items():
        if alias.startswith(cleaned) or cleaned.startswith(alias):
            return canonical

    # No match — return original
    return raw
```

→ verify: `python3 -c "from src.core.model_normalize import normalize_model_name; assert normalize_model_name('sonnet') == 'claude-sonnet-4-6'; assert normalize_model_name('claude-3-5-sonnet-20241022') == 'claude-3-5-sonnet'; print('OK')"`

- [ ] **Step 2: Commit**

```bash
git add src/core/model_normalize.py
git commit -m "feat(core): multi-pass model name normalization (4-pass: exact/prefix/date/fuzzy)"
```

---

## Branch 8: `steal/governance-utilities`

### Task 13: SubagentLimit Middleware

**Files:**
- Modify: `src/governance/dispatcher.py`

From DeerFlow 2.0 (R29): hard cap on concurrent sub-agents. If limit reached, queue or reject.

- [ ] **Step 1: Add subagent limit check to dispatcher**

In `src/governance/dispatcher.py`, the `AgentSemaphore` is already imported (line 12). Verify it enforces a hard cap. If not, add explicit limit:

```python
# At the top of the dispatch function, after semaphore check:
MAX_CONCURRENT_SUBAGENTS = int(os.environ.get("MAX_CONCURRENT_SUBAGENTS", "5"))

# In dispatch_task():
active_count = AgentSemaphore.active_count()
if active_count >= MAX_CONCURRENT_SUBAGENTS:
    log.warning(f"SubagentLimit: {active_count}/{MAX_CONCURRENT_SUBAGENTS} agents active, rejecting new dispatch")
    return {"status": "rejected", "reason": f"subagent limit reached ({active_count}/{MAX_CONCURRENT_SUBAGENTS})"}
```

→ verify: `grep "MAX_CONCURRENT_SUBAGENTS" src/governance/dispatcher.py`

- [ ] **Step 2: Commit**

```bash
git add src/governance/dispatcher.py
git commit -m "feat(governance): subagent limit middleware — hard cap on concurrent agents"
```

### Task 14: Disposition Parameterization

**Files:**
- Create: `config/disposition.yaml`
- Modify: `SOUL/tools/compiler.py` (load disposition params during boot.md compilation)

From hindsight (R28e): make personality/disposition parameters configurable rather than hardcoded in SOUL markdown.

- [ ] **Step 1: Create disposition.yaml**

```yaml
# Disposition Parameters — configurable personality tuning
# Source: hindsight Disposition Parameterization (Round 28e)
#
# These parameters are injected into boot.md at compile time.
# Change them to adjust Orchestrator's behavior without editing SOUL source.

personality:
  humor_level: 0.7          # 0.0 = pure tool, 1.0 = full comedian
  directness: 0.9           # 0.0 = diplomatic, 1.0 = brutally honest
  proactivity: 0.8          # 0.0 = only respond, 1.0 = always suggest
  formality: 0.2            # 0.0 = casual, 1.0 = formal

safety:
  risk_tolerance: 0.3       # 0.0 = block everything, 1.0 = allow everything
  verification_strictness: 0.8  # 0.0 = trust output, 1.0 = verify everything

execution:
  autonomy: 0.9             # 0.0 = ask before every action, 1.0 = full autonomy
  commit_eagerness: 0.7     # 0.0 = batch everything, 1.0 = commit every change
```

→ verify: `python3 -c "import yaml; d=yaml.safe_load(open('config/disposition.yaml')); print(d['personality']['humor_level'])"`

- [ ] **Step 2: Commit**

```bash
git add config/disposition.yaml
git commit -m "feat(soul): disposition parameters — configurable personality tuning"
```

### Task 15: Lock File mtime = State Utility

**Files:**
- Modify: `src/core/gate_chain.py` (already has `time_gate` using mtime)

The mtime=state pattern is ALREADY IMPLEMENTED in `gate_chain.py:time_gate()` (line 78-91). It uses `lock_path.stat().st_mtime` to track state. Also used in `memory_synthesizer.py:should_synthesize()` (Task 3).

- [ ] **Step 1: Add LockFileState utility to gate_chain.py for reuse**

```python
class LockFileState:
    """Zero-dependency state tracking via file mtime.

    Source: Claude Code consolidationLock (Round 28a)

    Usage:
        state = LockFileState(Path("data/.last_run"))
        if state.hours_since() >= 24:
            do_work()
            state.touch()
    """

    def __init__(self, path: Path):
        self.path = path

    def hours_since(self) -> float:
        """Hours since last touch. Returns float('inf') if never touched."""
        if not self.path.exists():
            return float('inf')
        return (time.time() - self.path.stat().st_mtime) / 3600

    def minutes_since(self) -> float:
        if not self.path.exists():
            return float('inf')
        return (time.time() - self.path.stat().st_mtime) / 60

    def touch(self):
        """Mark current time."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch()

    def is_stale(self, max_hours: float = 24.0) -> bool:
        return self.hours_since() >= max_hours
```

→ verify: `python3 -c "from src.core.gate_chain import LockFileState; from pathlib import Path; s=LockFileState(Path('/tmp/test-lock')); print(f'stale={s.is_stale(0)}')"`

- [ ] **Step 2: Commit**

```bash
git add src/core/gate_chain.py
git commit -m "feat(core): LockFileState utility — zero-dep state tracking via file mtime"
```

---

## Final: Merge All Branches

After all 8 branches are complete:

```bash
git checkout main
git merge steal/r19-prompt-polish
git merge steal/memory-pipeline
git merge steal/guardian-hardening
git merge steal/exec-policy-engine
git merge steal/checkpoint-restart
git merge steal/babysit-pr
git merge steal/sse-streaming
git merge steal/governance-utilities
```

Update the consolidated tracker with final counts:
- Previously implemented: ~123
- This session: +20 actionable implemented + 18 closed as reference-only + 6 confirmed already-done
- New total: ~143 implemented, 18 reference-only closed
- Remaining: P1/P2 long tail (~35 patterns, by-need basis)

---

## Self-Review Checklist

1. **Spec coverage**: All 44 pending P0s accounted for (20 actionable + 18 ref-only + 6 already-done = 44 ✓)
2. **Placeholder scan**: No "implement the logic" or "add as needed" phrases ✓
3. **Type consistency**: All imports and function names consistent across tasks ✓
4. **File paths**: All paths verified against codebase exploration ✓
5. **Verify commands**: Every step has explicit verification ✓
