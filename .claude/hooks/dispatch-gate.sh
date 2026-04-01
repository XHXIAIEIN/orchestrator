#!/bin/bash
# Hook: PreToolUse(Agent) — governance pipeline + steal-branch enforcement
# 1. Remind to use dispatch.py for non-trivial tasks
# 2. BLOCK [STEAL] tagged work if not on a dedicated branch
#
# Convention: agent prompts that do steal work MUST include the [STEAL] tag.
# No tag = no check. No regex guessing. Explicit declaration only.

INPUT=$(head -c 65536)

# Extract agent prompt (jq preferred, python3 fallback)
if command -v jq &>/dev/null; then
    PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty' 2>/dev/null)
else
    PROMPT=$(echo "$INPUT" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('tool_input',{}).get('prompt',''))" 2>/dev/null)
fi

# Explicit tag check — only [STEAL] triggers branch enforcement
if echo "$PROMPT" | grep -qF '[STEAL]'; then
    BRANCH=$(git branch --show-current 2>/dev/null || echo "")
    if ! echo "$BRANCH" | grep -qiE '(steal|round)'; then
        echo '{"decision":"block","reason":"[STEAL] tagged work requires a dedicated branch. Run: git checkout -b steal/<topic>"}'
        exit 0
    fi
fi

# ── Session Boundary Check ──
# Explicit [NEW-SESSION] tag = block and demand handoff
if echo "$PROMPT" | grep -qF '[NEW-SESSION]'; then
    echo '{"decision":"block","reason":"This task is tagged [NEW-SESSION] — it needs a fresh session. Write a handoff (per session_handoff.md) and give the user a startup prompt for the next session."}'
    exit 0
fi

# Auto-detect: [STEAL] without branch is already handled above.
# For non-tagged tasks, check context pressure via tool call counter.
TOOL_COUNT=$(cat /tmp/orchestrator-persona-counter 2>/dev/null || echo 0)
if [ "$TOOL_COUNT" -gt 50 ]; then
    echo "SESSION PRESSURE: $TOOL_COUNT tool calls in this session. Before starting a new major task, evaluate if it should be a fresh session (read SOUL/public/prompts/session_boundary.md). Trivial tasks are fine to continue."
fi

# ── Protected File Guardian (stolen from yoyo-evolve Round 30) ──
PROTECTED_REMINDER="PROTECTED FILES (do NOT modify): SOUL/private/identity.md, SOUL/private/hall-of-instances.md, .claude/hooks/guard-redflags.sh, .claude/hooks/config-protect.sh, .claude/boot.md, CLAUDE.md, .claude/settings.json. If your task requires changing these, STOP and report back."

# ── Sub-Agent Behavioral Norms (stolen from PUA injection protocol, Round 35) ──
# Sub-agents have blank context — they inherit NOTHING from the parent.
# Without explicit injection, sub-agents run "naked": no red lines, no methodology, no verification discipline.
BEHAVIORAL_NORMS="BEHAVIORAL NORMS (injected by dispatch-gate): (1) Every completion claim must reference actual command output — 'should work' is banned. (2) If you fail 3+ times consecutively, STOP and diagnose: list what you tried, what failed, and what assumption might be wrong. (3) Do not give up before trying 3 fundamentally different approaches. (4) End with DONE: <one sentence> or STUCK: <what you tried and where you're blocked>."

echo "DISPATCH GATE: You are Orchestrator. For non-trivial tasks, use 'python scripts/dispatch.py \"<task>\" --wait' to dispatch through the real Governor pipeline (Scrutinizer → Dispatcher → Executor). Do NOT manually brief agents with hand-written prompts. ${PROTECTED_REMINDER} ${BEHAVIORAL_NORMS}"
