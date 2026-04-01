#!/bin/bash
# Guard hook: block "ollama rm" / "ollama delete" — require user confirmation
# Attached to PreToolUse(Bash) in settings.local.json
# Performance: jq (~5ms) instead of python3 (~60ms) — Round 35 steal

INPUT=$(head -c 65536)

# Guard clause: use jq if available
if command -v jq &>/dev/null; then
    COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
else
    COMMAND=$(echo "$INPUT" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)
fi

[ -z "$COMMAND" ] && echo '{"decision":"allow"}' && exit 0

if echo "$COMMAND" | grep -qE '\bollama\s+(rm|delete)\b'; then
    echo '{"decision":"block","reason":"ollama rm/delete requires explicit user confirmation"}'
else
    echo '{"decision":"allow"}'
fi
