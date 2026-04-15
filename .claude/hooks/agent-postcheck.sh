#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../.." || exit 1
# Hook: PostToolUse(Agent) — check if agent modified protected files
# Source: yoyo-evolve Protected File Guardian (Round 30)

# Drain stdin
head -c 65536 > /dev/null

PROTECTED_FILES=(
    "SOUL/private/identity.md"
    "SOUL/private/hall-of-instances.md"
    ".claude/hooks/guard-redflags.sh"
    ".claude/hooks/config-protect.sh"
    ".claude/boot.md"
    "CLAUDE.md"
    ".claude/settings.json"
)

# Check git diff for protected file modifications
DIFF_FILES=$(git diff --name-only 2>/dev/null)
[ -z "$DIFF_FILES" ] && exit 0

VIOLATIONS=""
for pf in "${PROTECTED_FILES[@]}"; do
    if echo "$DIFF_FILES" | grep -qF "$pf"; then
        VIOLATIONS="${VIOLATIONS}  - ${pf}\n"
    fi
done

if [ -n "$VIOLATIONS" ]; then
    echo "⚠ PROTECTED FILE GUARDIAN: Sub-agent modified protected files!"
    echo -e "Affected files:\n${VIOLATIONS}"
    echo "Review these changes carefully. Consider reverting with: git checkout -- <file>"
fi
