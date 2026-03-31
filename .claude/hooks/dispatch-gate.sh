#!/bin/bash
# Hook: PreToolUse(Agent) — governance pipeline + steal-branch enforcement
# 1. Remind to use dispatch.py for non-trivial tasks
# 2. BLOCK steal/偷师 work if not on a dedicated branch

INPUT=$(cat)

# Extract agent prompt (use python — jq not always available on Windows)
PROMPT=$(echo "$INPUT" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('tool_input',{}).get('prompt',''))" 2>/dev/null)

# Match imperative steal instructions, not background mentions like "Round 21 偷师" in context
# Triggers: "steal from X", "execute steal plan", "偷师 Round 25", "implement round 23 patterns"
# Does NOT trigger: "背景：Round 21 偷师", "this was stolen from X", "Round 21 的成果"
if echo "$PROMPT" | grep -qiE '(^|\.\s*)(steal\s+(from|round|patterns|P0)|偷师\s*Round|execute.*steal|implement.*steal|implement.*round\s*[0-9]+\s*(steal|pattern))'; then
    BRANCH=$(git branch --show-current 2>/dev/null || echo "")
    # Must be on a dedicated steal branch, not main/master/feat/context-parity or other shared branches
    if ! echo "$BRANCH" | grep -qiE '(steal|round)'; then
        echo '{"decision":"block","reason":"STEAL WORK REQUIRES A DEDICATED BRANCH. Create a branch like steal/round-XX or feat/steal-XX first. Run: git checkout -b steal/<topic>. Do NOT do steal work on shared branches."}'
        exit 0
    fi
fi

echo "DISPATCH GATE: You are Orchestrator. For non-trivial tasks, use 'python scripts/dispatch.py \"<task>\" --wait' to dispatch through the real Governor pipeline (Scrutinizer → Dispatcher → Executor). Do NOT manually brief agents with hand-written prompts."
