#!/bin/bash
# Hook: Stop — Auto-save memory every N exchanges
# Stolen from MemPalace (R44 P0#3): hook-driven auto-save with anti-recursion
#
# Mechanism:
#   1. Count human↔AI exchanges via state file
#   2. When threshold reached → block Claude + inject save instruction
#   3. Claude executes /remember skill → triggers Stop again
#   4. Second Stop sees stop_hook_active=true → passes through (no infinite loop)
#
# State: .claude/hooks/state/memory_save_<session>

INPUT=$(cat)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$SCRIPT_DIR/state"
mkdir -p "$STATE_DIR"

# ── Anti-recursion gate ──
# When Claude finishes executing the save instruction, Stop fires again.
# stop_hook_active=true means "this Stop was triggered by a previous block" → pass through.
STOP_HOOK_ACTIVE=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    v = d.get('stop_hook_active', False)
    print(str(v).lower())
except:
    print('false')
" 2>/dev/null)

if [ "$STOP_HOOK_ACTIVE" = "true" ] || [ "$STOP_HOOK_ACTIVE" = "True" ]; then
    echo "{}"
    exit 0
fi

# ── Exchange counter ──
# Use session-stable state file. Fallback to PID-based session ID.
SESSION_ID=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    # Try session_id, fall back to a hash of transcript_path or 'default'
    sid = d.get('session_id', '') or 'default'
    print(sid[:32])
except:
    print('default')
" 2>/dev/null)

COUNTER_FILE="$STATE_DIR/memory_save_${SESSION_ID}"
SAVE_INTERVAL=15  # exchanges between auto-saves

# Read current count (0 if file doesn't exist)
if [ -f "$COUNTER_FILE" ]; then
    LAST_SAVE=$(cat "$COUNTER_FILE" 2>/dev/null || echo "0")
else
    LAST_SAVE=0
fi

# Increment exchange count
CURRENT=$((LAST_SAVE + 1))
echo "$CURRENT" > "$COUNTER_FILE"

# ── Threshold check ──
if [ "$CURRENT" -ge "$SAVE_INTERVAL" ]; then
    # Reset counter
    echo "0" > "$COUNTER_FILE"

    # Block Claude and inject memory save instruction
    # The reason becomes a system message that Claude will follow
    cat << 'HOOKJSON'
{
  "decision": "block",
  "reason": "AUTO-SAVE CHECKPOINT (memory-save-hook)\n\nYou have had 15+ exchanges since your last memory save. Before continuing, save any important information from this conversation:\n\n1. Review the conversation so far for key topics: decisions made, bugs found, architecture changes, user preferences expressed, project status updates\n2. For each topic worth remembering, write a memory file to the auto-memory directory (C:\\Users\\test\\.claude\\projects\\D--Users-Administrator-Documents-GitHub-orchestrator\\memory\\)\n3. Update MEMORY.md index if new files were created\n4. Keep saves focused — only save what would be useful in FUTURE conversations, not ephemeral task details\n5. After saving, continue with whatever you were doing before this checkpoint\n\nThis is a periodic auto-save, not a conversation interruption. Be quick about it."
}
HOOKJSON
    exit 0
fi

# Not yet at threshold — pass through silently
exit 0
