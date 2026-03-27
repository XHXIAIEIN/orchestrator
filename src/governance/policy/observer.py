"""Policy Observer — record and aggregate denial/friction events from task execution."""
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent
_DEPT_ROOT = _REPO_ROOT / "departments"

# Known tool names in Agent SDK
ALL_TOOLS = {"Bash", "Read", "Edit", "Write", "Glob", "Grep",
             "WebFetch", "WebSearch", "Agent", "NotebookEdit"}


@dataclass
class Denial:
    """A single observed policy denial or friction event."""
    ts: str
    department: str
    task_id: int
    denial_type: str  # "tool_blocked" | "path_denied" | "timeout" | "max_turns" | "write_in_readonly"
    detail: str
    suggested_fix: str = ""


def _denials_path(department: str) -> Path:
    return _DEPT_ROOT / department / "policy-denials.jsonl"


def _suggestions_path(department: str) -> Path:
    return _DEPT_ROOT / department / "policy-suggestions.md"


# ── Observe: record denials ──────────────────────────────────────

def record_denial(department: str, task_id: int, denial_type: str,
                  detail: str, suggested_fix: str = ""):
    """Append a denial event to the department's denials log."""
    path = _denials_path(department)
    path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "department": department,
        "task_id": task_id,
        "type": denial_type,
        "detail": detail,
        "suggested_fix": suggested_fix,
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning(f"PolicyAdvisor: failed to write denial for {department}: {e}")


def observe_task_execution(department: str, task_id: int,
                           agent_events: list, task_output: str,
                           task_status: str, blueprint=None):
    """Analyze a completed task's execution for policy friction signals.

    Called by Governor._finalize_task after each task completes.
    """
    if not blueprint:
        return

    allowed_tools = set(blueprint.policy.allowed_tools)
    denials_found = []

    # 1. Scan agent events for tool usage patterns
    tools_used = Counter()
    tools_attempted = Counter()

    for event in agent_events:
        try:
            data = json.loads(event["data"]) if isinstance(event.get("data"), str) else event.get("data", {})
        except (json.JSONDecodeError, TypeError):
            continue

        for tool_call in data.get("tools", []):
            tool_name = tool_call.get("tool", "")
            if tool_name:
                tools_attempted[tool_name] += 1
                if tool_name in allowed_tools:
                    tools_used[tool_name] += 1

    # Detect tools attempted but not in allowed list
    # Agent SDK blocks these, but the agent may mention wanting to use them
    _detect_tool_friction(department, task_id, task_output, allowed_tools, denials_found)

    # 2. Check for timeout
    if task_status == "failed" and "timeout" in task_output.lower():
        denials_found.append(Denial(
            ts=datetime.now(timezone.utc).isoformat(),
            department=department,
            task_id=task_id,
            denial_type="timeout",
            detail=f"Task timed out (current limit: {blueprint.timeout_s}s)",
            suggested_fix=f"Consider increasing timeout_s to {blueprint.timeout_s + 120}",
        ))

    # 3. Check for max_turns exhaustion
    turn_count = 0
    for event in agent_events:
        try:
            data = json.loads(event["data"]) if isinstance(event.get("data"), str) else event.get("data", {})
        except (json.JSONDecodeError, TypeError):
            continue
        if data.get("turn"):
            turn_count = max(turn_count, data["turn"])

    if turn_count >= blueprint.max_turns - 1:
        denials_found.append(Denial(
            ts=datetime.now(timezone.utc).isoformat(),
            department=department,
            task_id=task_id,
            denial_type="max_turns",
            detail=f"Agent used {turn_count}/{blueprint.max_turns} turns",
            suggested_fix=f"Consider increasing max_turns to {blueprint.max_turns + 10}",
        ))

    # 4. Check for write attempts in read-only departments
    if blueprint.policy.read_only:
        write_signals = re.findall(
            r'(?:cannot|can\'t|unable to|not allowed to)\s+(?:write|edit|modify|create)',
            task_output, re.IGNORECASE
        )
        if write_signals:
            denials_found.append(Denial(
                ts=datetime.now(timezone.utc).isoformat(),
                department=department,
                task_id=task_id,
                denial_type="write_in_readonly",
                detail=f"Read-only department attempted write: {write_signals[0][:100]}",
                suggested_fix="Verify if read_only should remain true, or split task to engineering",
            ))

    # 5. Record all denials
    for denial in denials_found:
        record_denial(
            department=denial.department,
            task_id=denial.task_id,
            denial_type=denial.denial_type,
            detail=denial.detail,
            suggested_fix=denial.suggested_fix,
        )

    if denials_found:
        log.info(f"PolicyAdvisor: recorded {len(denials_found)} denials for {department} task #{task_id}")


def _detect_tool_friction(department: str, task_id: int, output: str,
                          allowed_tools: set, denials: list):
    """Detect when agent output mentions wanting to use tools it doesn't have."""
    # Common patterns when agent can't use a tool
    friction_patterns = [
        (r"(?:I (?:don'?t|do not) have access to|cannot use|can'?t use)\s+(?:the\s+)?(\w+)\s+tool", "tool_blocked"),
        (r"(?:WebFetch|WebSearch|web search|fetch url|browse)", "tool_blocked"),
        (r"I (?:need|would need) to use (\w+)", "tool_blocked"),
    ]

    for pattern, dtype in friction_patterns:
        matches = re.findall(pattern, output, re.IGNORECASE)
        for match in matches:
            tool_name = match if isinstance(match, str) else match
            # Normalize tool name
            for canonical in ALL_TOOLS:
                if canonical.lower() == tool_name.lower():
                    tool_name = canonical
                    break

            if tool_name in ALL_TOOLS and tool_name not in allowed_tools:
                denials.append(Denial(
                    ts=datetime.now(timezone.utc).isoformat(),
                    department=department,
                    task_id=task_id,
                    denial_type="tool_blocked",
                    detail=f"Agent wanted to use '{tool_name}' but it's not in allowed_tools",
                    suggested_fix=f"Add '{tool_name}' to blueprint.yaml policy.allowed_tools",
                ))


# ── Aggregate: analyze patterns ──────────────────────────────────

def load_denials(department: str, limit: int = 100) -> list[dict]:
    """Load recent denial events for a department."""
    path = _denials_path(department)
    if not path.exists():
        return []

    try:
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        recent = lines[-limit:] if len(lines) > limit else lines
        denials = []
        for line in recent:
            if line.strip():
                try:
                    denials.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return denials
    except Exception:
        return []


def aggregate_denials(department: str) -> dict:
    """Aggregate denial patterns for a department.

    Returns:
        {
            "total": int,
            "by_type": {"tool_blocked": 5, "timeout": 2, ...},
            "top_tools_blocked": [("WebFetch", 3), ("Write", 2)],
            "timeout_count": int,
            "max_turns_count": int,
        }
    """
    denials = load_denials(department)
    if not denials:
        return {"total": 0, "by_type": {}, "top_tools_blocked": [],
                "timeout_count": 0, "max_turns_count": 0}

    by_type = Counter(d.get("type", "unknown") for d in denials)

    # Extract blocked tool names
    tool_blocks = []
    for d in denials:
        if d.get("type") == "tool_blocked":
            detail = d.get("detail", "")
            match = re.search(r"'(\w+)'", detail)
            if match:
                tool_blocks.append(match.group(1))

    top_tools = Counter(tool_blocks).most_common(5)

    return {
        "total": len(denials),
        "by_type": dict(by_type),
        "top_tools_blocked": top_tools,
        "timeout_count": by_type.get("timeout", 0),
        "max_turns_count": by_type.get("max_turns", 0),
    }
