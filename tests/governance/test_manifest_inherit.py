"""Tests for Agent YAML Inheritance."""
from src.governance.manifest_inherit import (
    deep_merge, ManifestInheritanceResolver,
)


def test_deep_merge_simple():
    base = {"a": 1, "b": 2}
    override = {"b": 3, "c": 4}
    result = deep_merge(base, override)
    assert result == {"a": 1, "b": 3, "c": 4}


def test_deep_merge_nested():
    base = {"policy": {"allowed": ["Read"], "denied": ["Bash"]}}
    override = {"policy": {"allowed": ["Read", "Write"]}}
    result = deep_merge(base, override)
    assert result["policy"]["allowed"] == ["Read", "Write"]
    assert result["policy"]["denied"] == ["Bash"]  # preserved


def test_deep_merge_no_mutation():
    base = {"a": {"b": 1}}
    override = {"a": {"c": 2}}
    result = deep_merge(base, override)
    assert "c" not in base["a"]  # base unchanged


def test_resolve_no_extends():
    resolver = ManifestInheritanceResolver()
    manifest = {"key": "engineering", "model": "opus"}
    result = resolver.resolve(manifest)
    assert result == {"key": "engineering", "model": "opus"}


def test_resolve_single_inheritance():
    resolver = ManifestInheritanceResolver()
    resolver.register_base("default", {
        "model": "claude-sonnet-4-6",
        "max_turns": 25,
        "timeout_s": 300,
        "policy": {"allowed_tools": ["Read", "Glob"]},
    })
    manifest = {
        "key": "security",
        "extends": "default",
        "max_turns": 15,  # override
        "policy": {"allowed_tools": ["Read", "Glob", "Bash"]},  # override
    }
    result = resolver.resolve(manifest)
    assert result["model"] == "claude-sonnet-4-6"  # inherited
    assert result["max_turns"] == 15  # overridden
    assert result["timeout_s"] == 300  # inherited
    assert "Bash" in result["policy"]["allowed_tools"]  # overridden
    assert "extends" not in result  # removed


def test_resolve_multi_level():
    resolver = ManifestInheritanceResolver()
    resolver.register_base("root", {"model": "haiku", "timeout_s": 60})
    resolver.register_base("standard", {"extends": "root", "timeout_s": 300, "max_turns": 25})
    manifest = {"key": "engineering", "extends": "standard", "max_turns": 40}
    result = resolver.resolve(manifest)
    assert result["model"] == "haiku"  # from root
    assert result["timeout_s"] == 300  # from standard
    assert result["max_turns"] == 40  # overridden


def test_resolve_missing_base():
    resolver = ManifestInheritanceResolver()
    manifest = {"key": "test", "extends": "nonexistent"}
    result = resolver.resolve(manifest)
    assert result["key"] == "test"  # still works, just no inheritance


def test_resolve_cycle_detection():
    resolver = ManifestInheritanceResolver()
    resolver.register_base("a", {"extends": "b", "x": 1})
    resolver.register_base("b", {"extends": "a", "y": 2})
    manifest = {"key": "test", "extends": "a"}
    result = resolver.resolve(manifest)  # should not infinite loop
    assert result["key"] == "test"


def test_get_bases():
    resolver = ManifestInheritanceResolver()
    resolver.register_base("default", {})
    resolver.register_base("strict", {})
    assert set(resolver.get_bases()) == {"default", "strict"}
