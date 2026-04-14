#!/usr/bin/env python3
"""StatusLine context monitor — R57 steal from CC-v3/claudefa.st.

Receives JSON on stdin with context_window data each turn.
Outputs colored status text for the status bar.
Writes context% to tmpfile for cross-hook IPC (consumed by Stop gate).
Detects compaction events (context% drop >10%).
"""

import json
import sys
import os
import tempfile
from pathlib import Path
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────
OVERHEAD_TOKENS = 45000  # Claude Code internal overhead estimate
DEFAULT_WINDOW = 200000
COMPACTION_DROP_THRESHOLD = 10  # % drop that signals compaction occurred

# Color thresholds (ANSI)
GREEN_MAX = 60
YELLOW_MAX = 80
# >= YELLOW_MAX is red


def get_session_id(data: dict) -> str:
    """Extract a stable session identifier from hook input."""
    sid = data.get("session_id", "")
    if not sid:
        sid = os.environ.get("CLAUDE_SESSION_ID", "default")
    return sid


def get_tmpfile_path(session_id: str) -> Path:
    """IPC tmpfile path — other hooks read this to get context%."""
    short_id = session_id[:8] if len(session_id) > 8 else session_id
    return Path(tempfile.gettempdir()) / f"claude-context-pct-{short_id}.txt"


def compute_context_pct(data: dict) -> int | None:
    """Compute context usage percentage from hook input."""
    cw = data.get("context_window", {})
    if not cw:
        return None

    # Method 1: Use remaining_percentage if available (most direct)
    remaining = cw.get("remaining_percentage")
    if remaining is not None:
        return min(100, max(0, 100 - int(remaining)))

    # Method 2: Compute from token counts
    usage = cw.get("current_usage", {})
    if not usage:
        return None

    total = (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
        + OVERHEAD_TOKENS
    )
    window_size = cw.get("context_window_size", DEFAULT_WINDOW)
    if window_size <= 0:
        return None

    return min(100, int(total / window_size * 100))


def colorize(pct: int) -> str:
    """ANSI-colored context% for status bar."""
    if pct < GREEN_MAX:
        color = "\033[32m"  # green
    elif pct < YELLOW_MAX:
        color = "\033[33m"  # yellow
    else:
        color = "\033[31m"  # red
    reset = "\033[0m"
    return f"{color}{pct}%{reset}"


def detect_compaction(tmpfile: Path, current_pct: int, session_id: str) -> bool:
    """Check if compaction just happened (context% dropped significantly)."""
    if not tmpfile.exists():
        return False
    try:
        prev = int(tmpfile.read_text().strip())
        if prev - current_pct > COMPACTION_DROP_THRESHOLD:
            # Log the compaction event
            log_dir = Path(tempfile.gettempdir())
            log_file = log_dir / "claude-autocompact.log"
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] session={session_id[:8]} drop={prev}%→{current_pct}%\n")
            return True
    except (ValueError, OSError):
        pass
    return False


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    pct = compute_context_pct(data)
    if pct is None:
        # No context data available — output minimal status
        print("ctx: --")
        return

    session_id = get_session_id(data)
    tmpfile = get_tmpfile_path(session_id)

    # Detect compaction before writing new value
    compacted = detect_compaction(tmpfile, pct, session_id)

    # Write current context% to tmpfile (atomic: write tmp then rename)
    try:
        tmp_write = tmpfile.with_suffix(".tmp")
        tmp_write.write_text(str(pct))
        tmp_write.replace(tmpfile)
    except OSError:
        pass

    # Build status output
    status = f"ctx: {colorize(pct)}"
    if compacted:
        status += " \033[35m[COMPACTED]\033[0m"
    elif pct >= YELLOW_MAX:
        remaining = 100 - pct
        status += f" \033[33m({remaining}% left)\033[0m"

    print(status)


if __name__ == "__main__":
    main()
