#!/usr/bin/env bash
# pre-bash hook: grep precedent-log before executing any bash command
# Runs in <=10ms for typical log size (<500 entries)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../.." || exit 0  # advisory only — never block on repo-root resolution

PRECEDENT_LOG="SOUL/private/precedent-log.md"
COMMAND="${CLAUDE_TOOL_INPUT:-}"  # CC injects the bash command here

if [[ -f "$PRECEDENT_LOG" && -n "$COMMAND" ]]; then
  # Extract first 6 tokens of command as search key
  KEY=$(echo "$COMMAND" | grep -oE '\S+' | head -6 | tr '\n' ' ' | xargs)
  HITS=$(grep -i -- "$KEY" "$PRECEDENT_LOG" 2>/dev/null | head -3 || true)
  if [[ -n "$HITS" ]]; then
    echo "[PRECEDENT] Similar command found in precedent-log:"
    echo "$HITS"
    echo "[PRECEDENT] Review before proceeding."
  fi
fi

exit 0  # always exit 0 — advisory only, never block
