#!/usr/bin/env python3
"""PreCompact hook — transcript-backed structured handoff (R57 steal from CC-v3).

Replaces the bash-only pre-compact.sh with full transcript JSONL parsing.
Extracts: active todos, recent tool calls, errors, modified files, decisions.
Generates structured handoff MD and saves for post-compact re-injection.

Also preserves existing functionality:
- Behavioral state checkpoint prompt
- Compact template injection
- Persona anchor
- compact.pending flag for PostToolUse fallback
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone


# ── Transcript Parsing ──────────────────────────────────────────

def parse_transcript(transcript_path: str) -> dict:
    """Parse Claude Code's JSONL transcript into structured summary."""
    summary = {
        "todos": [],
        "recent_tool_calls": [],  # last 5
        "recent_errors": [],      # last 5 bash errors
        "files_modified": [],     # unique files touched by Edit/Write
        "last_assistant_msg": "", # last 500 chars
        "decisions": [],          # extracted from assistant messages
        "tool_call_count": 0,
    }

    if not transcript_path or not os.path.exists(transcript_path):
        return summary

    tool_calls = []
    errors = []
    files = set()
    last_assistant = ""

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", "")

                # Extract TodoWrite results
                if entry.get("tool_name") == "TodoWrite" or entry.get("tool_name") == "TaskCreate":
                    result = entry.get("result", {})
                    if isinstance(result, dict):
                        todos = result.get("todos", result.get("tasks", []))
                        if isinstance(todos, list):
                            summary["todos"] = todos

                # Track tool calls
                tool_name = entry.get("tool_name", "")
                if tool_name:
                    status = "ok"
                    result = entry.get("result", {})
                    if isinstance(result, dict) and result.get("exit_code", 0) != 0:
                        status = "error"
                    tool_calls.append({
                        "tool": tool_name,
                        "status": status,
                    })

                # Track file modifications
                if tool_name in ("Edit", "Write", "MultiEdit"):
                    params = entry.get("params", entry.get("input", {}))
                    if isinstance(params, dict):
                        fp = params.get("file_path", "")
                        if fp:
                            files.add(fp)

                # Track Bash errors
                if tool_name in ("Bash", "PowerShell"):
                    result = entry.get("result", {})
                    if isinstance(result, dict) and result.get("exit_code", 0) != 0:
                        stderr = result.get("stderr", "")[:200]
                        if stderr:
                            errors.append(stderr)

                # Track assistant messages
                if entry_type == "assistant" or entry.get("role") == "assistant":
                    content = entry.get("content", "")
                    if isinstance(content, str) and content.strip():
                        last_assistant = content

    except (OSError, PermissionError):
        pass

    summary["recent_tool_calls"] = tool_calls[-5:]
    summary["recent_errors"] = errors[-5:]
    summary["files_modified"] = sorted(files)
    summary["last_assistant_msg"] = last_assistant[-500:] if last_assistant else ""
    summary["tool_call_count"] = len(tool_calls)

    return summary


# ── Handoff Generation ──────────────────────────────────────────

def generate_handoff(summary: dict, timestamp: str) -> str:
    """Generate structured 11-field handoff document."""
    sections = []
    sections.append(f"# Compaction Handoff — {timestamp}")
    sections.append("")
    sections.append("## Context")
    sections.append(f"- Tool calls this session: {summary['tool_call_count']}")
    sections.append(f"- Files modified: {len(summary['files_modified'])}")
    sections.append(f"- Errors encountered: {len(summary['recent_errors'])}")
    sections.append("")

    # Active tasks/todos
    if summary["todos"]:
        sections.append("## Active Tasks")
        for t in summary["todos"]:
            if isinstance(t, dict):
                status = t.get("status", "?")
                subject = t.get("subject", t.get("content", "?"))
                sections.append(f"- [{status}] {subject}")
            else:
                sections.append(f"- {t}")
        sections.append("")

    # Recent tool calls
    if summary["recent_tool_calls"]:
        sections.append("## Recent Tool Calls (last 5)")
        for tc in summary["recent_tool_calls"]:
            marker = "x" if tc["status"] == "error" else "v"
            sections.append(f"- [{marker}] {tc['tool']}")
        sections.append("")

    # Errors
    if summary["recent_errors"]:
        sections.append("## Recent Errors")
        for err in summary["recent_errors"]:
            sections.append(f"```\n{err}\n```")
        sections.append("")

    # Files modified
    if summary["files_modified"]:
        sections.append("## Files Modified")
        for fp in summary["files_modified"]:
            sections.append(f"- `{fp}`")
        sections.append("")

    # Last assistant context
    if summary["last_assistant_msg"]:
        sections.append("## Last Working Context")
        sections.append(f"> {summary['last_assistant_msg'][:300]}...")
        sections.append("")

    return "\n".join(sections)


