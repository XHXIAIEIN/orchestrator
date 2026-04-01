#!/bin/bash
# Hook: PreToolUse(Edit,Write) — block modifications to linter/formatter/build configs
# Source: Everything Claude Code steal — Config Protection Hook
#
# Philosophy: When linting or type-checking fails, fix the CODE, not the rules.
# This hook intercepts attempts to relax linter/formatter/build configs.
#
# Protected patterns:
#   .eslintrc*, .prettierrc*, tsconfig*.json, pyproject.toml (tool sections),
#   .flake8, .pylintrc, setup.cfg (tool sections), ruff.toml,
#   .editorconfig, biome.json, tslint.json
#
# Allowed: adding NEW rules (stricter), genuine config changes the user asked for.
# Blocked: disabling rules, widening ignore patterns, loosening strictness.

INPUT=$(head -c 65536)

# Extract file path from tool input (jq preferred, python3 fallback)
if command -v jq &>/dev/null; then
    FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
else
    FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    ti = d.get('tool_input', {})
    print(ti.get('file_path', ''))
except:
    print('')
" 2>/dev/null)
fi

[ -z "$FILE_PATH" ] && echo '{"decision":"allow"}' && exit 0

# Check if the file matches protected config patterns
BASENAME=$(basename "$FILE_PATH")
IS_CONFIG=false

case "$BASENAME" in
    .eslintrc*|.prettierrc*|tsconfig*.json|tslint.json|biome.json)
        IS_CONFIG=true ;;
    .flake8|.pylintrc|ruff.toml|.ruff.toml)
        IS_CONFIG=true ;;
    .editorconfig)
        IS_CONFIG=true ;;
    .env|.env.*|.envrc)
        IS_CONFIG=true ;;
    settings.json|settings.local.json)
        if echo "$FILE_PATH" | grep -qE '\.claude/'; then
            IS_CONFIG=true
        fi
        ;;
    pyproject.toml|setup.cfg)
        # Only protect if editing tool-config sections — check content
        EDIT_CONTENT=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    ti = d.get('tool_input', {})
    old = ti.get('old_string', '')
    new = ti.get('new_string', ti.get('content', ''))
    print(old + '\n' + new)
except:
    print('')
" 2>/dev/null)
        if echo "$EDIT_CONTENT" | grep -qiE '\[(tool\.|ruff|flake8|pylint|mypy|black|isort|pytest)'; then
            IS_CONFIG=true
        fi
        ;;
esac

if [ "$IS_CONFIG" = false ]; then
    echo '{"decision":"allow"}'
    exit 0
fi

# Detect if the change is RELAXING rules (disabling, ignoring, widening)
CHANGE_CONTENT=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    ti = d.get('tool_input', {})
    # For Edit: look at new_string; for Write: look at content
    new = ti.get('new_string', ti.get('content', ''))
    print(new)
except:
    print('')
" 2>/dev/null)

# Relaxation indicators
IS_RELAXING=false
if echo "$CHANGE_CONTENT" | grep -qiE '("off"|: *0|disable|no-|ignore|skip|suppress|allow|relaxed|nocheck|@ts-ignore|@ts-nocheck|# noqa|# type: ignore|# pylint: disable|eslint-disable|prettier-ignore)'; then
    IS_RELAXING=true
fi

if echo "$CHANGE_CONTENT" | grep -qiE '(strict.*false|strictNullChecks.*false|noImplicit.*false|skipLibCheck.*true)'; then
    IS_RELAXING=true
fi

if [ "$IS_RELAXING" = true ]; then
    echo "{\"decision\":\"block\",\"reason\":\"Config relaxation detected on ${BASENAME}. Fix the code, not the rules. If this is intentional (user-requested config change), ask the user to confirm.\"}"
else
    # Allowing stricter configs or neutral changes
    echo '{"decision":"allow"}'
fi
