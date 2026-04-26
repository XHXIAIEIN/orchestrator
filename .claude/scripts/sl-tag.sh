#!/usr/bin/env bash
# sl-tag: broadcast a short status to the Claude Code statusline.
#
# Usage:
#   bash .claude/scripts/sl-tag.sh "R80 millhouse phase1"   # set tag
#   bash .claude/scripts/sl-tag.sh --clear                  # remove tag
#   bash .claude/scripts/sl-tag.sh                          # show current tag
#
# The tag is written to <repo-or-worktree>/.claude/hooks/state/sl-tag.txt.
# That path is already gitignored. Because each git worktree has its own
# top-level, each worktree carries its own independent tag.
# statusline.py reads the file on every render (no cache), so updates show up
# on the next prompt.

set -e

TOPLEVEL="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$TOPLEVEL" ]; then
  echo "sl-tag: not inside a git repo or worktree" >&2
  exit 1
fi

DIR="$TOPLEVEL/.claude/hooks/state"
FILE="$DIR/sl-tag.txt"
mkdir -p "$DIR"

if [ "${1:-}" = "--clear" ]; then
  rm -f "$FILE"
  echo "sl-tag: cleared"
elif [ $# -eq 0 ]; then
  if [ -f "$FILE" ]; then cat "$FILE"; echo; else echo "(no tag)"; fi
else
  # Collapse all args into one line, strip newlines, cap length
  VALUE="$*"
  VALUE="${VALUE//$'\n'/ }"
  printf '%s' "${VALUE:0:48}" > "$FILE"
  echo "sl-tag: ${VALUE:0:48}"
fi
