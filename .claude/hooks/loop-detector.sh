#!/bin/bash
# Hook: PostToolUse — detect repetitive tool call patterns (infinite loop prevention)
# Source: DeerFlow 2.0 LoopDetectionMiddleware (Round 28 steal)
#
# Strategy: hash each tool call (name + truncated input), track in sliding window.
# 3 identical hashes in window → warn via output (non-blocking).
# 5 identical hashes in window → hard suggest stop.
#
# State file: /tmp/orchestrator-loop-state (one hash per line, max 20 lines)

STATE_FILE="/tmp/orchestrator-loop-state"
WINDOW_SIZE=20
WARN_THRESHOLD=3
STOP_THRESHOLD=5

INPUT=$(cat)

# Extract tool name and input for hashing
TOOL_HASH=$(echo "$INPUT" | python3 -c "
import sys, json, hashlib

try:
    d = json.load(sys.stdin)
    tool_name = d.get('tool_name', '')
    tool_input = d.get('tool_input', {})

    # Normalize: sort keys, truncate values to 200 chars for stable hashing
    if isinstance(tool_input, dict):
        normalized = {k: str(v)[:200] for k, v in sorted(tool_input.items())}
    else:
        normalized = str(tool_input)[:200]

    payload = f'{tool_name}:{json.dumps(normalized, sort_keys=True)}'
    print(hashlib.md5(payload.encode()).hexdigest()[:12])
except:
    print('')
" 2>/dev/null)

# Skip if we couldn't extract a hash
[ -z "$TOOL_HASH" ] && exit 0

# Append to state file, keep only last WINDOW_SIZE entries
echo "$TOOL_HASH" >> "$STATE_FILE"
tail -n "$WINDOW_SIZE" "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"

# Count occurrences of current hash in window
COUNT=$(grep -c "^${TOOL_HASH}$" "$STATE_FILE" 2>/dev/null || echo 0)

if [ "$COUNT" -ge "$STOP_THRESHOLD" ]; then
    echo "⚠ LOOP DETECTED: Same tool call pattern repeated ${COUNT}× in last ${WINDOW_SIZE} calls."
    echo "You are likely stuck in an infinite loop. STOP and try a different approach."
    echo "Pattern hash: ${TOOL_HASH}"
elif [ "$COUNT" -ge "$WARN_THRESHOLD" ]; then
    echo "⚡ Repetition warning: Same tool call pattern ${COUNT}× in last ${WINDOW_SIZE} calls. Consider varying your approach."
fi
