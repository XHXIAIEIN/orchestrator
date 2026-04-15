#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../.." || exit 1
# Guard hook: block "ollama rm" / "ollama delete" — require user confirmation
# Attached to PreToolUse(Bash) in settings.local.json
# Performance: jq (~5ms) instead of python3 (~60ms) — Round 35 steal

INPUT=$(cat)

# ── Guard clause: non-Bash tools are irrelevant ──
# R35c: guard clause — zero-cost exit for non-Bash tools
tool_name=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
if [ "$tool_name" != "Bash" ]; then
    echo '{"decision":"allow"}'
    exit 0
fi

# Extract command
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

[ -z "$COMMAND" ] && echo '{"decision":"allow"}' && exit 0

if echo "$COMMAND" | grep -qE '\bollama\s+(rm|delete)\b'; then
    echo '{"decision":"block","reason":"ollama rm/delete requires explicit user confirmation"}'
else
    echo '{"decision":"allow"}'
fi
