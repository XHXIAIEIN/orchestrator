"""Tests for Rule Dependency Resolver."""
from src.gateway.rule_dependencies import RuleDependencyResolver


def test_basic_rule_active():
    resolver = RuleDependencyResolver()
    resolver.add_rule("code_fix", tags=["engineering"])
    assert resolver.is_active("code_fix")


def test_tag_deactivation():
    resolver = RuleDependencyResolver()
    resolver.add_rule("code_fix", tags=["engineering"])
    resolver.deactivate_tag("engineering")
    assert not resolver.is_active("code_fix")


def test_tag_reactivation():
    resolver = RuleDependencyResolver()
    resolver.add_rule("code_fix", tags=["engineering"])
    resolver.deactivate_tag("engineering")
    resolver.activate_tag("engineering")
    assert resolver.is_active("code_fix")


def test_multiple_tags_any_active():
    resolver = RuleDependencyResolver()
    resolver.add_rule("deploy", tags=["operations", "engineering"])
    resolver.deactivate_tag("operations")
    assert resolver.is_active("deploy")  # engineering still active


def test_requires_dependency():
    resolver = RuleDependencyResolver()
    resolver.add_rule("code_fix", tags=["engineering"])
    resolver.add_rule("code_review", tags=["quality"], requires=["code_fix"])
    assert resolver.is_active("code_review")
    resolver.deactivate_tag("engineering")
    assert not resolver.is_active("code_fix")
    assert not resolver.is_active("code_review")  # cascade


def test_requires_any():
    resolver = RuleDependencyResolver()
    resolver.add_rule("a", tags=["t1"])
    resolver.add_rule("b", tags=["t2"])
    resolver.add_rule("c", tags=["t3"], requires_any=["a", "b"])
    assert resolver.is_active("c")
    resolver.deactivate_tag("t1")
    assert resolver.is_active("c")  # b still active
    resolver.deactivate_tag("t2")
    assert not resolver.is_active("c")  # both deps inactive


def test_manual_disable():
    resolver = RuleDependencyResolver()
    resolver.add_rule("code_fix", tags=["engineering"])
    resolver.disable_rule("code_fix")
    assert not resolver.is_active("code_fix")


def test_cascade_impact_preview():
    resolver = RuleDependencyResolver()
    resolver.add_rule("code_fix", tags=["engineering"])
    resolver.add_rule("code_review", tags=["quality"], requires=["code_fix"])
    impact = resolver.get_cascade_impact("engineering")
    assert "code_fix" in impact
    assert "code_review" in impact
    # Tag should still be active (preview only)
    assert resolver.is_active("code_fix")


def test_cycle_detection():
    resolver = RuleDependencyResolver()
    resolver.add_rule("a", tags=["t1"], requires=["b"])
    resolver.add_rule("b", tags=["t1"], requires=["a"])
    # Should not infinite loop -- cycles treated as inactive
    assert not resolver.is_active("a")


def test_get_active_rules():
    resolver = RuleDependencyResolver()
    resolver.add_rule("a", tags=["t1"])
    resolver.add_rule("b", tags=["t2"])
    resolver.deactivate_tag("t2")
    active = resolver.get_active_rules()
    assert "a" in active
    assert "b" not in active


def test_nonexistent_rule():
    resolver = RuleDependencyResolver()
    assert not resolver.is_active("nonexistent")


def test_no_tags_always_active():
    resolver = RuleDependencyResolver()
    resolver.add_rule("always_on")
    assert resolver.is_active("always_on")
