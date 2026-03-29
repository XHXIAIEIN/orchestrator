"""Tests for Generic Registry — stolen from ChatDev 2.0."""
import pytest
from src.core.registry import Registry


def test_register_and_resolve_target():
    r = Registry("test")
    r.register("my_thing", target=42)
    assert r.resolve("my_thing") == 42


def test_register_lazy_module():
    r = Registry("test")
    r.register("os_path_join", module_path="os.path", attr_name="join")
    assert "os_path_join" in r
    fn = r.resolve("os_path_join")
    import os.path
    assert fn is os.path.join


def test_register_with_loader():
    r = Registry("test")
    call_count = {"n": 0}
    def my_loader():
        call_count["n"] += 1
        return {"loaded": True}
    r.register("custom", loader=my_loader)
    result = r.resolve("custom")
    assert result == {"loaded": True}
    assert call_count["n"] == 1
    result2 = r.resolve("custom")
    assert result2 == {"loaded": True}
    assert call_count["n"] == 1


def test_register_metadata_only():
    r = Registry("test")
    r.register("info_only", metadata={"version": "1.0", "author": "test"})
    assert r.get_metadata("info_only") == {"version": "1.0", "author": "test"}
    assert r.resolve("info_only") is None


def test_duplicate_detection():
    r = Registry("test")
    r.register("dup", target=1)
    with pytest.raises(ValueError, match="already registered"):
        r.register("dup", target=2)


def test_override_allowed():
    r = Registry("test")
    r.register("item", target=1)
    r.register("item", target=2, override=True)
    assert r.resolve("item") == 2


def test_namespace_isolation():
    r1 = Registry("ns1")
    r2 = Registry("ns2")
    r1.register("shared_name", target="from_ns1")
    r2.register("shared_name", target="from_ns2")
    assert r1.resolve("shared_name") == "from_ns1"
    assert r2.resolve("shared_name") == "from_ns2"


def test_list_entries():
    r = Registry("test")
    r.register("a", target=1)
    r.register("b", target=2)
    r.register("c", metadata={"x": 1})
    assert set(r.list()) == {"a", "b", "c"}


def test_resolve_unknown_returns_none():
    r = Registry("test")
    assert r.resolve("nonexistent") is None


def test_contains():
    r = Registry("test")
    r.register("exists", target=True)
    assert "exists" in r
    assert "nope" not in r
