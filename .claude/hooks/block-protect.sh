#!/bin/bash
# block-protect.sh — Physical-level code block protection hook
# Prevents AI from modifying content between protection markers.
#
# Supported markers (must be a comment line, not embedded in prose):
#   # block-protect:start  /  # block-protect:end
#   // simplify-ignore-start  /  // simplify-ignore-end
#   <!-- DO-NOT-MODIFY:start -->  /  <!-- DO-NOT-MODIFY:end -->
#
# Modes:
#   scan    — SessionStart: find and report protected files
#   check   — PreToolUse(Edit|Write|MultiEdit): block edits touching protected regions
#   cleanup — Stop: remove temp state files
#
# Architecture: stateless check (no persistent state needed).
# Each Edit/Write is checked against the file's current markers in real-time.

MODE="${1:-check}"
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$HOOK_DIR/state"
PROJECT_DIR="$(cd "$HOOK_DIR/../.." && pwd)"

# Marker keywords
KEYWORDS_S='(block-protect:start|simplify-ignore-start|DO-NOT-MODIFY:start)'
KEYWORDS_E='(block-protect:end|simplify-ignore-end|DO-NOT-MODIFY:end)'
# Comment prefixes that signal a real marker (not prose)
COMMENT_PREFIX='^[[:space:]]*(#|//|--|/[*]|<!--|%)[[:space:]]*'
# Full line-anchored patterns
MARKER_START="${COMMENT_PREFIX}${KEYWORDS_S}"
MARKER_END="${COMMENT_PREFIX}${KEYWORDS_E}"

# ── scan: SessionStart — report protected files ──
if [ "$MODE" = "scan" ]; then
    cd "$PROJECT_DIR" || exit 0
    PROTECTED_FILES=$(git ls-files -z 2>/dev/null | xargs -0 grep -rlE "$MARKER_START" 2>/dev/null)

    if [ -n "$PROTECTED_FILES" ]; then
        COUNT=$(echo "$PROTECTED_FILES" | wc -l)
        mkdir -p "$STATE_DIR"
        echo "$PROTECTED_FILES" > "$STATE_DIR/block-protect-files.txt"

        DETAILS=""
        while IFS= read -r f; do
            BLOCKS=$(grep -cE "$MARKER_START" "$f" 2>/dev/null)
            DETAILS="${DETAILS}  ${f} (${BLOCKS} block(s))\n"
        done <<< "$PROTECTED_FILES"

        echo "[block-protect] $COUNT file(s) with protected blocks:"
        echo -e "$DETAILS"
    fi
    exit 0
fi

# ── cleanup: Stop — remove temp files ──
if [ "$MODE" = "cleanup" ]; then
    rm -f "$STATE_DIR/block-protect-files.txt" 2>/dev/null
    exit 0
fi

# ── check: PreToolUse(Edit|Write|MultiEdit) — block edits to protected regions ──
INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')

[ -z "$FILE_PATH" ] && echo '{"decision":"allow"}' && exit 0

# Normalize Windows backslashes to forward slashes
FILE_PATH=$(echo "$FILE_PATH" | tr '\' '/')

# File doesn't exist → allow (new file creation)
[ ! -f "$FILE_PATH" ] && echo '{"decision":"allow"}' && exit 0

# Fast check: does file have any real protection markers?
if ! grep -qE "$MARKER_START" "$FILE_PATH" 2>/dev/null; then
    echo '{"decision":"allow"}'
    exit 0
fi

# ── File has protected blocks — analyze the edit ──

case "$TOOL_NAME" in
    Write)
        echo '{"decision":"block","reason":"[BLOCK-PROTECT] File contains protected blocks. Use Edit to modify only unprotected regions, or remove the markers first if intentional."}'
        exit 0
        ;;

    Edit|MultiEdit)
        OLD_STRING=$(echo "$INPUT" | jq -r '.tool_input.old_string // ""')
        [ -z "$OLD_STRING" ] && echo '{"decision":"allow"}' && exit 0

        # Defense 1: old_string contains a real marker line → block
        if echo "$OLD_STRING" | grep -qE "$MARKER_START|$MARKER_END"; then
            echo '{"decision":"block","reason":"[BLOCK-PROTECT] Cannot modify or remove protection markers."}'
            exit 0
        fi

        # Defense 2: old_string targets content within a protected region
        ANCHOR=$(echo "$OLD_STRING" | grep -v '^[[:space:]]*$' | head -1)
        [ -z "$ANCHOR" ] && echo '{"decision":"allow"}' && exit 0

        MATCH_LINES=$(grep -nF -- "$ANCHOR" "$FILE_PATH" 2>/dev/null | cut -d: -f1)
        [ -z "$MATCH_LINES" ] && echo '{"decision":"allow"}' && exit 0

        OLD_LINE_COUNT=$(echo "$OLD_STRING" | wc -l)

        # Build protected ranges (awk needs escaped regex)
        PROTECTED_RANGES=$(awk '
            /^[[:space:]]*(#|\/\/|--|\/[*]|<!--|%)[[:space:]]*(block-protect:start|simplify-ignore-start|DO-NOT-MODIFY:start)/ { start=NR }
            /^[[:space:]]*(#|\/\/|--|\/[*]|<!--|%)[[:space:]]*(block-protect:end|simplify-ignore-end|DO-NOT-MODIFY:end)/   { if(start) { print start"-"NR; start=0 } }
        ' "$FILE_PATH" 2>/dev/null)

        [ -z "$PROTECTED_RANGES" ] && echo '{"decision":"allow"}' && exit 0

        # Check each match location against protected ranges
        for match_line in $MATCH_LINES; do
            match_end=$((match_line + OLD_LINE_COUNT - 1))
            for range in $PROTECTED_RANGES; do
                range_start=$(echo "$range" | cut -d'-' -f1)
                range_end=$(echo "$range" | cut -d'-' -f2)
                if [ "$match_line" -le "$range_end" ] && [ "$match_end" -ge "$range_start" ]; then
                    echo "{\"decision\":\"block\",\"reason\":\"[BLOCK-PROTECT] Edit overlaps with protected region (lines ${range_start}-${range_end}). Content between markers cannot be modified.\"}"
                    exit 0
                fi
            done
        done

        # Secondary anchor: last line of old_string
        LAST_ANCHOR=$(echo "$OLD_STRING" | grep -v '^[[:space:]]*$' | tail -1)
        if [ -n "$LAST_ANCHOR" ] && [ "$LAST_ANCHOR" != "$ANCHOR" ]; then
            LAST_MATCH_LINES=$(grep -nF -- "$LAST_ANCHOR" "$FILE_PATH" 2>/dev/null | cut -d: -f1)
            for last_line in $LAST_MATCH_LINES; do
                for range in $PROTECTED_RANGES; do
                    range_start=$(echo "$range" | cut -d'-' -f1)
                    range_end=$(echo "$range" | cut -d'-' -f2)
                    if [ "$last_line" -ge "$range_start" ] && [ "$last_line" -le "$range_end" ]; then
                        echo "{\"decision\":\"block\",\"reason\":\"[BLOCK-PROTECT] Edit extends into protected region (lines ${range_start}-${range_end}). Content between markers cannot be modified.\"}"
                        exit 0
                    fi
                done
            done
        fi

        echo '{"decision":"allow"}'
        exit 0
        ;;

    *)
        echo '{"decision":"allow"}'
        exit 0
        ;;
esac
