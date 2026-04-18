#!/usr/bin/env bash
set -euo pipefail

# Recursively expand @import references in a .md file into a flat compiled output.
# Output is written to .compiled/<same-relative-path> under repo root.
# Skips @import lines inside fenced code blocks.
# Usage: bash scripts/prompt-compile.sh <source-md-file>

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <source-md-file>" >&2
    exit 1
fi

INPUT_FILE="$1"

if [[ ! -f "$INPUT_FILE" ]]; then
    echo "Error: file not found: $INPUT_FILE" >&2
    exit 1
fi

# Normalize to Unix-style absolute path (consistent with pwd output)
SOURCE_FILE="$(cd "$(dirname "$INPUT_FILE")" && pwd)/$(basename "$INPUT_FILE")"

compile_file() {
    local file="$1"
    local in_fenced=false

    while IFS= read -r line; do
        # Toggle fenced code block state
        if [[ "$line" =~ ^\`\`\` ]]; then
            if $in_fenced; then
                in_fenced=false
            else
                in_fenced=true
            fi
            echo "$line"
            continue
        fi

        # Inside fenced block — pass through verbatim
        if $in_fenced; then
            echo "$line"
            continue
        fi

        # Match @prompts/<path> or @skills/<path>
        if [[ "$line" =~ ^@(prompts|skills)/(.+)$ ]]; then
            local prefix="${BASH_REMATCH[1]}"
            local rel_path="${BASH_REMATCH[2]}"

            if [[ "$prefix" == "prompts" ]]; then
                local target="$REPO_ROOT/SOUL/public/prompts/$rel_path"
            else
                local target="$REPO_ROOT/.claude/skills/$rel_path"
            fi

            if [[ -f "$target" ]]; then
                compile_file "$target"
            else
                echo "# WARNING: @import target not found: $target" >&2
                echo "$line"
            fi
        else
            echo "$line"
        fi
    done < "$file"
}

# Compute relative path from repo root to source file
REL_PATH="${SOURCE_FILE#$REPO_ROOT/}"
OUTPUT_FILE="$REPO_ROOT/.compiled/$REL_PATH"
OUTPUT_DIR="$(dirname "$OUTPUT_FILE")"

mkdir -p "$OUTPUT_DIR"

{
    echo "# COMPILED — do not edit directly"
    compile_file "$SOURCE_FILE"
} > "$OUTPUT_FILE"

echo "Compiled: $REL_PATH -> .compiled/$REL_PATH"
