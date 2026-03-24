#!/bin/bash
# Guard hook: block "ollama rm" / "ollama delete" — require user confirmation
# Attached to PreToolUse(Bash) in settings.local.json

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if echo "$COMMAND" | grep -qE '\bollama\s+(rm|delete)\b'; then
    echo '{"decision":"block","reason":"ollama rm/delete requires explicit user confirmation"}'
else
    echo '{"decision":"allow"}'
fi
