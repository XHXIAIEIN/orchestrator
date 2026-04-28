#!/bin/bash
# test_anti_fabrication.sh — Integration tests for anti-fabrication.sh hook.
# Uses GIT_DIFF_OVERRIDE shim to inject fixture content.
# Exits 0 if all 3 cases pass, 1 if any case fails.

set -uo pipefail

HOOK="$(cd "$(dirname "$0")/../.." && pwd)/.claude/hooks/anti-fabrication.sh"
FIXTURES="$(dirname "$0")/fixtures"

fail_count=0

# Case 1: dirty commit triggers warning
output="$(GIT_DIFF_OVERRIDE="$(cat "$FIXTURES/stub-commit-dirty.patch")" bash "$HOOK")"
if echo "$output" | grep -q 'ANTI-FABRICATION'; then
    echo "PASS: dirty commit triggers warning"
else
    echo "FAIL: dirty commit — no warning emitted"
    fail_count=$((fail_count + 1))
fi

# Case 2: clean (annotated) commit passes silently
output="$(GIT_DIFF_OVERRIDE="$(cat "$FIXTURES/stub-commit-clean.patch")" bash "$HOOK")"
if [ -z "$output" ]; then
    echo "PASS: clean commit passes silently"
else
    echo "FAIL: clean commit — false positive warning: $output"
    fail_count=$((fail_count + 1))
fi

# Case 3: docs-only change passes silently (docs/ whitelist suppresses it)
output="$(GIT_DIFF_OVERRIDE="+docs/ TODO: document this section" bash "$HOOK")"
if [ -z "$output" ]; then
    echo "PASS: docs-only passes silently"
else
    echo "FAIL: docs path — false positive: $output"
    fail_count=$((fail_count + 1))
fi

if [ "$fail_count" -gt 0 ]; then
    exit 1
fi
exit 0
