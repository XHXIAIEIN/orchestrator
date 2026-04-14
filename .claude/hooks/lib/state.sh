#!/usr/bin/env bash
# Cross-hook IPC via flag files (R50 — from Caveman steal)
#
# Usage:  source "$(dirname "$0")/lib/state.sh"
#
# Conventions:
#   - Keys: lowercase-kebab-case, prefixed with hook name
#     e.g., "pre-compact.pending", "session.start-time", "dispatch.tool-count"
#   - Values: single-line strings. Use JSON for complex data.
#   - State files live in STATE_DIR (default: /tmp/orchestrator-state/)
#   - Ephemeral by design — cleared on session start
#
# Why /tmp/ not .claude/hooks/state/?
#   .claude/hooks/state/ is already used for memory_save files (persistent).
#   IPC flags are ephemeral and should not pollute the git-tracked directory.

STATE_DIR="${ORCHESTRATOR_STATE_DIR:-/tmp/orchestrator-state}"
mkdir -p "$STATE_DIR" 2>/dev/null

# Write a key-value pair (atomic: write to tmp then mv)
state_set() {
    local key="$1" val="$2"
    local tmp="$STATE_DIR/.$key.tmp"
    echo "$val" > "$tmp" && mv "$tmp" "$STATE_DIR/$key"
}

# Read a key (empty string if not set)
state_get() {
    local key="$1"
    cat "$STATE_DIR/$key" 2>/dev/null || echo ""
}

# Check if key exists
state_has() {
    local key="$1"
    [ -f "$STATE_DIR/$key" ]
}

# Delete a key
state_del() {
    local key="$1"
    rm -f "$STATE_DIR/$key"
}

# Increment a numeric key (returns new value)
state_incr() {
    local key="$1"
    local cur; cur=$(state_get "$key")
    cur=${cur:-0}
    local new=$((cur + 1))
    state_set "$key" "$new"
    echo "$new"
}

# Clear all state (called by session-start)
state_clear_all() {
    rm -f "$STATE_DIR"/* 2>/dev/null
}

# List all keys
state_keys() {
    ls "$STATE_DIR/" 2>/dev/null | grep -v '\.tmp$'
}
