"""Tests for Deferred Retrievers."""
from src.governance.deferred_retrieval import DeferredContext


def test_lazy_loading():
    calls = []
    ctx = DeferredContext()
    ctx.register("data", lambda: (calls.append(1), "result")[1])
    assert len(calls) == 0  # not loaded yet
    result = ctx.get("data")
    assert result == "result"
    assert len(calls) == 1  # loaded now


def test_cached_after_first_load():
    calls = []
    ctx = DeferredContext()
    ctx.register("data", lambda: (calls.append(1), "result")[1])
    ctx.get("data")
    ctx.get("data")
    ctx.get("data")
    assert len(calls) == 1  # only loaded once


def test_default_on_missing_key():
    ctx = DeferredContext()
    assert ctx.get("nonexistent", "fallback") == "fallback"


def test_default_on_error():
    ctx = DeferredContext()
    ctx.register("bad", lambda: 1/0)
    result = ctx.get("bad", "safe_default")
    assert result == "safe_default"


def test_has_without_loading():
    ctx = DeferredContext()
    ctx.register("data", lambda: "expensive")
    assert ctx.has("data")
    assert not ctx.is_loaded("data")


def test_preload():
    ctx = DeferredContext()
    ctx.register("a", lambda: "val_a")
    ctx.register("b", lambda: "val_b")
    ctx.preload("a")
    assert ctx.is_loaded("a")
    assert not ctx.is_loaded("b")


def test_materialize_all():
    ctx = DeferredContext()
    ctx.register("x", lambda: 1)
    ctx.register("y", lambda: 2)
    result = ctx.materialize_all()
    assert result == {"x": 1, "y": 2}


def test_unloaded_keys_tracked():
    ctx = DeferredContext()
    ctx.register("used", lambda: "a")
    ctx.register("unused", lambda: "b")
    ctx.get("used")
    assert "unused" in ctx.get_unloaded_keys()
    assert "used" in ctx.get_loaded_keys()


def test_stats():
    ctx = DeferredContext()
    ctx.register("a", lambda: 1)
    ctx.register("b", lambda: 2)
    ctx.get("a")
    stats = ctx.get_stats()
    assert stats["registered"] == 2
    assert stats["loaded"] == 1
    assert stats["skipped"] == 1


def test_override():
    ctx = DeferredContext()
    ctx.register("key", lambda: "old")
    ctx.register("key", lambda: "new", override=True)
    assert ctx.get("key") == "new"


def test_no_override_by_default():
    ctx = DeferredContext()
    ctx.register("key", lambda: "first")
    ctx.register("key", lambda: "second")  # ignored
    assert ctx.get("key") == "first"
