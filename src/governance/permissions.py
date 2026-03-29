"""3-Tier Plugin Permission Model — stolen from OpenAkita.

Classifies tools into permission tiers:
  - BASIC: Read-only operations (Read, Glob, Grep, LS)
  - ADVANCED: Mutation operations (Edit, Write, Bash, NotebookEdit)
  - SYSTEM: System-level operations (WebFetch, WebSearch, dangerous Bash)

Each department/agent has a maximum permission tier. Tool calls are
validated against the tier before execution.

Usage:
    checker = PermissionChecker()
    allowed = checker.check("engineering", "Bash", {"command": "rm -rf /"})
    # allowed.permitted = False, allowed.reason = "destructive command"
"""
import logging
import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

log = logging.getLogger(__name__)


class PermissionTier(IntEnum):
    BASIC = 1      # Read-only
    ADVANCED = 2   # Can mutate files
    SYSTEM = 3     # Can access network, system commands


# Tool → tier mapping
TOOL_TIERS: dict[str, PermissionTier] = {
    # Basic (read-only)
    "Read": PermissionTier.BASIC,
    "Glob": PermissionTier.BASIC,
    "Grep": PermissionTier.BASIC,
    "LS": PermissionTier.BASIC,
    "NotebookRead": PermissionTier.BASIC,
    # Advanced (mutation)
    "Edit": PermissionTier.ADVANCED,
    "Write": PermissionTier.ADVANCED,
    "Bash": PermissionTier.ADVANCED,
    "NotebookEdit": PermissionTier.ADVANCED,
    # System (network, external)
    "WebFetch": PermissionTier.SYSTEM,
    "WebSearch": PermissionTier.SYSTEM,
    "Agent": PermissionTier.SYSTEM,
}

# Dangerous command patterns (Bash-specific, always blocked unless SYSTEM tier)
_DANGEROUS_PATTERNS = [
    re.compile(r'\brm\s+-rf\s+/', re.I),
    re.compile(r'\bmkfs\b', re.I),
    re.compile(r'\bdd\s+if=', re.I),
    re.compile(r':\(\)\{\s*:\|:&\s*\};:', re.I),  # fork bomb
    re.compile(r'\bgit\s+push\s+--force\s+.*main', re.I),
    re.compile(r'\bdrop\s+database\b', re.I),
    re.compile(r'\btruncate\s+table\b', re.I),
]


@dataclass
class PermissionResult:
    """Result of a permission check."""
    permitted: bool
    tool: str
    tier_required: PermissionTier
    tier_granted: PermissionTier
    reason: str = ""


class PermissionChecker:
    """Validate tool access against permission tiers."""

    def __init__(self):
        self._dept_tiers: dict[str, PermissionTier] = {}
        self._overrides: dict[str, dict[str, bool]] = {}  # dept → {tool: allowed}

    def set_department_tier(self, department: str, tier: PermissionTier):
        """Set the maximum permission tier for a department."""
        self._dept_tiers[department] = tier
        log.debug(f"permissions: {department} → tier {tier.name}")

    def set_override(self, department: str, tool: str, allowed: bool):
        """Override a specific tool for a department (bypass tier check)."""
        if department not in self._overrides:
            self._overrides[department] = {}
        self._overrides[department][tool] = allowed

    def get_tier(self, department: str) -> PermissionTier:
        """Get the permission tier for a department. Default: ADVANCED."""
        return self._dept_tiers.get(department, PermissionTier.ADVANCED)

    def check(self, department: str, tool: str,
              tool_input: dict = None) -> PermissionResult:
        """Check if a department can use a tool.

        Args:
            department: Department key
            tool: Tool name (e.g. "Bash", "Read")
            tool_input: Optional tool input for content-level checks

        Returns:
            PermissionResult with permitted flag and reason.
        """
        dept_tier = self.get_tier(department)
        tool_tier = TOOL_TIERS.get(tool, PermissionTier.ADVANCED)

        # Check overrides first
        dept_overrides = self._overrides.get(department, {})
        if tool in dept_overrides:
            allowed = dept_overrides[tool]
            return PermissionResult(
                permitted=allowed,
                tool=tool,
                tier_required=tool_tier,
                tier_granted=dept_tier,
                reason=f"override: {'allowed' if allowed else 'denied'}",
            )

        # Tier check
        if tool_tier > dept_tier:
            return PermissionResult(
                permitted=False,
                tool=tool,
                tier_required=tool_tier,
                tier_granted=dept_tier,
                reason=f"{tool} requires {tool_tier.name}, department has {dept_tier.name}",
            )

        # Content-level check for Bash commands
        if tool == "Bash" and tool_input:
            command = tool_input.get("command", "")
            dangerous = self._check_dangerous(command)
            if dangerous:
                return PermissionResult(
                    permitted=False,
                    tool=tool,
                    tier_required=PermissionTier.SYSTEM,
                    tier_granted=dept_tier,
                    reason=f"dangerous command pattern: {dangerous}",
                )

        return PermissionResult(
            permitted=True,
            tool=tool,
            tier_required=tool_tier,
            tier_granted=dept_tier,
        )

    def _check_dangerous(self, command: str) -> str:
        """Check if a bash command matches dangerous patterns."""
        for pattern in _DANGEROUS_PATTERNS:
            if pattern.search(command):
                return pattern.pattern
        return ""

    def filter_tools(self, department: str, tools: list[str]) -> list[str]:
        """Filter a tool list to only those permitted for a department."""
        return [t for t in tools if self.check(department, t).permitted]

    def get_stats(self) -> dict:
        return {
            "departments": {d: t.name for d, t in self._dept_tiers.items()},
            "overrides": {d: list(o.keys()) for d, o in self._overrides.items() if o},
        }


# Singleton
_checker: Optional[PermissionChecker] = None


def get_permission_checker() -> PermissionChecker:
    global _checker
    if _checker is None:
        _checker = PermissionChecker()
    return _checker
