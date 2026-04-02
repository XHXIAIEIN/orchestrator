#!/bin/bash
# Claude Code Global Security Guard Hook
# Architecture: jq (JSON parse, 1 call) + grep -nf (pattern match, 1 call)
# All rules externalized to guard-rules.conf — no regex in this script.

INPUT=$(cat)
HOOK_DIR="$(dirname "$0")"
RULES_FILE="$HOOK_DIR/guard-rules.conf"

# === Single jq call: extract all fields ===
PARSED=$(echo "$INPUT" | jq -r '[.tool_name // "", .tool_input.file_path // "", .tool_input.command // ""] | @tsv')
TOOL_NAME=$(echo "$PARSED" | cut -f1)
FILE_PATH=$(echo "$PARSED" | cut -f2)
TOOL_INPUT=$(echo "$PARSED" | cut -f3)

# === Write/Edit/MultiEdit: path checks (inline, few patterns) ===
case "$TOOL_NAME" in
    Write|Edit|MultiEdit)
        case "$FILE_PATH" in
            *.env|*credentials*|*id_rsa*|*id_ed25519*|*.pem|*.npmrc|*.pypirc|*kubeconfig*)
                echo "{\"decision\":\"ask\",\"reason\":\"[GUARD] Writing to sensitive path: $FILE_PATH\"}"
                exit 0 ;;
            C:\\Windows*|C:/Windows*|/c/Windows*)
                echo "{\"decision\":\"block\",\"reason\":\"[GUARD] Writing to system directory: $FILE_PATH\"}"
                exit 0 ;;
        esac
        exit 0 ;;
    Bash|PowerShell) ;; # proceed to rule matching
    *) exit 0 ;;        # other tools pass through
esac

# === PowerShell safe fast-pass ===
if [[ "$TOOL_NAME" == "PowerShell" ]]; then
    case "$TOOL_INPUT" in
        *Get-ChildItem*|*Get-Content*|*Write-Output*|*Test-Path*|*Get-ItemProperty*)
            case "$TOOL_INPUT" in
                *Remove-Item*|*rmdir*|*format*|*base64*|*--no-verify*) ;;
                *) exit 0 ;;
            esac ;;
    esac
fi

# === Build pattern list from rules file (skip comments/blanks) ===
ACTIVE_RULES=$(sed '/^#/d;/^$/d' "$RULES_FILE")

# === Exfiltration whitelist check ===
WHITELIST_FILE="$HOOK_DIR/whitelist.conf"
SKIP_EXFIL=false
if [[ -f "$WHITELIST_FILE" ]]; then
    WL_PATTERN=$(sed '/^#/d;/^$/d' "$WHITELIST_FILE" | tr '\n' '|' | sed 's/|$//')
    if [[ -n "$WL_PATTERN" ]] && echo "$TOOL_INPUT" | grep -qiE "$WL_PATTERN"; then
        SKIP_EXFIL=true
    fi
fi

if [[ "$SKIP_EXFIL" == true ]]; then
    # Remove exfil rules, keep the rest
    ACTIVE_RULES=$(echo "$ACTIVE_RULES" | grep -v 'Outbound data upload')
fi

# === Fast path: single grep checks if ANY rule matches ===
ALL_PATTERNS=$(echo "$ACTIVE_RULES" | awk -F'\t' '{print $2}')
if ! echo "$TOOL_INPUT" | grep -qiEf <(echo "$ALL_PATTERNS") 2>/dev/null; then
    exit 0  # No match — fast exit
fi

# === Slow path (rare): find which rule matched — first match wins ===
while IFS=$'\t' read -r decision pattern message; do
    if echo "$TOOL_INPUT" | grep -qiE -e "$pattern" 2>/dev/null; then
        echo "{\"decision\":\"$decision\",\"reason\":\"[GUARD] $message\"}"
        exit 0
    fi
done <<< "$ACTIVE_RULES"

exit 0
