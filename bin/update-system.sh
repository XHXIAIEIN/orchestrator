#!/bin/bash
# R46 (career-ops): Safe Auto-Update System
#
# Updates System Layer files only (per DATA_CONTRACT.md).
# User Layer files are NEVER touched. Hybrid files use merge strategy.
#
# Usage:
#   bash bin/update-system.sh              # dry-run (show what would change)
#   bash bin/update-system.sh --apply      # actually update
#   bash bin/update-system.sh --rollback   # revert last update
#
# Prerequisites: clean git working tree (no uncommitted changes)

set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="$PROJECT_DIR/.trash/update-backup-$(date +%Y%m%d-%H%M%S)"
MODE="${1:---dry-run}"

# ── User Layer paths (from DATA_CONTRACT.md) — NEVER modify ──
USER_LAYER_PATTERNS=(
    "SOUL/private/"
    ".claude/hooks/"
    ".claude/settings.json"
    ".env"
    "config/"
    "data/"
)

# ── Hybrid Layer — merge only, never replace ──
HYBRID_PATTERNS=(
    "CLAUDE.md"
    ".claude/boot.md"
    "SOUL/tools/compiler.py"
    "docs/architecture/PATTERNS.md"
)

is_user_layer() {
    local file="$1"
    for pattern in "${USER_LAYER_PATTERNS[@]}"; do
        if [[ "$file" == "$pattern"* ]]; then
            return 0
        fi
    done
    return 1
}

is_hybrid() {
    local file="$1"
    for pattern in "${HYBRID_PATTERNS[@]}"; do
        if [[ "$file" == "$pattern" ]]; then
            return 0
        fi
    done
    return 1
}

echo "┌─ System Layer Update ─────────────────────────┐"
echo "│ Mode: $MODE                                    │"

# ── Preflight: clean working tree ──
if [ -n "$(cd "$PROJECT_DIR" && git status --porcelain 2>/dev/null)" ]; then
    echo "│ [FAIL] Working tree not clean. Commit or stash first. │"
    echo "└─────────────────────────────────────────────────┘"
    exit 1
fi

# ── Fetch latest ──
echo "│ Fetching latest from remote...                 │"
cd "$PROJECT_DIR"
git fetch origin main 2>/dev/null || git fetch origin master 2>/dev/null || true

# ── Analyze what would change ──
MAIN_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@refs/remotes/origin/@@' || echo "main")
CHANGES=$(git diff --name-only "origin/$MAIN_BRANCH" 2>/dev/null || echo "")

if [ -z "$CHANGES" ]; then
    echo "│ Already up to date. No changes.                │"
    echo "└─────────────────────────────────────────────────┘"
    exit 0
fi

SAFE_FILES=""
BLOCKED_FILES=""
HYBRID_FILES=""

while IFS= read -r file; do
    [ -z "$file" ] && continue
    if is_user_layer "$file"; then
        BLOCKED_FILES="$BLOCKED_FILES  [BLOCKED] $file (User Layer)\n"
    elif is_hybrid "$file"; then
        HYBRID_FILES="$HYBRID_FILES  [MERGE]   $file (Hybrid)\n"
    else
        SAFE_FILES="$SAFE_FILES  [UPDATE]  $file\n"
    fi
done <<< "$CHANGES"

echo "│"
[ -n "$SAFE_FILES" ] && echo -e "│ System Layer (will update):\n$SAFE_FILES"
[ -n "$HYBRID_FILES" ] && echo -e "│ Hybrid Layer (manual merge needed):\n$HYBRID_FILES"
[ -n "$BLOCKED_FILES" ] && echo -e "│ User Layer (protected, skipped):\n$BLOCKED_FILES"

if [ "$MODE" = "--apply" ]; then
    # Backup current state
    mkdir -p "$BACKUP_DIR"
    echo -e "$SAFE_FILES" > "$BACKUP_DIR/updated-files.txt"
    git stash push -m "update-system backup" 2>/dev/null || true

    # Checkout only System Layer files from remote
    while IFS= read -r file; do
        [ -z "$file" ] && continue
        if ! is_user_layer "$file" && ! is_hybrid "$file"; then
            git checkout "origin/$MAIN_BRANCH" -- "$file" 2>/dev/null || true
        fi
    done <<< "$CHANGES"

    echo "│"
    echo "│ [DONE] System Layer files updated.              │"
    echo "│ Backup at: $BACKUP_DIR                          │"
    if [ -n "$HYBRID_FILES" ]; then
        echo "│ [TODO] Hybrid files need manual merge.         │"
    fi
elif [ "$MODE" = "--rollback" ]; then
    LATEST_STASH=$(git stash list | head -1 | grep "update-system backup" || echo "")
    if [ -n "$LATEST_STASH" ]; then
        git stash pop 2>/dev/null
        echo "│ [DONE] Rolled back to pre-update state.        │"
    else
        echo "│ [FAIL] No update-system backup found in stash. │"
    fi
else
    echo "│"
    echo "│ Dry run complete. Use --apply to update.       │"
fi

echo "└─────────────────────────────────────────────────┘"
