#!/bin/bash
# Guard hook: block "ollama rm" / "ollama delete" — require user confirmation
# Attached to PreToolUse(Bash) in settings.local.json

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

if echo "$COMMAND" | grep -qE '\bollama\s+(rm|delete)\b'; then
    echo '{"decision":"block","reason":"ollama rm/delete requires explicit user confirmation"}'
else
    echo '{"decision":"allow"}'
fi
