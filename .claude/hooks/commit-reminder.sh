#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../.." || exit 1
# Hook: Stop — uncommitted-work check
#
# When Claude is about to stop, surface the count of uncommitted
# files. Per CLAUDE.md § Git Safety, auto-commit is NOT allowed
# without explicit owner authorization — this hook informs, it does
# not command. Once the owner has authorized commits in the current
# session, commit-per-feature-point is encouraged.

# Check for uncommitted changes (tracked modified + staged + new code files)
CHANGED=$(git diff --name-only HEAD 2>/dev/null | wc -l | tr -d ' ')
STAGED=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
UNTRACKED=$(git ls-files --others --exclude-standard -- 'src/' 'tests/' 'docs/' '*.py' '*.ts' '*.js' '*.sh' 2>/dev/null | wc -l | tr -d ' ')

TOTAL=$((CHANGED + STAGED + UNTRACKED))

if [ "$TOTAL" -gt 0 ]; then
    echo "[COMMIT-CHECK] ${TOTAL} uncommitted file(s). Per CLAUDE.md Git Safety: stage-first for owner review (show git diff/status). Auto-commit only if the owner has authorized commits in this session."
fi
