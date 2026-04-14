#!/usr/bin/env bash
# Hook: PreToolUse — security pattern scanner (R55 SlowMist steal)
# Scans tool input content against the attack pattern library.
# HIGH/REJECT matches → exit 2 (block + feedback to Claude)

INPUT=$(cat)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Extract tool name and relevant content to scan
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // "unknown"' 2>/dev/null)

# Build scan text from tool input fields
SCAN_TEXT=$(echo "$INPUT" | jq -r '
  .tool_input |
  [.command, .prompt, .content, .file_path, .pattern, .url] |
  map(select(. != null and . != "")) |
  join("\n")
' 2>/dev/null)

# Skip if nothing to scan
[ -z "$SCAN_TEXT" ] && exit 0

# Run the Python scanner
RESULT=$(echo "$SCAN_TEXT" | python3 "$REPO_ROOT/src/security/_hook_scan.py" "$TOOL_NAME" 2>/dev/null)

# No matches → allow
[ -z "$RESULT" ] && exit 0

# Parse risk level from first line
RISK=$(echo "$RESULT" | head -1)
DETAILS=$(echo "$RESULT" | tail -n +2)

if [ "$RISK" = "REJECT" ]; then
    echo "SECURITY BLOCK: Attack pattern detected in $TOOL_NAME tool input." >&2
    echo "$DETAILS" >&2
    exit 2
elif [ "$RISK" = "HIGH" ]; then
    echo "SECURITY WARNING: Suspicious pattern in $TOOL_NAME tool input." >&2
    echo "$DETAILS" >&2
    echo "Review carefully before proceeding." >&2
    exit 2
fi
