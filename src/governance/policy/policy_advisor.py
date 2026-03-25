"""
Policy Advisor — OpenShell-inspired feedback loop for Blueprint policies.

Cycle: Observe (agent events) → Aggregate (patterns) → Suggest (blueprint changes) → Review (human)

Instead of hand-writing blueprint.yaml policies, we observe what actually happens
during task execution and generate data-driven suggestions:
  - Tools the agent tried to use but weren't in allowed_tools
  - Paths the agent accessed that could be added to policy
  - Tasks that timed out (suggest increasing timeout_s)
  - Tasks that hit max_turns (suggest increasing max_turns)
  - Read-only departments that attempted writes

Denials are stored in departments/{dept}/policy-denials.jsonl
Suggestions are written to departments/{dept}/policy-suggestions.md
"""
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

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


# ── Suggest: generate blueprint changes ──────────────────────────

def generate_suggestions(department: str) -> str:
    """Generate human-readable policy suggestions based on accumulated denials.

    Returns markdown text. Also writes to departments/{dept}/policy-suggestions.md.
    """
    from src.governance.policy.blueprint import load_blueprint

    agg = aggregate_denials(department)
    if agg["total"] == 0:
        return ""

    bp = load_blueprint(department)
    if not bp:
        return ""

    lines = [
        f"# Policy Suggestions for {bp.name_zh} ({department})",
        f"",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
        f"from {agg['total']} denial events_",
        "",
    ]

    suggestions = []

    # Tool suggestions
    if agg["top_tools_blocked"]:
        lines.append("## Tool Access")
        for tool, count in agg["top_tools_blocked"]:
            lines.append(f"- **{tool}** blocked {count}x → Consider adding to `policy.allowed_tools`")
            suggestions.append({
                "field": "policy.allowed_tools",
                "action": "add",
                "value": tool,
                "evidence": f"Blocked {count} times across recent tasks",
            })
        lines.append("")

    # Timeout suggestions
    if agg["timeout_count"] >= 2:
        lines.append("## Timeout")
        lines.append(f"- {agg['timeout_count']} timeouts detected (current: {bp.timeout_s}s)")
        lines.append(f"- → Consider increasing `timeout_s` to {bp.timeout_s + 120}")
        suggestions.append({
            "field": "timeout_s",
            "action": "increase",
            "value": bp.timeout_s + 120,
            "evidence": f"{agg['timeout_count']} timeout events",
        })
        lines.append("")

    # Max turns suggestions
    if agg["max_turns_count"] >= 2:
        lines.append("## Max Turns")
        lines.append(f"- {agg['max_turns_count']} tasks hit turn limit (current: {bp.max_turns})")
        lines.append(f"- → Consider increasing `max_turns` to {bp.max_turns + 10}")
        suggestions.append({
            "field": "max_turns",
            "action": "increase",
            "value": bp.max_turns + 10,
            "evidence": f"{agg['max_turns_count']} max_turns events",
        })
        lines.append("")

    # Write-in-readonly suggestions
    write_count = agg["by_type"].get("write_in_readonly", 0)
    if write_count >= 2:
        lines.append("## Read-Only Friction")
        lines.append(f"- {write_count} write attempts in read-only department")
        lines.append(f"- → Review if `read_only: true` is still appropriate, "
                     f"or ensure tasks requiring writes go to engineering")
        lines.append("")

    # Summary
    if suggestions:
        lines.append("## Blueprint Diff (suggested)")
        lines.append("```yaml")
        for s in suggestions:
            lines.append(f"# {s['evidence']}")
            if s["action"] == "add":
                lines.append(f"{s['field']}: [..., {s['value']}]")
            else:
                lines.append(f"{s['field']}: {s['value']}")
        lines.append("```")
        lines.append("")
        lines.append("_Apply these changes to `blueprint.yaml` after review._")

    md = "\n".join(lines)

    # Write to file
    try:
        _suggestions_path(department).write_text(md, encoding="utf-8")
    except Exception as e:
        log.warning(f"PolicyAdvisor: failed to write suggestions for {department}: {e}")

    return md


