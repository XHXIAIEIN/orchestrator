"""Tests for Plugin Lifecycle Hooks."""

from src.core.lifecycle_hooks import LifecycleHookRegistry, HOOK_POINTS


def test_register_and_fire():
    reg = LifecycleHookRegistry()
    called = []
    reg.register("pre_llm_call", lambda **kw: called.append(kw), name="test")
    reg.fire("pre_llm_call", model="test-model", prompt="hello")
    assert len(called) == 1
    assert called[0]["model"] == "test-model"


def test_fire_empty_point():
    reg = LifecycleHookRegistry()
    results = reg.fire("post_llm_call", cost=0.01)
    assert results == []


def test_multiple_hooks_same_point():
    reg = LifecycleHookRegistry()
    calls = []
    reg.register("on_session_start", lambda **kw: calls.append("a"), name="hook_a")
    reg.register("on_session_start", lambda **kw: calls.append("b"), name="hook_b")
    reg.fire("on_session_start", task_id=1)
    assert calls == ["a", "b"]


def test_failing_hook_doesnt_block():
    reg = LifecycleHookRegistry()
    calls = []
    reg.register("pre_llm_call", lambda **kw: 1 / 0, name="bad_hook")
    reg.register("pre_llm_call", lambda **kw: calls.append("ok"), name="good_hook")
    reg.fire("pre_llm_call", model="test")
    assert calls == ["ok"]  # good hook still ran
    assert reg._errors == 1


def test_invalid_hook_point_raises():
    reg = LifecycleHookRegistry()
    try:
        reg.register("invalid_point", lambda: None)
        assert False, "Should raise ValueError"
    except ValueError:
        pass


def test_unregister():
    reg = LifecycleHookRegistry()
    calls = []
    reg.register("on_error", lambda **kw: calls.append("x"), name="removeme")
    reg.unregister("on_error", "removeme")
    reg.fire("on_error", error="test")
    assert calls == []


def test_fire_returns_results():
    reg = LifecycleHookRegistry()
    reg.register("post_llm_call", lambda **kw: kw.get("cost", 0) * 2, name="doubler")
    reg.register("post_llm_call", lambda **kw: None, name="silent")
    results = reg.fire("post_llm_call", cost=5)
    assert results == [10]  # only non-None


def test_get_stats():
    reg = LifecycleHookRegistry()
    reg.register("pre_llm_call", lambda **kw: None, name="a")
    reg.fire("pre_llm_call")
    reg.fire("pre_llm_call")
    stats = reg.get_stats()
    assert stats["registered"]["pre_llm_call"] == 1
    assert stats["fire_counts"]["pre_llm_call"] == 2


def test_get_registered():
    reg = LifecycleHookRegistry()
    reg.register("on_session_start", lambda **kw: None, name="tracker")
    result = reg.get_registered("on_session_start")
    assert result == {"on_session_start": ["tracker"]}


def test_all_hook_points_valid():
    """All HOOK_POINTS should be pre-registered."""
    reg = LifecycleHookRegistry()
    for point in HOOK_POINTS:
        reg.fire(point)  # should not raise


def test_get_registered_all():
    reg = LifecycleHookRegistry()
    reg.register("pre_llm_call", lambda **kw: None, name="a")
    reg.register("on_error", lambda **kw: None, name="b")
    result = reg.get_registered()
    assert "pre_llm_call" in result
    assert "on_error" in result
    assert "post_llm_call" not in result  # empty points excluded


def test_clear():
    reg = LifecycleHookRegistry()
    reg.register("pre_llm_call", lambda **kw: None, name="x")
    reg.clear()
    assert reg.get_registered() == {}


def test_singleton():
    from src.core.lifecycle_hooks import get_lifecycle_hooks

    h1 = get_lifecycle_hooks()
    h2 = get_lifecycle_hooks()
    assert h1 is h2
