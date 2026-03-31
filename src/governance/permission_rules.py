"""Declarative Permission Rules Engine — stolen from Claude Code v2.1.88.

Claude Code uses regex-based toolPermissionRules in settings.json to
create a three-value decision gate (allow/deny/ask). We adapt this to
Orchestrator's Governor model: allow/deny/escalate.

Three-tier decision flow (Claude Code pattern):
  Tool call → [Pre-hook: InterventionChecker] → [Rules: this module] → [Fallback: PermissionChecker tier]

The key insight from Claude Code: rules are DECLARATIVE (YAML/JSON), not
imperative (code). Adding a new rule = editing a config file, not deploying code.

Usage:
    engine = PermissionRuleEngine()
    decision = engine.evaluate("Bash", {"command": "git push origin main"}, "engineering")
    # decision.action == RuleAction.ESCALATE
    # decision.description == "Any git push needs Governor approval"
"""
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Default rules file path (relative to project root)
_DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "permission_rules.yaml"


class RuleAction(Enum):
    """Three-value decision — the Claude Code pattern."""
    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"
    NO_MATCH = "no_match"  # No rule matched; fall through to tier check


@dataclass
class RuleDecision:
    """Result of evaluating a tool call against declarative rules."""
    action: RuleAction
    rule_pattern: str = ""
    description: str = ""
    tool: str = ""

    @property
    def matched(self) -> bool:
        return self.action != RuleAction.NO_MATCH


@dataclass
class _CompiledRule:
    """A single compiled regex rule."""
    pattern: re.Pattern
    raw_pattern: str
    description: str
    path_field: str  # empty string means match against command/default field


@dataclass
class _ToolRules:
    """Compiled rules for a single tool, grouped by action."""
    allow: list[_CompiledRule] = field(default_factory=list)
    deny: list[_CompiledRule] = field(default_factory=list)
    escalate: list[_CompiledRule] = field(default_factory=list)


