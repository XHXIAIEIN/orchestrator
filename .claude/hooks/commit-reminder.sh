#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../.." || exit 1
# Hook: Stop — auto-commit enforcement
#
# When Claude is about to stop, check for uncommitted changes.
# If found, output a DIRECTIVE to commit them NOW — not a suggestion,
# not a reminder. Claude must commit before ending the turn.
#
# This enforces "one feature point = one commit" mechanically.

# Check for uncommitted changes (tracked modified + staged + new code files)
CHANGED=$(git diff --name-only HEAD 2>/dev/null | wc -l | tr -d ' ')
STAGED=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
UNTRACKED=$(git ls-files --others --exclude-standard -- 'src/' 'tests/' 'docs/' '*.py' '*.ts' '*.js' '*.sh' 2>/dev/null | wc -l | tr -d ' ')

TOTAL=$((CHANGED + STAGED + UNTRACKED))

if [ "$TOTAL" -gt 0 ]; then
    echo "[COMMIT-NOW] You have ${TOTAL} uncommitted file(s). Do NOT end your turn without committing. Run git add + git commit now. Do not ask the user — judge the feature-point boundary yourself and commit."
fi