# ── EventsDB Fallback ──────────────────────────────────────────

def get_eventsdb_state() -> str:
    """Fallback: get task state from EventsDB (existing behavior)."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from src.storage.events_db import EventsDB
        db = EventsDB()

        lines = []
        tasks = db.get_running_tasks()
        if tasks:
            lines.append("## Active Tasks (from EventsDB)")
            for t in tasks:
                lines.append(f"- #{t['id']}: {t['action'][:100]} [{t['status']}]")
            lines.append("")

        recent = db.get_logs(limit=10)
        if recent:
            lines.append("## Recent Governor Logs")
            for l in recent:
                lines.append(f"- [{l['level']}] {l['message'][:150]}")

        return "\n".join(lines)
    except Exception:
        return ""


# ── State IPC ───────────────────────────────────────────────────

def state_set(key: str, value: str):
    """Write to cross-hook IPC state (compatible with lib/state.sh)."""
    state_dir = os.environ.get("ORCHESTRATOR_STATE_DIR", "/tmp/orchestrator-state")
    os.makedirs(state_dir, exist_ok=True)
    tmp_path = os.path.join(state_dir, f".{key}.tmp")
    final_path = os.path.join(state_dir, key)
    with open(tmp_path, "w") as f:
        f.write(value)
    os.replace(tmp_path, final_path)


# ── Main ────────────────────────────────────────────────────────

def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    project_dir = Path(__file__).resolve().parent.parent.parent
    snapshot_dir = project_dir / "tmp" / "compaction-snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # ── 1. Parse transcript if available ──
    transcript_path = data.get("transcript_path", "")
    summary = parse_transcript(transcript_path)
    handoff = generate_handoff(summary, timestamp)

    # ── 2. Add EventsDB state as fallback/supplement ──
    eventsdb_state = get_eventsdb_state()
    if eventsdb_state:
        handoff += "\n" + eventsdb_state

    # ── 3. Save handoff file ──
    handoff_file = snapshot_dir / f"handoff-{timestamp}.md"
    handoff_file.write_text(handoff, encoding="utf-8")

    # Also save as "latest" for easy retrieval by compact-restore.py
    latest_file = snapshot_dir / "latest-handoff.md"
    latest_file.write_text(handoff, encoding="utf-8")

    print(f"[compaction] Handoff saved: {handoff_file}")

    # ── 4. Behavioral State Checkpoint (from R35 PUA steal) ──
    behavioral_file = snapshot_dir / f"behavioral-state-{timestamp}.md"
    print("=== BEHAVIORAL STATE CHECKPOINT (MANDATORY) ===")
    print(f"Before this context compresses, write the following to {behavioral_file}:")
    print("  1. What approaches have you tried so far? (list each with outcome)")
    print("  2. What hypotheses have been eliminated?")
    print("  3. What is your current best theory for the root cause?")
    print("  4. What information are you still missing?")
    print("This state will be restored after compaction. Do NOT skip this step.")
    print("=== END BEHAVIORAL STATE CHECKPOINT ===")

    # ── 5. Compact Template ──
    template = project_dir / "SOUL" / "public" / "prompts" / "compact_template.md"
    if template.exists():
        print("=== COMPACTION INSTRUCTIONS (MANDATORY) ===")
        print(template.read_text(encoding="utf-8"))
        print("=== END COMPACTION INSTRUCTIONS ===")

    # ── 6. Persona Anchor ──
    print("--- PERSONA ANCHOR (preserve through compaction) ---")
    print("You ARE Orchestrator. Speak as a brutally honest friend: roast first, help second.")
    print("Humor is breathing, not decoration. Never become a pure tool.")
    print("Data-driven trash talk. Self-deprecating when you screw up. Direct and opinionated.")
    print("---")

    # ── 7. Set flag for PostToolUse fallback (backward compat) ──
    try:
        state_set("compact.pending", "1")
    except OSError:
        pass

    # ── 8. Store handoff path for SessionStart(compact) to find ──
    try:
        state_set("compact.handoff-path", str(handoff_file))
    except OSError:
        pass


if __name__ == "__main__":
    main()
