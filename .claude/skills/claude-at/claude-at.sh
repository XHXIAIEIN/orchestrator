#!/usr/bin/env bash
# claude-at — launch a real claude CLI session in <target-dir> with a pre-seeded prompt.
# Opens a new Windows Terminal tab (or cmd.exe window fallback) that runs claude and
# keeps the shell open after exit so the user can inspect results.
#
# Usage:
#   claude-at.sh <target-dir> <prompt-file> [title]
#
# Example:
#   claude-at.sh .claude/worktrees/steal-eureka .claude/tasks/eureka.md

set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 <target-dir> <prompt-file> [title]" >&2
  exit 2
fi

TARGET_DIR="$1"
PROMPT_FILE="$2"
TITLE="${3:-claude@$(basename "$TARGET_DIR")}"

if [ ! -d "$TARGET_DIR" ]; then
  echo "error: target dir not found: $TARGET_DIR" >&2
  exit 1
fi

if [ ! -r "$PROMPT_FILE" ]; then
  echo "error: prompt file not readable: $PROMPT_FILE" >&2
  exit 1
fi

# Resolve to absolute paths so the child shell doesn't need to know parent cwd.
TARGET_ABS="$(cd "$TARGET_DIR" && pwd -W 2>/dev/null || cd "$TARGET_DIR" && pwd)"
PROMPT_ABS="$(cd "$(dirname "$PROMPT_FILE")" && pwd -W 2>/dev/null || cd "$(dirname "$PROMPT_FILE")" && pwd)/$(basename "$PROMPT_FILE")"

# The child-side command: cd, run claude with prompt (read from file at invocation time),
# then drop into a shell so the user can look at the result.
CHILD_CMD="cd '$TARGET_ABS' && claude \"\$(cat '$PROMPT_ABS')\"; echo; echo '[claude exited — shell open for inspection]'; exec bash"

if command -v wt.exe >/dev/null 2>&1; then
  # Windows Terminal: new tab in the current window (-w 0), with title and cwd.
  # Note: we pass 'bash -lc' as the shell action; wt will spawn it.
  wt.exe -w 0 nt --title "$TITLE" -d "$TARGET_ABS" bash -lc "$CHILD_CMD" &
  echo "launched: $TITLE -> $TARGET_ABS"
elif command -v cmd.exe >/dev/null 2>&1; then
  # Fallback: plain cmd window via 'start'.
  cmd.exe //c start "$TITLE" bash -lc "$CHILD_CMD" &
  echo "launched (cmd fallback): $TITLE -> $TARGET_ABS"
else
  echo "error: neither wt.exe nor cmd.exe on PATH — cannot spawn terminal" >&2
  exit 1
fi
