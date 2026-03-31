"""Tool policy engine with deny-wins semantics.

Deny rules always override allow rules. Supports glob matching for tool names.
Supports sub-agent depth limits to prevent infinite delegation.

Ported from OpenFang's insight: simple allowlists are insufficient.
A deny rule must ALWAYS win, regardless of what allow rules say.

Enhanced with FunctionCatalog (ChatDev 2.0, Round 13): JSON Schema
introspection for validating tool parameters before execution.
"""

import fnmatch
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

# ── FunctionCatalog (stolen from ChatDev 2.0, Round 13) ──
# JSON Schema introspection for tool parameter validation.
try:
    from src.core.function_catalog import introspect_function
except ImportError:
    introspect_function = None

_log = logging.getLogger(__name__)


@dataclass
class ToolPolicy:
    """Evaluate tool access requests against allow/deny rules.

    Rules:
    1. Explicit deny ALWAYS wins over explicit allow
    2. Tool names support glob patterns (e.g., "browser_*", "file_*")
    3. No matching rule + allowlist configured → default deny (closed by default)
    4. No matching rule + no allowlist → default allow (open by default)
    5. Sub-agent depth limit prevents runaway delegation
    """

    allowed: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)
    max_depth: int = 3

    @classmethod
    def from_blueprint(cls, blueprint_dict: dict) -> "ToolPolicy":
        """Create from a department blueprint.yaml policy section."""
        return cls(
            allowed=blueprint_dict.get("allowed_tools", []),
            denied=blueprint_dict.get("denied_tools", []),
            max_depth=blueprint_dict.get("max_agent_depth", 3),
        )

    @classmethod
    def from_policy(cls, policy: "Policy", max_depth: int = 3) -> "ToolPolicy":  # noqa: F821
        """Create from an existing Policy dataclass (blueprint.py)."""
        return cls(
            allowed=list(policy.allowed_tools),
            denied=list(policy.denied_tools),
            max_depth=max_depth,
        )

    # ── Core evaluation ──────────────────────────────────────────

    def is_allowed(self, tool_name: str, depth: int = 0) -> tuple[bool, str]:
        """Check if a tool is allowed.

        Returns (allowed: bool, reason: str).
        """
        # Depth limit — bail early
        if depth > self.max_depth:
            return False, f"agent depth {depth} exceeds limit {self.max_depth}"

        # Deny-wins: check deny list FIRST — one match and we're done
        for pattern in self.denied:
            if fnmatch.fnmatch(tool_name, pattern):
                return False, f"denied by pattern '{pattern}'"

        # If no allowlist configured, open by default
        if not self.allowed:
            return True, "no allowlist configured (open by default)"

        # Check allow list — need at least one match
        for pattern in self.allowed:
            if fnmatch.fnmatch(tool_name, pattern):
                return True, f"allowed by pattern '{pattern}'"

        # Allowlist exists but no match → deny
        return False, "not in allowlist"

    # ── Batch helpers ────────────────────────────────────────────

    def filter_tools(self, tool_names: list[str], depth: int = 0) -> list[str]:
        """Filter a list of tools, returning only allowed ones."""
        return [t for t in tool_names if self.is_allowed(t, depth)[0]]

    def check_batch(
        self, tool_names: list[str], depth: int = 0
    ) -> dict[str, tuple[bool, str]]:
        """Check multiple tools, return per-tool results."""
        return {t: self.is_allowed(t, depth) for t in tool_names}

    # ── Parameter Validation (ChatDev 2.0, Round 13) ──────────────

    def validate_params(
        self, tool_fn: Callable, params: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Validate tool parameters against the function's JSON Schema.

        Uses FunctionCatalog introspection to extract the schema from the
        function signature and type hints, then checks:
        1. All required parameters are present
        2. Parameter types match (basic type checking)

        Returns (valid: bool, errors: list[str]).
        If FunctionCatalog is unavailable, always returns (True, []).
        """
        if introspect_function is None:
            return True, []

        try:
            spec = introspect_function(tool_fn)
        except Exception as e:
            _log.debug(f"ToolPolicy: introspection failed for {tool_fn}: {e}")
            return True, []  # Fail open — don't block on introspection errors

        schema = spec.get("json_schema", {})
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        errors: list[str] = []

        # Check required params
        for param_name in required:
            if param_name not in params:
                errors.append(f"missing required parameter: '{param_name}'")

        # Basic type validation
        _JSON_TYPE_MAP = {
            "string": str, "integer": int, "number": (int, float),
            "boolean": bool, "array": list, "object": dict,
        }
        for param_name, value in params.items():
            if param_name not in properties:
                continue  # Extra params are OK (may be **kwargs)
            expected_type_str = properties[param_name].get("type", "")
            expected_type = _JSON_TYPE_MAP.get(expected_type_str)
            if expected_type and not isinstance(value, expected_type):
                errors.append(
                    f"parameter '{param_name}': expected {expected_type_str}, "
                    f"got {type(value).__name__}"
                )

        return len(errors) == 0, errors

    def introspect_tool(self, tool_fn: Callable) -> dict[str, Any] | None:
        """Introspect a tool function and return its full schema.

        Returns None if FunctionCatalog is unavailable.
        """
        if introspect_function is None:
            return None
        try:
            return introspect_function(tool_fn)
        except Exception as e:
            _log.debug(f"ToolPolicy: introspection failed: {e}")
            return None
