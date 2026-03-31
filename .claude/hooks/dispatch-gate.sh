#!/bin/bash
# Hook: PreToolUse(Agent) — governance pipeline + steal-branch enforcement
# 1. Remind to use dispatch.py for non-trivial tasks
# 2. BLOCK [STEAL] tagged work if not on a dedicated branch
#
# Convention: agent prompts that do steal work MUST include the [STEAL] tag.
# No tag = no check. No regex guessing. Explicit declaration only.

INPUT=$(cat)

# Extract agent prompt (use python — jq not always available on Windows)
PROMPT=$(echo "$INPUT" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('tool_input',{}).get('prompt',''))" 2>/dev/null)

# Explicit tag check — only [STEAL] triggers branch enforcement
if echo "$PROMPT" | grep -qF '[STEAL]'; then
    BRANCH=$(git branch --show-current 2>/dev/null || echo "")
    if ! echo "$BRANCH" | grep -qiE '(steal|round)'; then
        echo '{"decision":"block","reason":"[STEAL] tagged work requires a dedicated branch. Run: git checkout -b steal/<topic>"}'
        exit 0
    fi
fi

echo "DISPATCH GATE: You are Orchestrator. For non-trivial tasks, use 'python scripts/dispatch.py \"<task>\" --wait' to dispatch through the real Governor pipeline (Scrutinizer → Dispatcher → Executor). Do NOT manually brief agents with hand-written prompts."
