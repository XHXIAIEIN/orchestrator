#!/bin/bash
# R83 P0#2 — Phase Gate PreToolUse hook
# Blocks Edit/Write/MultiEdit on non-whitelisted files when phase < 1.
# Spec: SOUL/public/prompts/phase-gate.md
# Self-tests: bash .claude/hooks/phase-gate.sh --selftest
set -u

is_whitelisted() {
  local path="$1"
  local base
  base=$(basename "$path")
  case "$base" in
    *.md) return 0 ;;
    *.lock) return 0 ;;
    package.json|package-lock.json|yarn.lock|pnpm-lock.yaml) return 0 ;;
    pyproject.toml|Pipfile|Pipfile.lock|uv.lock) return 0 ;;
    .python-version|.nvmrc|.node-version) return 0 ;;
    requirements*.txt) return 0 ;;
  esac
  return 1
}

run_gate() {
  local tool_name="$1"
  local file_path="$2"
  local state_file="$3"

  case "$tool_name" in
    Edit|Write|MultiEdit) ;;
    *) return 0 ;;
  esac

  if [ -z "$file_path" ]; then
    return 0
  fi

  if is_whitelisted "$file_path"; then
    return 0
  fi

  local phase=0
  if [ -f "$state_file" ]; then
    phase=$(jq -r '.phase // 0' "$state_file" 2>/dev/null || echo 0)
  fi

  if [ "$phase" -ge 1 ] 2>/dev/null; then
    return 0
  fi

  jq -nc \
    --arg reason "[PHASE-GATE] Edit/Write blocked: phase=0 (env not bootstrapped). File '$file_path' is not on the pre-bootstrap whitelist. Run 'bash scripts/phase-advance.sh' to advance to phase 1. Protocol: SOUL/public/prompts/phase-gate.md" \
    '{decision: "block", reason: $reason}'
  return 0
}

# --- selftest harness ---
if [ "${1:-}" = "--selftest-whitelist" ]; then
  for f in pyproject.toml src/foo.py README.md requirements.txt yarn.lock .python-version a.lock; do
    if is_whitelisted "$f"; then
      echo "$f:allow"
    else
      echo "$f:block"
    fi
  done
  exit 0
fi

if [ "${1:-}" = "--selftest" ]; then
  fail=0
  tmp=$(mktemp)
  # Case 1: phase=0 + src/foo.py → block
  echo '{"phase":0,"validated_at":null,"env_fingerprint":null}' > "$tmp"
  out=$(run_gate "Edit" "src/foo.py" "$tmp")
  if echo "$out" | jq -e '.decision == "block"' >/dev/null 2>&1; then
    echo "PASS: phase0-src-block"
  else
    echo "FAIL: phase0-src-block: $out"; fail=1
  fi
  # Case 2: phase=0 + pyproject.toml → allow (empty)
  out=$(run_gate "Edit" "pyproject.toml" "$tmp")
  if [ -z "$out" ]; then
    echo "PASS: phase0-pyproject-allow"
  else
    echo "FAIL: phase0-pyproject-allow: $out"; fail=1
  fi
  # Case 3: phase=0 + README.md → allow
  out=$(run_gate "Edit" "README.md" "$tmp")
  if [ -z "$out" ]; then
    echo "PASS: phase0-md-allow"
  else
    echo "FAIL: phase0-md-allow: $out"; fail=1
  fi
  # Case 4: phase=1 + src/foo.py → allow
  echo '{"phase":1,"validated_at":"2026-04-19T10:00:00Z","env_fingerprint":"abc"}' > "$tmp"
  out=$(run_gate "Edit" "src/foo.py" "$tmp")
  if [ -z "$out" ]; then
    echo "PASS: phase1-src-allow"
  else
    echo "FAIL: phase1-src-allow: $out"; fail=1
  fi
  rm -f "$tmp"
  exit $fail
fi

# --- normal hook entrypoint ---
INPUT=$(cat)
PARSED=$(echo "$INPUT" | jq -r '[.tool_name // "", .tool_input.file_path // ""] | @tsv' 2>/dev/null || echo $'\t')
TOOL_NAME=$(echo "$PARSED" | cut -f1)
FILE_PATH=$(echo "$PARSED" | cut -f2)

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
PHASE_STATE="${PHASE_STATE:-$REPO_ROOT/.claude/phase-state.json}"

run_gate "$TOOL_NAME" "$FILE_PATH" "$PHASE_STATE"
exit 0
