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
Suggestions are written to data/suggestions/{dept}/policy-suggestions.md
"""
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ── Re-exports for backward compatibility ──
from src.governance.policy.observer import (
    Denial, ALL_TOOLS,
    record_denial, observe_task_execution, _detect_tool_friction,
    load_denials, aggregate_denials,
    _denials_path, _suggestions_path,
    _REPO_ROOT, _DEPT_ROOT,
)
from src.governance.policy.suggester import (
    generate_suggestions, generate_all_suggestions,
)

log = logging.getLogger(__name__)


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
