#!/bin/bash
# R83 P0#2 — phase-gate hook integration test harness
# Feeds fixture scenarios through .claude/hooks/phase-gate.sh and asserts block/allow outcomes.
set -u

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOK="$REPO_ROOT/.claude/hooks/phase-gate.sh"
FIXTURE="$REPO_ROOT/tests/hooks/fixtures/phase-gate-scenarios.json"

fail=0
count=$(jq 'length' "$FIXTURE")
for i in $(seq 0 $((count - 1))); do
  label=$(jq -r ".[$i].label" "$FIXTURE")
  expected=$(jq -r ".[$i].expected" "$FIXTURE")
  state=$(jq -c ".[$i].phase_state" "$FIXTURE")
  payload=$(jq -c ".[$i].tool_payload" "$FIXTURE")

  tmp=$(mktemp)
  echo "$state" > "$tmp"

  out=$(echo "$payload" | PHASE_STATE="$tmp" bash "$HOOK" 2>&1)
  rm -f "$tmp"

  case "$expected" in
    block)
      if echo "$out" | jq -e '.decision == "block"' >/dev/null 2>&1; then
        echo "PASS: $label"
      else
        echo "FAIL: $label: $out"; fail=1
      fi
      ;;
    allow)
      if [ -z "$out" ]; then
        echo "PASS: $label"
      else
        echo "FAIL: $label: $out"; fail=1
      fi
      ;;
  esac
done

exit $fail