class PermissionRuleEngine:
    """Evaluate tool calls against declarative YAML rules.

    Features:
      - Three-value decisions (allow/deny/escalate)
      - Per-tool regex matching
      - Department-specific overrides
      - Hot-reload: watches file mtime, reloads on change
      - Graceful fallback if YAML missing/malformed
    """

    def __init__(self, rules_path: Optional[str | Path] = None):
        self._path = Path(rules_path) if rules_path else _DEFAULT_RULES_PATH
        self._rules: dict[str, _ToolRules] = {}
        self._dept_overrides: dict[str, dict] = {}
        self._last_mtime: float = 0.0
        self._load_rules()

    # ── Public API ──────────────────────────────────────────────────

    def evaluate(self, tool: str, tool_input: dict = None,
                 department: str = "") -> RuleDecision:
        """Evaluate a tool call against the rules.

        Args:
            tool: Tool name (e.g. "Bash", "Write", "Agent")
            tool_input: Tool arguments dict
            department: Department key for department-specific overrides

        Returns:
            RuleDecision with action and matched rule info.
        """
        self._maybe_reload()
        tool_input = tool_input or {}

        # Normalize tool name to lowercase for matching
        tool_lower = tool.lower()

        # Determine which rule sets to check
        rule_sets = self._get_rule_sets(tool_lower, department)
        if not rule_sets:
            return RuleDecision(action=RuleAction.NO_MATCH, tool=tool)

        # Extract the value to match against
        match_value = self._extract_match_value(tool_lower, tool_input)

        # Evaluate in order: deny → allow → escalate
        # Deny first (safety), then allow (fast-path), then escalate
        for action, action_name in [
            (rule_sets.deny, RuleAction.DENY),
            (rule_sets.allow, RuleAction.ALLOW),
            (rule_sets.escalate, RuleAction.ESCALATE),
        ]:
            for rule in action:
                value = self._get_rule_target(rule, tool_input, match_value)
                if value and rule.pattern.search(value):
                    return RuleDecision(
                        action=action_name,
                        rule_pattern=rule.raw_pattern,
                        description=rule.description,
                        tool=tool,
                    )

        return RuleDecision(action=RuleAction.NO_MATCH, tool=tool)

    def get_department_max_tier(self, department: str) -> Optional[str]:
        """Get max_tier override for a department, if any."""
        self._maybe_reload()
        dept_config = self._dept_overrides.get(department, {})
        return dept_config.get("max_tier")

    def reload(self):
        """Force reload rules from disk."""
        self._load_rules()

    def get_stats(self) -> dict:
        """Return stats about loaded rules."""
        stats = {}
        for tool, rules in self._rules.items():
            stats[tool] = {
                "allow": len(rules.allow),
                "deny": len(rules.deny),
                "escalate": len(rules.escalate),
            }
        return {
            "rules_path": str(self._path),
            "loaded": bool(self._rules),
            "tools": stats,
            "department_overrides": list(self._dept_overrides.keys()),
        }

    # ── Internal ────────────────────────────────────────────────────

    def _get_rule_sets(self, tool_lower: str, department: str) -> Optional[_ToolRules]:
        """Get the merged rule set for a tool, including department overrides."""
        base = self._rules.get(tool_lower)
        if not base and not department:
            return None

        # Check for department-specific overrides
        dept_config = self._dept_overrides.get(department, {})
        dept_tool_rules = dept_config.get(tool_lower)

        if not dept_tool_rules and not base:
            return None

        if not dept_tool_rules:
            return base

        # Merge: department rules take priority (prepended)
        merged = _ToolRules(
            allow=list(dept_tool_rules.allow) + (base.allow if base else []),
            deny=list(dept_tool_rules.deny) + (base.deny if base else []),
            escalate=list(dept_tool_rules.escalate) + (base.escalate if base else []),
        )
        return merged

    def _extract_match_value(self, tool_lower: str, tool_input: dict) -> str:
        """Extract the primary value to match against for a tool."""
        if tool_lower == "bash":
            return tool_input.get("command", "")
        elif tool_lower in ("write", "edit"):
            return tool_input.get("file_path", "")
        elif tool_lower == "agent":
            # Match against the agent prompt/description
            return tool_input.get("prompt", tool_input.get("description", ""))
        return str(tool_input)

    def _get_rule_target(self, rule: _CompiledRule, tool_input: dict,
                         default_value: str) -> str:
        """Get the value a rule should match against."""
        if rule.path_field:
            return tool_input.get(rule.path_field, "")
        return default_value

    def _maybe_reload(self):
        """Check file mtime and reload if changed (hot-reload)."""
        try:
            mtime = os.path.getmtime(self._path)
            if mtime > self._last_mtime:
                self._load_rules()
        except OSError:
            pass  # File gone; keep existing rules

    def _load_rules(self):
        """Load and compile rules from YAML file."""
        try:
            import yaml
        except ImportError:
            log.warning("permission_rules: PyYAML not installed, rules engine disabled")
            return

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._last_mtime = os.path.getmtime(self._path)
        except FileNotFoundError:
            log.info(f"permission_rules: {self._path} not found, rules engine disabled")
            return
        except Exception as e:
            log.warning(f"permission_rules: failed to load {self._path}: {e}")
            return

        # Compile tool rules
        self._rules = {}
        raw_rules = data.get("rules", {})
        for tool_name, action_groups in raw_rules.items():
            self._rules[tool_name.lower()] = self._compile_tool_rules(action_groups)

        # Compile department overrides
        self._dept_overrides = {}
        raw_overrides = data.get("department_overrides", {})
        for dept, config in raw_overrides.items():
            dept_data: dict = {}
            if "max_tier" in config:
                dept_data["max_tier"] = config["max_tier"]
            # Compile per-tool rules within department
            for key, val in config.items():
                if key == "max_tier":
                    continue
                if isinstance(val, dict):
                    dept_data[key.lower()] = self._compile_tool_rules(val)
            self._dept_overrides[dept] = dept_data

        tool_count = sum(
            len(r.allow) + len(r.deny) + len(r.escalate)
            for r in self._rules.values()
        )
        log.info(f"permission_rules: loaded {tool_count} rules for {len(self._rules)} tools")

    def _compile_tool_rules(self, action_groups: dict) -> _ToolRules:
        """Compile a tool's action groups into _ToolRules."""
        rules = _ToolRules()
        for action_name in ("allow", "deny", "escalate"):
            raw_list = action_groups.get(action_name, [])
            compiled = []
            for entry in raw_list:
                pattern_str = entry.get("pattern", "")
                try:
                    compiled.append(_CompiledRule(
                        pattern=re.compile(pattern_str, re.IGNORECASE),
                        raw_pattern=pattern_str,
                        description=entry.get("description", ""),
                        path_field=entry.get("path_field", ""),
                    ))
                except re.error as e:
                    log.warning(f"permission_rules: bad regex '{pattern_str}': {e}")
            setattr(rules, action_name, compiled)
        return rules


# ── Singleton ───────────────────────────────────────────────────────

_engine: Optional[PermissionRuleEngine] = None


def get_permission_rule_engine() -> PermissionRuleEngine:
    """Get the singleton rules engine instance."""
    global _engine
    if _engine is None:
        _engine = PermissionRuleEngine()
    return _engine
