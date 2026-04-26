#!/usr/bin/env bash
set -euo pipefail

# DFS cycle detector for @import references in prompt/skill markdown files.
# Matches @prompts/ and @skills/ prefixes; skips lines inside fenced code blocks.
# Adapted from tlotp/scripts/import-lint.sh.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOTS=("SOUL/public/prompts" ".claude/skills")

VISITING="$(mktemp)"
VISITED="$(mktemp)"
trap 'rm -f "$VISITING" "$VISITED"' EXIT

CYCLE_FOUND=0

check_file() {
    local file="$1"

    # Already fully visited — no need to re-process
    if grep -qF "$file" "$VISITED" 2>/dev/null; then
        return 0
    fi

    # Back-edge: file is already on the current DFS stack → cycle
    if grep -qF "$file" "$VISITING" 2>/dev/null; then
        echo "CYCLE DETECTED: $file is part of a circular @import chain"
        CYCLE_FOUND=1
        return 1
    fi

    echo "$file" >> "$VISITING"

    local in_fenced=false
    while IFS= read -r line; do
        # Toggle fenced code block state
        if [[ "$line" =~ ^\`\`\` ]]; then
            if $in_fenced; then
                in_fenced=false
            else
                in_fenced=true
            fi
            continue
        fi

        # Skip lines inside fenced blocks
        $in_fenced && continue

        # Match @prompts/<path> or @skills/<path>
        if [[ "$line" =~ ^@(prompts|skills)/(.+)$ ]]; then
            local prefix="${BASH_REMATCH[1]}"
            local rel_path="${BASH_REMATCH[2]}"

            # Resolve to absolute path relative to repo root
            if [[ "$prefix" == "prompts" ]]; then
                local target="$REPO_ROOT/SOUL/public/prompts/$rel_path"
            else
                local target="$REPO_ROOT/.claude/skills/$rel_path"
            fi

            if [[ -f "$target" ]]; then
                check_file "$target" || return 1
            fi
        fi
    done < "$file"

    # Remove from visiting stack, mark as done
    grep -vF "$file" "$VISITING" > "${VISITING}.tmp" && mv "${VISITING}.tmp" "$VISITING"
    echo "$file" >> "$VISITED"
    return 0
}

for root in "${ROOTS[@]}"; do
    abs_root="$REPO_ROOT/$root"
    if [[ ! -d "$abs_root" ]]; then
        continue
    fi
    while IFS= read -r -d '' md_file; do
        check_file "$md_file" || true
    done < <(find "$abs_root" -name "*.md" -print0)
done

if [[ $CYCLE_FOUND -eq 0 ]]; then
    echo "OK: No circular @imports detected"
    exit 0
else
    exit 1
fi
