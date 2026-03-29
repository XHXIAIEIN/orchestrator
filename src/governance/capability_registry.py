"""Unified Capability Pipeline — stolen from OpenAkita.

Central registry for all capabilities (tools, integrations, skills).
Departments declare what capabilities they NEED, the registry resolves
which tools satisfy those needs.

Benefits:
- Add a new tool once, all departments that need its capability get it
- Remove/disable a tool centrally without editing every manifest
- Audit which departments use which tools

Usage:
    registry = CapabilityRegistry()
    registry.register_tool("Bash", capabilities=["shell", "execute", "system"])
    registry.register_tool("Read", capabilities=["file_read", "inspect"])
    registry.register_tool("WebFetch", capabilities=["network", "http"])

    # Department requests capabilities
    tools = registry.resolve(["file_read", "shell"])
    # → ["Read", "Bash"]
"""
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class ToolEntry:
    """A registered tool with its capabilities."""
    name: str
    capabilities: list[str] = field(default_factory=list)
    enabled: bool = True
    description: str = ""
    tier: str = "advanced"  # basic, advanced, system


class CapabilityRegistry:
    """Central registry mapping capabilities to tools."""

    def __init__(self):
        self._tools: dict[str, ToolEntry] = {}
        self._capability_index: dict[str, list[str]] = {}  # capability → [tool_names]

    def register_tool(self, name: str, capabilities: list[str] = None,
                      description: str = "", tier: str = "advanced"):
        """Register a tool with its capabilities."""
        entry = ToolEntry(
            name=name,
            capabilities=capabilities or [],
            description=description,
            tier=tier,
        )
        self._tools[name] = entry

        # Update capability index
        for cap in entry.capabilities:
            if cap not in self._capability_index:
                self._capability_index[cap] = []
            if name not in self._capability_index[cap]:
                self._capability_index[cap].append(name)

        log.debug(f"capability_registry: registered {name} with {capabilities}")

    def disable_tool(self, name: str):
        """Disable a tool globally."""
        if name in self._tools:
            self._tools[name].enabled = False
            log.info(f"capability_registry: disabled {name}")

    def enable_tool(self, name: str):
        """Re-enable a tool."""
        if name in self._tools:
            self._tools[name].enabled = True

    def resolve(self, capabilities: list[str],
                max_tier: str = "system") -> list[str]:
        """Resolve capability requirements to a list of enabled tools.

        Args:
            capabilities: List of required capabilities.
            max_tier: Maximum tool tier to include.

        Returns:
            List of tool names that satisfy the requirements.
        """
        tier_order = {"basic": 1, "advanced": 2, "system": 3}
        max_level = tier_order.get(max_tier, 3)

        tools = set()
        for cap in capabilities:
            tool_names = self._capability_index.get(cap, [])
            for name in tool_names:
                entry = self._tools.get(name)
                if entry and entry.enabled:
                    tool_level = tier_order.get(entry.tier, 2)
                    if tool_level <= max_level:
                        tools.add(name)

        return sorted(tools)

    def get_capabilities_for_tool(self, name: str) -> list[str]:
        """Get all capabilities provided by a tool."""
        entry = self._tools.get(name)
        return list(entry.capabilities) if entry else []

    def get_tools_for_capability(self, capability: str) -> list[str]:
        """Get all tools that provide a capability."""
        return [
            name for name in self._capability_index.get(capability, [])
            if self._tools.get(name, ToolEntry(name="")).enabled
        ]

    def list_all_capabilities(self) -> list[str]:
        """List all registered capabilities."""
        return sorted(self._capability_index.keys())

    def list_all_tools(self) -> list[dict]:
        """List all registered tools with their status."""
        return [
            {"name": t.name, "capabilities": t.capabilities,
             "enabled": t.enabled, "tier": t.tier}
            for t in self._tools.values()
        ]

    def audit(self, department_capabilities: dict[str, list[str]]) -> dict:
        """Audit which tools each department would get.

        Args:
            department_capabilities: {dept_name: [required_capabilities]}

        Returns:
            {dept_name: [resolved_tools]}
        """
        result = {}
        for dept, caps in department_capabilities.items():
            result[dept] = self.resolve(caps)
        return result

    def get_stats(self) -> dict:
        enabled = sum(1 for t in self._tools.values() if t.enabled)
        return {
            "total_tools": len(self._tools),
            "enabled_tools": enabled,
            "total_capabilities": len(self._capability_index),
        }


def build_default_registry() -> CapabilityRegistry:
    """Build registry with standard Orchestrator tools."""
    reg = CapabilityRegistry()
    reg.register_tool("Read", ["file_read", "inspect"], tier="basic")
    reg.register_tool("Glob", ["file_search", "inspect"], tier="basic")
    reg.register_tool("Grep", ["content_search", "inspect"], tier="basic")
    reg.register_tool("LS", ["directory_list", "inspect"], tier="basic")
    reg.register_tool("Edit", ["file_write", "modify"], tier="advanced")
    reg.register_tool("Write", ["file_write", "create"], tier="advanced")
    reg.register_tool("Bash", ["shell", "execute", "system"], tier="advanced")
    reg.register_tool("NotebookEdit", ["notebook", "modify"], tier="advanced")
    reg.register_tool("WebFetch", ["network", "http", "download"], tier="system")
    reg.register_tool("WebSearch", ["network", "search"], tier="system")
    reg.register_tool("Agent", ["delegation", "parallel"], tier="system")
    return reg
