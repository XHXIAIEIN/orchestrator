#!/bin/bash
# PostToolUse hook: P0-3 Out-of-Band Subagent Intervention Channel
# Checks temp/${TASK_ID}/ for control files written by parent agent.
# Priority: _stop.txt (exit) > _keyinfo.txt (accumulate) > _intervene.txt (redirect)

# Read stdin (required by hook protocol, not used for logic)
INPUT=$(cat)

# If TASK_ID is not set, nothing to check
if [ -z "$TASK_ID" ]; then
    exit 0
fi

CHANNEL_DIR="temp/${TASK_ID}"
STATE_DIR=".claude/hooks/state"

# Ensure state dir exists
mkdir -p "$STATE_DIR"

# --- _stop.txt: hard stop ---
STOP_FILE="${CHANNEL_DIR}/_stop.txt"
if [ -f "$STOP_FILE" ]; then
    CONTENT=$(cat "$STOP_FILE")
    rm -f "$STOP_FILE"
    printf '{"decision":"block","reason":"[parent-stop] %s"}\n' "$CONTENT"
    exit 1
fi

# --- _keyinfo.txt: inject key info (non-blocking) ---
KEYINFO_FILE="${CHANNEL_DIR}/_keyinfo.txt"
if [ -f "$KEYINFO_FILE" ]; then
    CONTENT=$(cat "$KEYINFO_FILE")
    rm -f "$KEYINFO_FILE"
    echo "$CONTENT" >> "${STATE_DIR}/keyinfo-${TASK_ID}.txt"
    # Non-blocking: continue to check _intervene.txt
fi

# --- _intervene.txt: parent redirect ---
INTERVENE_FILE="${CHANNEL_DIR}/_intervene.txt"
if [ -f "$INTERVENE_FILE" ]; then
    CONTENT=$(cat "$INTERVENE_FILE")
    rm -f "$INTERVENE_FILE"
    printf '{"decision":"block","reason":"[PARENT INTERVENTION] %s"}\n' "$CONTENT"
    exit 1
fi

exit 0
