"""Tool policy engine with deny-wins semantics.

Deny rules always override allow rules. Supports glob matching for tool names.
Supports sub-agent depth limits to prevent infinite delegation.

Ported from OpenFang's insight: simple allowlists are insufficient.
A deny rule must ALWAYS win, regardless of what allow rules say.
"""

import fnmatch
from dataclasses import dataclass, field


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
