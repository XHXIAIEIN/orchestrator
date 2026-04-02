#!/bin/bash
# Guard hook: block "ollama rm" / "ollama delete" — require user confirmation
# Attached to PreToolUse(Bash) in settings.local.json
# Performance: jq (~5ms) instead of python3 (~60ms) — Round 35 steal

INPUT=$(head -c 65536)

# Extract command
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

[ -z "$COMMAND" ] && echo '{"decision":"allow"}' && exit 0

if echo "$COMMAND" | grep -qE '\bollama\s+(rm|delete)\b'; then
    echo '{"decision":"block","reason":"ollama rm/delete requires explicit user confirmation"}'
else
    echo '{"decision":"allow"}'
fi
