#!/bin/bash
# R83 P0#2 — Phase Gate advancer
# Usage:
#   bash scripts/phase-advance.sh           # advance to phase 1
#   bash scripts/phase-advance.sh --phase 2 # advance to a specific phase
#   bash scripts/phase-advance.sh --reset   # reset to phase 0
# Spec: SOUL/public/prompts/phase-gate.md
set -eu

REPO_ROOT=$(git rev-parse --show-toplevel)
STATE_FILE="$REPO_ROOT/.claude/phase-state.json"
mkdir -p "$(dirname "$STATE_FILE")"

if [ "${1:-}" = "--reset" ]; then
  printf '{"phase": 0, "validated_at": null, "env_fingerprint": null}\n' > "$STATE_FILE"
  echo "PHASE-ADVANCE: reset to phase 0."
  exit 0
fi

PHASE=1
if [ "${1:-}" = "--phase" ] && [ -n "${2:-}" ]; then
  PHASE="$2"
fi

LOCKFILE=$(ls "$REPO_ROOT"/*.lock "$REPO_ROOT"/pyproject.toml "$REPO_ROOT"/requirements*.txt 2>/dev/null | head -1 || true)

if [ -z "$LOCKFILE" ]; then
  echo "PHASE-ADVANCE: No lockfile found. Env fingerprint will be null."
  FINGERPRINT="null-no-lockfile"
  FP_JSON="null"
else
  FINGERPRINT=$(printf '%s\nphase1-validated' "$(cat "$LOCKFILE")" | sha256sum | awk '{print $1}')
  FP_JSON="\"$FINGERPRINT\""
fi

VALIDATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

jq -n \
  --argjson phase "$PHASE" \
  --arg validated_at "$VALIDATED_AT" \
  --argjson fp "$FP_JSON" \
  '{phase: $phase, validated_at: $validated_at, env_fingerprint: $fp}' > "$STATE_FILE"

SHORT_FP=$(echo "$FINGERPRINT" | cut -c1-12)
echo "PHASE-ADVANCE: phase advanced to ${PHASE} at ${VALIDATED_AT}. Fingerprint: ${SHORT_FP}..."
