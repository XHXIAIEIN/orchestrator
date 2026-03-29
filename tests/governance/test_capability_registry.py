"""Tests for Unified Capability Pipeline."""
from src.governance.capability_registry import (
    CapabilityRegistry, build_default_registry,
)


def test_register_and_resolve():
    reg = CapabilityRegistry()
    reg.register_tool("Read", ["file_read"])
    reg.register_tool("Bash", ["shell", "execute"])
    tools = reg.resolve(["file_read", "shell"])
    assert "Read" in tools
    assert "Bash" in tools


def test_resolve_unknown_capability():
    reg = CapabilityRegistry()
    tools = reg.resolve(["nonexistent"])
    assert tools == []


def test_disabled_tool_excluded():
    reg = CapabilityRegistry()
    reg.register_tool("Bash", ["shell"])
    reg.disable_tool("Bash")
    tools = reg.resolve(["shell"])
    assert "Bash" not in tools


def test_enable_tool():
    reg = CapabilityRegistry()
    reg.register_tool("Bash", ["shell"])
    reg.disable_tool("Bash")
    reg.enable_tool("Bash")
    tools = reg.resolve(["shell"])
    assert "Bash" in tools


def test_tier_filtering():
    reg = CapabilityRegistry()
    reg.register_tool("Read", ["inspect"], tier="basic")
    reg.register_tool("WebFetch", ["network"], tier="system")
    # Basic tier should not include system tools
    tools = reg.resolve(["inspect", "network"], max_tier="basic")
    assert "Read" in tools
    assert "WebFetch" not in tools


def test_get_capabilities_for_tool():
    reg = CapabilityRegistry()
    reg.register_tool("Bash", ["shell", "execute", "system"])
    caps = reg.get_capabilities_for_tool("Bash")
    assert "shell" in caps
    assert "execute" in caps


def test_get_tools_for_capability():
    reg = CapabilityRegistry()
    reg.register_tool("Read", ["inspect"])
    reg.register_tool("Glob", ["inspect"])
    tools = reg.get_tools_for_capability("inspect")
    assert len(tools) == 2


def test_audit():
    reg = CapabilityRegistry()
    reg.register_tool("Read", ["file_read"], tier="basic")
    reg.register_tool("Bash", ["shell"], tier="advanced")
    reg.register_tool("WebFetch", ["network"], tier="system")
    result = reg.audit({
        "engineering": ["file_read", "shell"],
        "readonly": ["file_read"],
    })
    assert "Bash" in result["engineering"]
    assert "Bash" not in result["readonly"]


def test_default_registry():
    reg = build_default_registry()
    stats = reg.get_stats()
    assert stats["total_tools"] >= 10
    assert stats["total_capabilities"] >= 5


def test_list_all():
    reg = CapabilityRegistry()
    reg.register_tool("A", ["cap1", "cap2"])
    reg.register_tool("B", ["cap2", "cap3"])
    assert "cap1" in reg.list_all_capabilities()
    tools = reg.list_all_tools()
    assert len(tools) == 2


def test_stats():
    reg = CapabilityRegistry()
    reg.register_tool("A", ["x"])
    reg.register_tool("B", ["y"])
    reg.disable_tool("B")
    stats = reg.get_stats()
    assert stats["total_tools"] == 2
    assert stats["enabled_tools"] == 1
