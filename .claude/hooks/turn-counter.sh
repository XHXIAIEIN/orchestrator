#!/bin/bash
# PostToolUse hook: increment per-session turn counter
# Reads SESSION_ID from env; falls back to $$ (PID) if unset.
# Increments integer in .claude/hooks/state/turn-${SESSION_ID}.txt
# Creates the file with value 1 if it doesn't exist yet.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$SCRIPT_DIR/state"
mkdir -p "$STATE_DIR"

# Derive session identifier
SID="${SESSION_ID:-$$}"
STATE_FILE="$STATE_DIR/turn-${SID}.txt"

if [ -f "$STATE_FILE" ]; then
    CURRENT=$(cat "$STATE_FILE" 2>/dev/null | tr -d '[:space:]')
    # Guard against non-numeric content
    if ! [[ "$CURRENT" =~ ^[0-9]+$ ]]; then
        CURRENT=0
    fi
    NEW=$(( CURRENT + 1 ))
else
    NEW=1
fi

echo "$NEW" > "$STATE_FILE"
exit 0
