"""Tests for 3-Tier Plugin Permission Model."""
from src.governance.permissions import (
    PermissionChecker, PermissionTier, TOOL_TIERS,
)


def test_basic_tier_allows_read():
    pc = PermissionChecker()
    pc.set_department_tier("readonly_dept", PermissionTier.BASIC)
    result = pc.check("readonly_dept", "Read")
    assert result.permitted is True


def test_basic_tier_blocks_write():
    pc = PermissionChecker()
    pc.set_department_tier("readonly_dept", PermissionTier.BASIC)
    result = pc.check("readonly_dept", "Write")
    assert result.permitted is False
    assert "ADVANCED" in result.reason


def test_advanced_tier_allows_bash():
    pc = PermissionChecker()
    pc.set_department_tier("engineering", PermissionTier.ADVANCED)
    result = pc.check("engineering", "Bash")
    assert result.permitted is True


def test_advanced_tier_blocks_webfetch():
    pc = PermissionChecker()
    pc.set_department_tier("engineering", PermissionTier.ADVANCED)
    result = pc.check("engineering", "WebFetch")
    assert result.permitted is False


def test_system_tier_allows_everything():
    pc = PermissionChecker()
    pc.set_department_tier("admin", PermissionTier.SYSTEM)
    for tool in TOOL_TIERS:
        result = pc.check("admin", tool)
        assert result.permitted is True, f"{tool} should be allowed for SYSTEM"


def test_dangerous_bash_blocked():
    pc = PermissionChecker()
    pc.set_department_tier("engineering", PermissionTier.ADVANCED)
    result = pc.check("engineering", "Bash", {"command": "rm -rf /"})
    assert result.permitted is False
    assert "dangerous" in result.reason


def test_safe_bash_allowed():
    pc = PermissionChecker()
    pc.set_department_tier("engineering", PermissionTier.ADVANCED)
    result = pc.check("engineering", "Bash", {"command": "ls -la"})
    assert result.permitted is True


def test_override_allows_blocked_tool():
    pc = PermissionChecker()
    pc.set_department_tier("readonly_dept", PermissionTier.BASIC)
    pc.set_override("readonly_dept", "Bash", True)
    result = pc.check("readonly_dept", "Bash")
    assert result.permitted is True
    assert "override" in result.reason


def test_override_denies_allowed_tool():
    pc = PermissionChecker()
    pc.set_department_tier("engineering", PermissionTier.ADVANCED)
    pc.set_override("engineering", "Edit", False)
    result = pc.check("engineering", "Edit")
    assert result.permitted is False


def test_filter_tools():
    pc = PermissionChecker()
    pc.set_department_tier("basic_dept", PermissionTier.BASIC)
    tools = ["Read", "Glob", "Edit", "Bash", "WebFetch"]
    filtered = pc.filter_tools("basic_dept", tools)
    assert filtered == ["Read", "Glob"]


def test_default_tier_is_advanced():
    pc = PermissionChecker()
    tier = pc.get_tier("unknown_dept")
    assert tier == PermissionTier.ADVANCED


def test_unknown_tool_defaults_advanced():
    pc = PermissionChecker()
    pc.set_department_tier("basic_dept", PermissionTier.BASIC)
    result = pc.check("basic_dept", "SomeNewTool")
    assert result.permitted is False  # unknown tool = ADVANCED, basic can't use


def test_force_push_main_blocked():
    pc = PermissionChecker()
    pc.set_department_tier("engineering", PermissionTier.ADVANCED)
    result = pc.check("engineering", "Bash", {"command": "git push --force origin main"})
    assert result.permitted is False


def test_get_stats():
    pc = PermissionChecker()
    pc.set_department_tier("eng", PermissionTier.ADVANCED)
    pc.set_department_tier("ops", PermissionTier.SYSTEM)
    pc.set_override("eng", "WebFetch", True)
    stats = pc.get_stats()
    assert stats["departments"]["eng"] == "ADVANCED"
    assert stats["departments"]["ops"] == "SYSTEM"
    assert "WebFetch" in stats["overrides"]["eng"]


def test_singleton():
    from src.governance.permissions import get_permission_checker
    c1 = get_permission_checker()
    c2 = get_permission_checker()
    assert c1 is c2
