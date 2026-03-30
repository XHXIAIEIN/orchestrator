# src/governance/safety/intervention_checker.py
"""
InterventionChecker — Three-layer graded safety gate for tool execution.

Stolen from: LobeHub's InterventionChecker pattern (Round 16, P0 #4).
Core idea: replace binary pass/block with a three-layer prioritized check:
  Layer 1: Safety blacklist (highest priority, unconditional block)
  Layer 2: Per-tool policy (NEVER / REQUIRED / AUTO / CUSTOM)
  Layer 3: Parameter pattern matching (escalate to REQUIRED on dangerous args)

Unlike the existing ToolPolicy (deny-wins allowlist/denylist), this module
inspects *what* a tool does with *which arguments*, not just the tool name.
The two systems are complementary — ToolPolicy gates access, InterventionChecker
gates execution safety.
"""
from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# ── Enums ────────────────────────────────────────────────────────────


class InterventionPolicy(Enum):
    """Per-tool execution policy."""
    REQUIRED = "required"   # Must get human confirmation before execution
    NEVER    = "never"      # Always blocked, no override
    AUTO     = "auto"       # Allowed without confirmation
    CUSTOM   = "custom"     # Delegate to a custom checker function


class MatchMode(Enum):
    """How to match parameter values against a rule pattern."""
    EXACT    = "exact"
    PREFIX   = "prefix"
    WILDCARD = "wildcard"
    REGEX    = "regex"


# ── Data structures ──────────────────────────────────────────────────


@dataclass(frozen=True)
class InterventionRule:
    """A single intervention rule binding a tool + pattern to a policy."""
    tool_name: str
    policy: InterventionPolicy
    match_mode: MatchMode = MatchMode.EXACT
    param_name: str = ""          # which param to inspect ("" = tool-level, no param check)
    pattern: str = ""             # pattern to match against param value
    reason: str = ""


@dataclass(frozen=True)
class InterventionResult:
    """Outcome of a three-layer check."""
    allowed: bool
    reason: str
    layer: str                        # "blacklist" | "policy" | "param" | "default"
    policy: InterventionPolicy


# ── Checker ──────────────────────────────────────────────────────────


