"""Tests for 16-Event Lifecycle Hooks (R38: Inspect AI steal)."""

import pytest
from src.core.lifecycle_hooks import (
    LifecycleHookRegistry,
    HOOK_POINTS,
    LimitExceededError,
    HookEntry,
    _ALIASES,
)


# ── Basic Registration & Firing ──

def test_register_and_fire():
    reg = LifecycleHookRegistry()
    called = []
    reg.register("on_pre_llm", lambda **kw: called.append(kw), name="test")
    reg.fire("on_pre_llm", model="test-model", prompt="hello")
    assert len(called) == 1
    assert called[0]["model"] == "test-model"


def test_fire_empty_point():
    reg = LifecycleHookRegistry()
    results = reg.fire("on_post_llm", cost=0.01)
    assert results == []


def test_multiple_hooks_same_point():
    reg = LifecycleHookRegistry()
    calls = []
    reg.register("on_task_start", lambda **kw: calls.append("a"), name="hook_a")
    reg.register("on_task_start", lambda **kw: calls.append("b"), name="hook_b")
    reg.fire("on_task_start", task_id=1)
    assert calls == ["a", "b"]


# ── Fault Isolation ──

def test_failing_hook_doesnt_block():
    reg = LifecycleHookRegistry()
    calls = []
    reg.register("on_pre_llm", lambda **kw: 1 / 0, name="bad_hook")
    reg.register("on_pre_llm", lambda **kw: calls.append("ok"), name="good_hook")
    reg.fire("on_pre_llm", model="test")
    assert calls == ["ok"]
    assert reg._errors == 1


def test_limit_exceeded_pierces_isolation():
    """LimitExceededError is the ONLY exception that propagates."""
    reg = LifecycleHookRegistry()

    def cost_guard(**kw):
        raise LimitExceededError("token_budget", current=10000, maximum=5000)

    reg.register("on_post_llm", cost_guard, name="cost_guard")
    with pytest.raises(LimitExceededError) as exc_info:
        reg.fire("on_post_llm", cost=0.50)
    assert exc_info.value.limit_type == "token_budget"
    assert exc_info.value.current == 10000
    assert exc_info.value.maximum == 5000


def test_limit_exceeded_after_good_hooks():
    """Hooks before the LimitExceededError still fire."""
    reg = LifecycleHookRegistry()
    calls = []
    reg.register("on_post_llm", lambda **kw: calls.append("ok"), name="good")
    reg.register("on_post_llm",
                 lambda **kw: (_ for _ in ()).throw(LimitExceededError("cost")),
                 name="guard")
    with pytest.raises(LimitExceededError):
        reg.fire("on_post_llm")
    assert calls == ["ok"]


def test_regular_exception_doesnt_propagate():
    """Non-LimitExceededError exceptions are swallowed."""
    reg = LifecycleHookRegistry()
    reg.register("on_error", lambda **kw: 1/0, name="bad")
    results = reg.fire("on_error", task_id=1)
    assert results == []
    assert reg._errors == 1


# ── Registration & Unregistration ──

def test_invalid_hook_point_raises():
    reg = LifecycleHookRegistry()
    with pytest.raises(ValueError):
        reg.register("totally_invalid", lambda **kw: None)


def test_unregister():
    reg = LifecycleHookRegistry()
    calls = []
    reg.register("on_error", lambda **kw: calls.append("x"), name="removeme")
    reg.unregister("on_error", "removeme")
    reg.fire("on_error", error="test")
    assert calls == []


def test_fire_returns_results():
    reg = LifecycleHookRegistry()
    reg.register("on_post_llm", lambda **kw: kw.get("cost", 0) * 2, name="doubler")
    reg.register("on_post_llm", lambda **kw: None, name="silent")
    results = reg.fire("on_post_llm", cost=5)
    assert results == [10]


# ── Priority ──

def test_priority_ordering():
    """Higher priority hooks fire first."""
    reg = LifecycleHookRegistry()
    order = []
    reg.register("on_attempt_start", lambda **kw: order.append("low"), name="low", priority=0)
    reg.register("on_attempt_start", lambda **kw: order.append("high"), name="high", priority=10)
    reg.register("on_attempt_start", lambda **kw: order.append("mid"), name="mid", priority=5)
    reg.fire("on_attempt_start", task_id=1)
    assert order == ["high", "mid", "low"]


def test_same_priority_preserves_order():
    """Same-priority hooks fire in registration order."""
    reg = LifecycleHookRegistry()
    order = []
    reg.register("on_rollout_start", lambda **kw: order.append("first"), name="first")
    reg.register("on_rollout_start", lambda **kw: order.append("second"), name="second")
    reg.fire("on_rollout_start", task_id=1)
    assert order == ["first", "second"]


# ── enabled() Self-Determination ──

def test_enabled_hook_fires():
    reg = LifecycleHookRegistry()
    calls = []
    reg.register("on_task_start", lambda **kw: calls.append("yes"),
                 name="enabled", enabled=lambda: True)
    reg.fire("on_task_start", task_id=1)
    assert calls == ["yes"]


