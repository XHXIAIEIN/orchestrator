#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../.." || exit 1
# Hook: PreToolUse(Edit,Write) — Three-State Protected File Check
# Source: R66 yoyo-evolve (committed + staged + unstaged triple check)
#
# Enhancement over config-protect.sh:
#   config-protect.sh checks WHAT you're writing (relaxation detection).
#   This hook checks WHETHER protected files have been tampered with
#   across all three git states — committed, staged, and unstaged.
#
# Designed as a PostToolUse/Notification hook that runs AFTER each
# tool use to verify protected files haven't been modified.
# Unlike config-protect.sh (which gates writes), this catches
# modifications that slipped through via Bash, multi-step edits, etc.
#
# Protected paths (from CLAUDE.md Gate Functions):
#   CLAUDE.md, boot.md, docker-compose.yml, .env, hooks/*,
#   .github/workflows/, settings.json

PROTECTED_PATHS=(
    "CLAUDE.md"
    ".claude/boot.md"
    ".claude/settings.json"
    ".claude/hooks/"
    "docker-compose.yml"
    "docker-compose.override.yml"
    ".env"
    ".github/workflows/"
)

# Get the reference point — HEAD (or initial commit if shallow)
REF="HEAD"

VIOLATIONS=""
VIOLATION_COUNT=0

for path in "${PROTECTED_PATHS[@]}"; do
    # State 1: committed changes (compared to HEAD)
    COMMITTED=$(git diff --name-only "$REF" -- "$path" 2>/dev/null)
    if [ -n "$COMMITTED" ]; then
        VIOLATIONS="${VIOLATIONS}[committed] ${COMMITTED}\n"
        ((VIOLATION_COUNT++))
    fi

    # State 2: staged changes (in index, not yet committed)
    STAGED=$(git diff --cached --name-only -- "$path" 2>/dev/null)
    if [ -n "$STAGED" ]; then
        VIOLATIONS="${VIOLATIONS}[staged] ${STAGED}\n"
        ((VIOLATION_COUNT++))
    fi

    # State 3: unstaged changes (working tree, not in index)
    UNSTAGED=$(git diff --name-only -- "$path" 2>/dev/null)
    if [ -n "$UNSTAGED" ]; then
        VIOLATIONS="${VIOLATIONS}[unstaged] ${UNSTAGED}\n"
        ((VIOLATION_COUNT++))
    fi
done

if [ "$VIOLATION_COUNT" -gt 0 ]; then
    echo "⚠️ PROTECTED FILE MODIFICATION DETECTED (${VIOLATION_COUNT} changes across 3 states):"
    echo -e "$VIOLATIONS"
    echo ""
    echo "If these changes are intentional (user-requested), proceed."
    echo "If not, revert with: git checkout -- <file>"
    echo ""
    echo "Three-state check: committed (in commits) + staged (git add) + unstaged (working tree)"
    # Non-blocking warning — the existing config-protect.sh handles blocking
fi