class InterventionChecker:
    """Three-layer graded safety gate.

    Usage::

        checker = InterventionChecker.from_yaml("config/intervention_rules.yaml")
        result = checker.check("Bash", {"command": "rm -rf /"})
        if not result.allowed:
            print(f"Blocked by {result.layer}: {result.reason}")
    """

    def __init__(
        self,
        blacklist: list[str] | None = None,
        tool_policies: dict[str, InterventionPolicy] | None = None,
        param_rules: list[InterventionRule] | None = None,
    ) -> None:
        self._blacklist: list[str] = blacklist or []
        self._tool_policies: dict[str, InterventionPolicy] = tool_policies or {}
        self._param_rules: list[InterventionRule] = param_rules or []

        # Pre-compile regex patterns for Layer 3
        self._compiled: dict[str, re.Pattern[str]] = {}
        for rule in self._param_rules:
            if rule.match_mode == MatchMode.REGEX and rule.pattern:
                try:
                    self._compiled[rule.pattern] = re.compile(rule.pattern, re.IGNORECASE)
                except re.error as exc:
                    log.warning("Bad regex in intervention rule %r: %s", rule.pattern, exc)

    # ── Factory ──────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str | Path) -> InterventionChecker:
        """Load rules from a YAML config file."""
        path = Path(path)
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)

        blacklist = raw.get("blacklist", [])

        tool_policies: dict[str, InterventionPolicy] = {}
        for entry in raw.get("tool_policies", []):
            tool_policies[entry["tool"]] = InterventionPolicy(entry["policy"])

        param_rules: list[InterventionRule] = []
        for entry in raw.get("param_rules", []):
            param_rules.append(InterventionRule(
                tool_name=entry.get("tool", "*"),
                policy=InterventionPolicy(entry.get("policy", "required")),
                match_mode=MatchMode(entry.get("match_mode", "wildcard")),
                param_name=entry.get("param", ""),
                pattern=entry.get("pattern", ""),
                reason=entry.get("reason", ""),
            ))

        return cls(blacklist=blacklist, tool_policies=tool_policies, param_rules=param_rules)

    # ── Three-layer check ────────────────────────────────────────

    def check(self, tool_name: str, params: dict[str, Any] | None = None) -> InterventionResult:
        """Run three-layer intervention check.

        Layer 1: Blacklist — exact substring match on command text → BLOCK.
        Layer 2: Tool policy lookup → NEVER/REQUIRED/AUTO/CUSTOM.
        Layer 3: Parameter pattern matching → escalate to REQUIRED if hit.

        Default (no rules matched): REQUIRED (closed by default).
        """
        params = params or {}

        # ── Layer 1: Safety blacklist ────────────────────────────
        # Flatten all param values into a single string for substring scan
        flat_params = " ".join(str(v) for v in params.values())
        combined = f"{tool_name} {flat_params}"
        for entry in self._blacklist:
            if entry.lower() in combined.lower():
                return InterventionResult(
                    allowed=False,
                    reason=f"Blacklisted: '{entry}'",
                    layer="blacklist",
                    policy=InterventionPolicy.NEVER,
                )

        # ── Layer 2: Per-tool policy ─────────────────────────────
        policy = self._resolve_tool_policy(tool_name)
        if policy is not None:
            if policy == InterventionPolicy.NEVER:
                return InterventionResult(
                    allowed=False,
                    reason=f"Tool '{tool_name}' policy is NEVER",
                    layer="policy",
                    policy=policy,
                )
            if policy == InterventionPolicy.AUTO:
                # Still check Layer 3 — dangerous params can escalate AUTO → REQUIRED
                escalation = self._check_params(tool_name, params)
                if escalation is not None:
                    return escalation
                return InterventionResult(
                    allowed=True,
                    reason=f"Tool '{tool_name}' policy is AUTO",
                    layer="policy",
                    policy=policy,
                )
            if policy == InterventionPolicy.REQUIRED:
                return InterventionResult(
                    allowed=False,
                    reason=f"Tool '{tool_name}' requires confirmation",
                    layer="policy",
                    policy=policy,
                )
            if policy == InterventionPolicy.CUSTOM:
                # CUSTOM without a registered handler → fall through to param check
                pass

        # ── Layer 3: Parameter pattern matching ──────────────────
        escalation = self._check_params(tool_name, params)
        if escalation is not None:
            return escalation

        # ── Default: closed by default ───────────────────────────
        return InterventionResult(
            allowed=False,
            reason="No matching rule — default REQUIRED",
            layer="default",
            policy=InterventionPolicy.REQUIRED,
        )

    # ── Internal helpers ─────────────────────────────────────────

    def _resolve_tool_policy(self, tool_name: str) -> InterventionPolicy | None:
        """Find the most specific policy for a tool (exact match first, then glob)."""
        # Exact match
        if tool_name in self._tool_policies:
            return self._tool_policies[tool_name]
        # Glob match
        for pattern, policy in self._tool_policies.items():
            if fnmatch.fnmatch(tool_name, pattern):
                return policy
        return None

    def _check_params(
        self, tool_name: str, params: dict[str, Any]
    ) -> InterventionResult | None:
        """Layer 3: check param values against pattern rules."""
        for rule in self._param_rules:
            # Tool name filter
            if rule.tool_name != "*" and not fnmatch.fnmatch(tool_name, rule.tool_name):
                continue
            # Param name filter — if rule targets a specific param
            if rule.param_name:
                value = str(params.get(rule.param_name, ""))
                if self._match_value(value, rule):
                    return InterventionResult(
                        allowed=False,
                        reason=rule.reason or f"Param '{rule.param_name}' matched pattern '{rule.pattern}'",
                        layer="param",
                        policy=InterventionPolicy.REQUIRED,
                    )
            else:
                # Scan all param values
                for _key, val in params.items():
                    if self._match_value(str(val), rule):
                        return InterventionResult(
                            allowed=False,
                            reason=rule.reason or f"Param value matched pattern '{rule.pattern}'",
                            layer="param",
                            policy=InterventionPolicy.REQUIRED,
                        )
        return None

    def _match_value(self, value: str, rule: InterventionRule) -> bool:
        """Check if a string matches a rule's pattern using its match mode."""
        if not rule.pattern:
            return False
        if rule.match_mode == MatchMode.EXACT:
            return value == rule.pattern
        if rule.match_mode == MatchMode.PREFIX:
            return value.startswith(rule.pattern)
        if rule.match_mode == MatchMode.WILDCARD:
            return fnmatch.fnmatch(value, rule.pattern)
        if rule.match_mode == MatchMode.REGEX:
            compiled = self._compiled.get(rule.pattern)
            if compiled:
                return bool(compiled.search(value))
            # Fallback if compilation failed earlier
            try:
                return bool(re.search(rule.pattern, value, re.IGNORECASE))
            except re.error:
                return False
        return False
