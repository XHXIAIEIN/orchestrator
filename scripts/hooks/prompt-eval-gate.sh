#!/usr/bin/env bash
# Prompt Eval Gate — pre-commit hook
# Blocks commits that regress department prompt quality.
#
# Install:
#   cp scripts/hooks/prompt-eval-gate.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# Skip (escape hatch):
#   SKIP_PROMPT_EVAL=1 git commit ...

set -euo pipefail

# Allow bypass
if [[ "${SKIP_PROMPT_EVAL:-0}" == "1" ]]; then
    echo "⚠️  Prompt eval gate SKIPPED (SKIP_PROMPT_EVAL=1)"
    exit 0
fi

PROMPT_PATTERNS=(
    "departments/*/SKILL.md"
    "departments/**/prompt.md"
)

changed_prompts=()
for pattern in "${PROMPT_PATTERNS[@]}"; do
    while IFS= read -r file; do
        [[ -n "$file" ]] && changed_prompts+=("$file")
    done < <(git diff --cached --name-only -- "$pattern" 2>/dev/null)
done

if [[ ${#changed_prompts[@]} -eq 0 ]]; then
    exit 0  # No prompt changes, pass through
fi

echo "Prompt changes detected: ${changed_prompts[*]}"
echo "   Running eval gate..."

exit_code=0

for file in "${changed_prompts[@]}"; do
    # Extract department and division from path
    # departments/<dept>/<div>/prompt.md OR departments/<dept>/SKILL.md
    dept=$(echo "$file" | cut -d'/' -f2)
    filename=$(basename "$file")

    if [[ "$filename" == "SKILL.md" ]]; then
        # SKILL.md change: test all divisions in that department
        div=""
        echo "   Evaluating $dept (SKILL.md change)..."
    else
        div=$(echo "$file" | cut -d'/' -f3)
        echo "   Evaluating $dept/$div..."
    fi

    # Build eval command
    eval_args=(
        --department "$dept"
        --mode ab
        --old-ref "HEAD"
        --new-ref ""
    )
    if [[ -n "$div" ]]; then
        eval_args+=(--division "$div")
    fi

    # Run A/B eval
    if python -m src.governance.eval.prompt_eval "${eval_args[@]}"; then
        echo "   PASS: $dept${div:+/$div}"
    else
        echo "   FAIL: $dept${div:+/$div} — commit blocked"
        echo "   Use SKIP_PROMPT_EVAL=1 git commit to bypass (not recommended)"
        exit_code=1
    fi
done

if [[ $exit_code -eq 0 ]]; then
    echo "Prompt eval passed for all changed departments"
fi

exit $exit_code
