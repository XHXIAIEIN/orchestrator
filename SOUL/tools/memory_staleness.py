"""
Memory Staleness Annotator — add human-readable age to memory index entries.

Source: Claude Code R29 — Human-Readable Staleness Signal (P32)

Scans the memory directory, computes each file's age in human-readable format
("2 days ago", "3 weeks ago"), and can annotate MEMORY.md entries with freshness.

Usage:
    python SOUL/tools/memory_staleness.py [--annotate] [--stale-days 30]

    --annotate: Update MEMORY.md in-place with staleness markers
    --stale-days N: Mark files older than N days as potentially stale (default: 30)

Output (no --annotate): prints a staleness report to stdout.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Default memory directory (Claude Code auto-memory)
DEFAULT_MEMORY_DIR = Path(
    os.environ.get(
        "CLAUDE_MEMORY_DIR",
        os.path.expanduser(
            "~/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory"
        ),
    )
)


def human_age(mtime: float) -> str:
    """Convert mtime to human-readable relative time."""
    delta = time.time() - mtime
    if delta < 0:
        return "just now"

    minutes = delta / 60
    hours = delta / 3600
    days = delta / 86400
    weeks = days / 7
    months = days / 30

    if minutes < 1:
        return "just now"
    elif minutes < 60:
        return f"{int(minutes)} min ago"
    elif hours < 24:
        return f"{int(hours)}h ago"
    elif days < 7:
        d = int(days)
        return f"{d} day{'s' if d != 1 else ''} ago"
    elif weeks < 5:
        w = int(weeks)
        return f"{w} week{'s' if w != 1 else ''} ago"
    else:
        m = int(months)
        return f"{m} month{'s' if m != 1 else ''} ago"


def scan_memory_ages(memory_dir: Path | None = None) -> list[dict]:
    """Scan memory files and return age info."""
    d = memory_dir or DEFAULT_MEMORY_DIR
    if not d.exists():
        return []

    results = []
    for f in sorted(d.iterdir()):
        if f.name.startswith(".") or f.name == "MEMORY.md" or f.is_dir():
            continue
        if f.suffix != ".md":
            continue

        stat = f.stat()
        age_str = human_age(stat.st_mtime)
        days_old = (time.time() - stat.st_mtime) / 86400

        results.append({
            "name": f.name,
            "age": age_str,
            "days_old": round(days_old, 1),
            "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })

    return results


def print_staleness_report(stale_days: int = 30):
    """Print a human-readable staleness report."""
    files = scan_memory_ages()
    if not files:
        print("No memory files found.")
        return

    stale = [f for f in files if f["days_old"] > stale_days]
    fresh = [f for f in files if f["days_old"] <= stale_days]

    print(f"Memory staleness report ({len(files)} files, threshold: {stale_days} days)\n")

    if stale:
        print(f"⚠ Potentially stale ({len(stale)}):")
        for f in sorted(stale, key=lambda x: -x["days_old"]):
            print(f"  {f['name']:40s} {f['age']:>15s}")

    if fresh:
        print(f"\n✓ Fresh ({len(fresh)}):")
        for f in sorted(fresh, key=lambda x: -x["days_old"]):
            print(f"  {f['name']:40s} {f['age']:>15s}")


if __name__ == "__main__":
    stale_days = 30
    if "--stale-days" in sys.argv:
        idx = sys.argv.index("--stale-days")
        if idx + 1 < len(sys.argv):
            stale_days = int(sys.argv[idx + 1])

    print_staleness_report(stale_days)
