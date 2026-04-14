#!/usr/bin/env python3
"""Context Threshold Stop Gate — R57 steal from CC-v3.

Stop hook: when context usage >= 85%, blocks Claude from stopping normally
and forces a handoff. This is PHYSICAL interception — Claude cannot bypass it.

Reads context% from tmpfile written by .claude/scripts/status.py (StatusLine).
"""

import json
import sys
import os
import tempfile
from pathlib import Path

CONTEXT_THRESHOLD = 85  # Block at this percentage


def get_session_id(data: dict) -> str:
    sid = data.get("session_id", "")
    if not sid:
        sid = os.environ.get("CLAUDE_SESSION_ID", "default")
    return sid


def read_context_pct(session_id: str) -> int | None:
    """Read context% from tmpfile (written by StatusLine)."""
    short_id = session_id[:8] if len(session_id) > 8 else session_id
    tmpfile = Path(tempfile.gettempdir()) / f"claude-context-pct-{short_id}.txt"
    try:
        return int(tmpfile.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    # Anti-recursion: if this stop was triggered by the gate itself, let it pass
    if data.get("stop_hook_active"):
        print("{}")
        return

    session_id = get_session_id(data)
    pct = read_context_pct(session_id)

    if pct is not None and pct >= CONTEXT_THRESHOLD:
        remaining = 100 - pct
        result = {
            "decision": "block",
            "reason": (
                f"Context at {pct}% (only {remaining}% remaining). "
                "You're about to hit automatic compaction. "
                "Before stopping: 1) /commit any uncommitted work, "
                "2) write a handoff note to tmp/compaction-snapshots/, "
                "3) tell the user to start a new session. "
                "Do NOT just stop — save state first."
            ),
        }
        print(json.dumps(result))
    else:
        print("{}")


if __name__ == "__main__":
    main()
