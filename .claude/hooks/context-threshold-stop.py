#!/usr/bin/env python3
"""Context Threshold Stop Gate — R57 steal from CC-v3.

Stop hook: when context usage >= 85%, blocks Claude from stopping normally
and forces a handoff. This is PHYSICAL interception — Claude cannot bypass it.

Reads token usage from transcript_path (the only reliable source in Stop hooks).
"""

import json
import sys

CONTEXT_THRESHOLD = 85
DEFAULT_WINDOW = 200000


def get_latest_usage(transcript_path: str) -> dict | None:
    """Read the last assistant message's usage from transcript JSONL."""
    try:
        # Read from end — usage is in the last few lines
        with open(transcript_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, FileNotFoundError):
        return None

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage = entry.get("message", {}).get("usage")
        if usage:
            return usage
    return None


def compute_context_pct(usage: dict) -> int:
    total_input = (
        usage.get("input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
    )
    window = DEFAULT_WINDOW
    return min(100, int(total_input / window * 100))


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    transcript_path = data.get("transcript_path", "")
    if not transcript_path:
        print("{}")
        return

    usage = get_latest_usage(transcript_path)
    if not usage:
        print("{}")
        return

    pct = compute_context_pct(usage)

    if pct >= CONTEXT_THRESHOLD:
        remaining = 100 - pct
        # R71 Hermes: Budget exhaustion graceful summary path
        # Don't just say "write a handoff" — provide a structured template
        # that forces the model to enumerate progress and pending items.
        result = {
            "decision": "block",
            "reason": (
                f"⚠ CONTEXT BUDGET CRITICAL: {pct}% used, {remaining}% remaining.\n"
                "Automatic compaction is imminent. You MUST produce a graceful summary NOW.\n\n"
                "OUTPUT THIS EXACT STRUCTURE before doing anything else:\n"
                "```\n"
                "## Session Summary (context budget exhausted)\n"
                "### Completed\n"
                "- [list each completed task with verification status]\n"
                "### In Progress\n"
                "- [list each incomplete task with current state]\n"
                "### Not Started\n"
                "- [list remaining planned tasks]\n"
                "### Handoff for Next Session\n"
                "- Branch: <current branch>\n"
                "- Next step: <exact next action>\n"
                "- Key context: <critical info the next session needs>\n"
                "```\n"
                "Then: 1) /commit any uncommitted work, "
                "2) Save this summary to tmp/compaction-snapshots/, "
                "3) Tell the user to start a new session with the handoff prompt."
            ),
            "pattern_id": "budget-exhaustion-summary",
            "severity": "critical",
            "context_pct": pct,
        }
        print(json.dumps(result))
    else:
        print("{}")


if __name__ == "__main__":
    main()