def generate_all_suggestions() -> dict[str, str]:
    """Generate suggestions for all departments. Returns {dept: markdown}."""
    results = {}
    if not _DEPT_ROOT.exists():
        return results

    for dept_dir in sorted(_DEPT_ROOT.iterdir()):
        if not dept_dir.is_dir() or dept_dir.name.startswith((".", "_", "shared")):
            continue
        denials_file = dept_dir / "policy-denials.jsonl"
        if denials_file.exists():
            md = generate_suggestions(dept_dir.name)
            if md:
                results[dept_dir.name] = md

    return results


# ── Mitchell Rule: auto-apply denial patterns ─────────────────────

AUTO_APPLY_THRESHOLD = 3  # Same denial type 3+ times → auto-apply
AUTO_APPLY_LOG_FILE = "auto-applied-rules.jsonl"


class PolicyAdvisor:
    """
    Mitchell 法则: agent 犯了一个错, 就在 harness 里加一个机制确保它再也不犯。

    封装 policy_advisor 模块函数，并提供 auto_apply_rules() 自动闭环能力。
    高置信度 pattern (同一 denial 3次+) 自动写入 blueprint.yaml。
    """

    # Delegate module-level functions as instance methods
    # (these read from self._dept_dir so tests can patch it)
    def record_denial(self, dept: str, task_id: int, denial_type: str,
                      detail: str, suggested_fix: str = ""):
        path = self._dept_dir(dept) / "policy-denials.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "department": dept,
            "task_id": task_id,
            "type": denial_type,
            "detail": detail,
            "suggested_fix": suggested_fix,
        }
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            log.warning(f"PolicyAdvisor: failed to write denial for {dept}: {e}")

    def load_denials(self, dept: str, limit: int = 100) -> list[dict]:
        path = self._dept_dir(dept) / "policy-denials.jsonl"
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            recent = lines[-limit:] if len(lines) > limit else lines
            result = []
            for line in recent:
                if line.strip():
                    try:
                        result.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            return result
        except Exception:
            return []

    def aggregate_denials(self, dept: str) -> dict:
        denials = self.load_denials(dept)
        if not denials:
            return {"total": 0, "by_type": {}, "top_tools_blocked": [],
                    "timeout_count": 0, "max_turns_count": 0}

        by_type = Counter(d.get("type", "unknown") for d in denials)

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

    def generate_suggestions(self, dept: str) -> str:
        return generate_suggestions(dept)

    # ── Auto-apply ──────────────────────────────────────────────────

    def auto_apply_rules(self, dept: str) -> list[dict]:
        """
        Mitchell 法则: agent 犯了一个错, 就在 harness 里加一个机制确保它再也不犯。
        高置信度 pattern (同一 denial 3次+) 自动写入 blueprint.yaml。
        返回已应用的规则列表。
        """
        aggregated = self.aggregate_denials(dept)
        if aggregated["total"] < AUTO_APPLY_THRESHOLD:
            return []

        applied = []

        # Rule 1: tool_blocked 3+ times for same tool → add to allowed_tools
        top_blocked = aggregated.get("top_tools_blocked", [])
        for tool_name, count in top_blocked:
            if count >= AUTO_APPLY_THRESHOLD:
                if self._add_allowed_tool(dept, tool_name):
                    rule = {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "department": dept,
                        "rule_type": "add_allowed_tool",
                        "detail": f"Added '{tool_name}' to allowed_tools (blocked {count} times)",
                        "tool": tool_name,
                        "trigger_count": count,
                    }
                    applied.append(rule)
                    log.info(f"policy_advisor: auto-applied rule for {dept}: {rule['detail']}")

        # Rule 2: max_turns exhaustion 3+ times → increase max_turns by 50%
        if aggregated.get("max_turns_count", 0) >= AUTO_APPLY_THRESHOLD:
            new_limit = self._increase_max_turns(dept)
            if new_limit:
                rule = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "department": dept,
                    "rule_type": "increase_max_turns",
                    "detail": f"Increased max_turns to {new_limit} (exhausted {aggregated['max_turns_count']} times)",
                    "new_value": new_limit,
                    "trigger_count": aggregated["max_turns_count"],
                }
                applied.append(rule)
                log.info(f"policy_advisor: auto-applied rule for {dept}: {rule['detail']}")

        # Rule 3: timeout 3+ times → increase timeout by 50%
        if aggregated.get("timeout_count", 0) >= AUTO_APPLY_THRESHOLD:
            new_timeout = self._increase_timeout(dept)
            if new_timeout:
                rule = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "department": dept,
                    "rule_type": "increase_timeout",
                    "detail": f"Increased timeout_s to {new_timeout} (timed out {aggregated['timeout_count']} times)",
                    "new_value": new_timeout,
                    "trigger_count": aggregated["timeout_count"],
                }
                applied.append(rule)
                log.info(f"policy_advisor: auto-applied rule for {dept}: {rule['detail']}")

        # Log applied rules
        if applied:
            self._log_auto_applied(dept, applied)

        return applied

    # ── Blueprint I/O ───────────────────────────────────────────────

    def _dept_dir(self, dept: str) -> Path:
        """Return department directory path."""
        return _REPO_ROOT / "departments" / dept

    def _load_blueprint(self, dept: str) -> tuple[dict, Path]:
        """Load blueprint YAML, return (data, path)."""
        bp_path = self._dept_dir(dept) / "blueprint.yaml"
        if not bp_path.exists():
            return {}, bp_path
        with open(bp_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data, bp_path

    def _save_blueprint(self, dept: str, data: dict, bp_path: Path):
        """Save blueprint YAML."""
        with open(bp_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _add_allowed_tool(self, dept: str, tool_name: str) -> bool:
        """Add a tool to allowed_tools in blueprint. Returns True if changed."""
        data, bp_path = self._load_blueprint(dept)
        if not data:
            return False

        policy = data.get("policy", {})
        allowed = policy.get("allowed_tools", [])
        denied = policy.get("denied_tools", [])

        # Safety: don't add if it's in denied_tools (explicit deny overrides)
        if tool_name in denied:
            log.warning(f"policy_advisor: '{tool_name}' is in denied_tools for {dept}, skipping auto-add")
            return False

        if tool_name in allowed:
            return False  # Already allowed

        allowed.append(tool_name)
        policy["allowed_tools"] = allowed
        data["policy"] = policy
        self._save_blueprint(dept, data, bp_path)
        return True

    def _increase_max_turns(self, dept: str, factor: float = 1.5) -> int | None:
        """Increase max_turns by factor. Returns new value or None."""
        data, bp_path = self._load_blueprint(dept)
        if not data:
            return None

        current = data.get("max_turns", 25)
        new_val = min(int(current * factor), 50)  # Cap at 50
        if new_val == current:
            return None

        data["max_turns"] = new_val
        self._save_blueprint(dept, data, bp_path)
        return new_val

    def _increase_timeout(self, dept: str, factor: float = 1.5) -> int | None:
        """Increase timeout_s by factor. Returns new value or None."""
        data, bp_path = self._load_blueprint(dept)
        if not data:
            return None

        current = data.get("timeout_s", 300)
        new_val = min(int(current * factor), 600)  # Cap at 600s
        if new_val == current:
            return None

        data["timeout_s"] = new_val
        self._save_blueprint(dept, data, bp_path)
        return new_val

    def _log_auto_applied(self, dept: str, rules: list[dict]):
        """Log auto-applied rules to JSONL file for audit trail."""
        log_path = self._dept_dir(dept) / AUTO_APPLY_LOG_FILE
        with open(log_path, "a", encoding="utf-8") as f:
            for rule in rules:
                f.write(json.dumps(rule, ensure_ascii=False) + "\n")