def test_disabled_hook_skipped():
    reg = LifecycleHookRegistry()
    calls = []
    reg.register("on_task_start", lambda **kw: calls.append("no"),
                 name="disabled", enabled=lambda: False)
    reg.fire("on_task_start", task_id=1)
    assert calls == []


def test_broken_enabled_disables_hook():
    """If enabled() raises, treat as disabled — not as a fire() failure."""
    reg = LifecycleHookRegistry()
    calls = []
    reg.register("on_task_start", lambda **kw: calls.append("bad"),
                 name="broken_enabled", enabled=lambda: 1/0)
    reg.fire("on_task_start", task_id=1)
    assert calls == []
    assert reg._errors == 0  # enabled() failure != hook fire failure


# ── Backwards Compatibility Aliases ──

def test_alias_register_resolves():
    """Old hook names register under the new canonical name."""
    reg = LifecycleHookRegistry()
    calls = []
    reg.register("pre_llm_call", lambda **kw: calls.append("aliased"), name="old")
    reg.fire("on_pre_llm")
    assert calls == ["aliased"]


def test_alias_fire_resolves():
    """Firing with an old name resolves to the canonical name."""
    reg = LifecycleHookRegistry()
    calls = []
    reg.register("on_pre_llm", lambda **kw: calls.append("canonical"), name="new")
    reg.fire("pre_llm_call")
    assert calls == ["canonical"]


def test_all_aliases_resolve_to_valid_points():
    for old, new in _ALIASES.items():
        assert new in HOOK_POINTS, f"Alias {old} -> {new} is not a valid hook point"


# ── 16 Hook Points Validation ──

def test_exactly_16_hook_points():
    assert len(HOOK_POINTS) == 16


def test_all_hook_points_valid():
    """All HOOK_POINTS should be pre-registered in a fresh registry."""
    reg = LifecycleHookRegistry()
    for point in HOOK_POINTS:
        reg.fire(point)  # should not raise


def test_hook_points_by_layer():
    """Verify hook points exist for each architectural layer."""
    assert "on_batch_start" in HOOK_POINTS
    assert "on_batch_end" in HOOK_POINTS
    assert "on_task_start" in HOOK_POINTS
    assert "on_task_end" in HOOK_POINTS
    assert "on_rollout_start" in HOOK_POINTS
    assert "on_rollout_end" in HOOK_POINTS
    assert "on_attempt_start" in HOOK_POINTS
    assert "on_attempt_end" in HOOK_POINTS
    assert "on_context_build" in HOOK_POINTS
    assert "on_context_inject" in HOOK_POINTS
    assert "on_pre_llm" in HOOK_POINTS
    assert "on_post_llm" in HOOK_POINTS
    assert "on_review_start" in HOOK_POINTS
    assert "on_review_end" in HOOK_POINTS
    assert "on_error" in HOOK_POINTS
    assert "on_limit_exceeded" in HOOK_POINTS


# ── Stats & Introspection ──

def test_get_stats():
    reg = LifecycleHookRegistry()
    reg.register("on_pre_llm", lambda **kw: None, name="a")
    reg.fire("on_pre_llm")
    reg.fire("on_pre_llm")
    stats = reg.get_stats()
    assert stats["registered"]["on_pre_llm"] == 1
    assert stats["fire_counts"]["on_pre_llm"] == 2


def test_get_registered_single():
    reg = LifecycleHookRegistry()
    reg.register("on_task_start", lambda **kw: None, name="tracker")
    result = reg.get_registered("on_task_start")
    assert result == {"on_task_start": ["tracker"]}


def test_get_registered_all():
    reg = LifecycleHookRegistry()
    reg.register("on_pre_llm", lambda **kw: None, name="a")
    reg.register("on_error", lambda **kw: None, name="b")
    result = reg.get_registered()
    assert "on_pre_llm" in result
    assert "on_error" in result
    assert "on_post_llm" not in result  # empty = excluded


def test_clear():
    reg = LifecycleHookRegistry()
    reg.register("on_pre_llm", lambda **kw: None, name="x")
    reg.clear()
    assert reg.get_registered() == {}


# ── Singleton ──

def test_singleton():
    from src.core.lifecycle_hooks import get_lifecycle_hooks, reset_lifecycle_hooks
    reset_lifecycle_hooks()
    h1 = get_lifecycle_hooks()
    h2 = get_lifecycle_hooks()
    assert h1 is h2
    reset_lifecycle_hooks()


# ── HookEntry ──

def test_hook_entry_default_enabled():
    entry = HookEntry(name="test", callback=lambda **kw: None)
    assert entry.enabled is True


def test_hook_entry_enabled_callable():
    entry = HookEntry(name="test", callback=lambda **kw: None, _enabled=lambda: False)
    assert entry.enabled is False


# ── LimitExceededError ──

def test_limit_exceeded_error_fields():
    err = LimitExceededError("token_budget", current=10000, maximum=5000)
    assert err.limit_type == "token_budget"
    assert err.current == 10000
    assert err.maximum == 5000
    assert "token_budget" in str(err)
    assert "10000" in str(err)
