#!/bin/bash
# Block Protection Hook — prevents edits to code between protect-start/protect-end markers
# Triggered on: PreToolUse for Edit|Write
#
# Markers (language-agnostic, detected by substring):
#   protect-start / protect-end
#   PROTECT-START / PROTECT-END
#
# Examples in code:
#   # protect-start
#   critical_function_here()
#   # protect-end
#
#   <!-- protect-start -->
#   <div>immutable markup</div>
#   <!-- protect-end -->

INPUT=$(cat)

# Extract tool info
PARSED=$(echo "$INPUT" | jq -r '[.tool_name // "", .tool_input.file_path // "", .tool_input.old_string // "", .tool_input.content // ""] | @tsv')
TOOL_NAME=$(echo "$PARSED" | cut -f1)
FILE_PATH=$(echo "$PARSED" | cut -f2)

# Only check Edit and Write
case "$TOOL_NAME" in
    Edit|MultiEdit) ;;
    Write)
        # For Write (full overwrite), check if file has protected blocks
        if [ -f "$FILE_PATH" ] && grep -qi 'protect-start' "$FILE_PATH" 2>/dev/null; then
            echo "{\"decision\":\"block\",\"reason\":\"[BLOCK-PROTECT] $FILE_PATH contains protected blocks (protect-start/protect-end). Use Edit to modify only unprotected sections, or get owner approval to remove protection markers first.\"}"
            exit 0
        fi
        exit 0 ;;
    *) exit 0 ;;
esac

# For Edit: check if old_string overlaps with a protected block
# Strategy: extract protected blocks from file, check if old_string contains any protected content

# File must exist
[ ! -f "$FILE_PATH" ] && exit 0

# File must have protection markers
grep -qi 'protect-start' "$FILE_PATH" 2>/dev/null || exit 0

# Extract old_string from input (may contain special chars, use jq)
OLD_STRING=$(echo "$INPUT" | jq -r '.tool_input.old_string // ""')
[ -z "$OLD_STRING" ] && exit 0

# Extract protected blocks and check overlap
# Use awk to extract content between markers, then check if old_string contains any of it
PROTECTED_LINES=$(awk '
    tolower($0) ~ /protect-start/ { inside=1; next }
    tolower($0) ~ /protect-end/ { inside=0; next }
    inside { print }
' "$FILE_PATH")

[ -z "$PROTECTED_LINES" ] && exit 0

# Check if old_string contains any protected line (non-empty, non-whitespace)
while IFS= read -r line; do
    # Skip empty/whitespace-only lines
    trimmed=$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    [ -z "$trimmed" ] && continue
    # Check if old_string contains this protected line
    if echo "$OLD_STRING" | grep -qF "$trimmed"; then
        echo "{\"decision\":\"block\",\"reason\":\"[BLOCK-PROTECT] Edit touches protected code in $FILE_PATH. The line '$trimmed' is inside a protect-start/protect-end block. Get owner approval before modifying protected code.\"}"
        exit 0
    fi
done <<< "$PROTECTED_LINES"

exit 0
