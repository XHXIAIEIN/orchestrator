#!/bin/bash
# anti-fabrication.sh — Stop hook: warns when committed code contains unacknowledged fabrication markers.
# Exits 0 always (warn-only, never blocks).
# GIT_DIFF_OVERRIDE: if set, uses its value as the diff input instead of running git diff HEAD (test shim).

set -euo pipefail

# --selftest mode
if [ "${1:-}" = "--selftest" ]; then
    tmpfile="$(mktemp)"
    printf '+  TODO: mock this endpoint\n' > "$tmpfile"
    export GIT_DIFF_OVERRIDE
    GIT_DIFF_OVERRIDE="$(cat "$tmpfile")"
    rm -f "$tmpfile"
    output="$(GIT_DIFF_OVERRIDE="$GIT_DIFF_OVERRIDE" bash "$0")"
    if echo "$output" | grep -q 'ANTI-FABRICATION'; then
        echo "selftest PASS: ANTI-FABRICATION detected"
        exit 0
    else
        echo "selftest FAIL: expected ANTI-FABRICATION in output, got: $output" >&2
        exit 1
    fi
fi

# Get diff content
if [ -n "${GIT_DIFF_OVERRIDE:-}" ]; then
    diff_content="$GIT_DIFF_OVERRIDE"
else
    diff_content="$(git diff HEAD --unified=0 2>/dev/null)" || exit 0
    if [ -z "$diff_content" ]; then
        exit 0
    fi
fi

# Extract only new (+) lines, excluding diff headers (+++)
new_lines="$(printf '%s\n' "$diff_content" | grep '^+' | grep -v '^+++')"

if [ -z "$new_lines" ]; then
    exit 0
fi

# Apply whitelist: remove lines from whitelisted paths
# Whitelist: tests/fixtures/, tests/, docs/, .md:, # legitimate-stub:
filtered="$(printf '%s\n' "$new_lines" | grep -vE 'tests/fixtures/|tests/|docs/|\.md:|# legitimate-stub:')"

if [ -z "$filtered" ]; then
    exit 0
fi

# Check for fabrication markers
matches="$(printf '%s\n' "$filtered" | grep -iE '(^|\s)(mock|TODO|stub|FIXME|placeholder|fake)(\s|:|$)' || true)"

if [ -z "$matches" ]; then
    exit 0
fi

# Collect first 5 matching lines
first5="$(printf '%s\n' "$matches" | head -5)"

# Emit systemMessage warning via stdout JSON
printf '{"systemMessage":"ANTI-FABRICATION: New code contains unacknowledged fabrication markers (mock/TODO/stub/FIXME/placeholder/fake). Either resolve them now, or annotate each with '"'"'# legitimate-stub: <reason>'"'"' and explain in your completion declaration which stubs remain and why. Matched lines:\\n%s"}\n' "$first5"

exit 0
