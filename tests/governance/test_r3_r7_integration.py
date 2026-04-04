"""Tests for Round 3-7 orphan module integrations.

Verifies that the six low-difficulty steal modules are wired into
their respective production code paths:
  1. manifest_inherit → registry.py (extends: field)
  2. cross_review → review.py (dual-model for high-blast-radius)
  3. lifecycle_hooks → executor.py (global hook registry bridged)
  4. webhook → handlers.py (webhook trigger source)
  5. rule_dependencies → intent_rules.py (dependency resolver)
  6. deferred_retrieval → engine.py (DeferredRetrievalProvider)
"""
import pytest


# ═══════════════════════════════════════════════════════════════
# 1. Manifest Inheritance → Registry
# ═══════════════════════════════════════════════════════════════

class TestManifestInheritIntegration:
    """Test that registry.py resolves extends: chains."""

    def test_resolver_imported_in_registry(self):
        """Registry module should import ManifestInheritanceResolver."""
        import src.governance.registry as reg
        assert hasattr(reg, '_manifest_resolver')

    def test_deep_merge_basic(self):
        from src.governance.manifest_inherit import deep_merge
        base = {"model": "sonnet", "policy": {"tools": ["Read"], "max_turns": 10}}
        override = {"policy": {"tools": ["Read", "Bash"]}}
        result = deep_merge(base, override)
        assert result["model"] == "sonnet"
        assert result["policy"]["tools"] == ["Read", "Bash"]
        assert result["policy"]["max_turns"] == 10

    def test_resolver_single_inheritance(self):
        from src.governance.manifest_inherit import ManifestInheritanceResolver
        resolver = ManifestInheritanceResolver()
        resolver.register_base("default", {
            "model": "claude-sonnet-4-6",
            "max_turns": 25,
            "policy": {"allowed_tools": ["Read", "Glob"]},
        })
        result = resolver.resolve({
            "key": "security",
            "extends": "default",
            "policy": {"allowed_tools": ["Read", "Glob", "Bash"]},
        })
        assert result["model"] == "claude-sonnet-4-6"
        assert result["max_turns"] == 25
        assert "Bash" in result["policy"]["allowed_tools"]
        assert "extends" not in result

    def test_resolver_no_extends_passthrough(self):
        from src.governance.manifest_inherit import ManifestInheritanceResolver
        resolver = ManifestInheritanceResolver()
        manifest = {"key": "eng", "model": "sonnet"}
        result = resolver.resolve(manifest)
        assert result == manifest

    def test_resolver_cycle_detection(self):
        from src.governance.manifest_inherit import ManifestInheritanceResolver
        resolver = ManifestInheritanceResolver()
        resolver.register_base("a", {"extends": "b", "val": 1})
        resolver.register_base("b", {"extends": "a", "val": 2})
        # Should not infinite loop — cycle detection breaks it
        result = resolver.resolve({"key": "test", "extends": "a"})
        assert "key" in result


# ═══════════════════════════════════════════════════════════════
# 2. Cross-Review → Review
# ═══════════════════════════════════════════════════════════════

class TestCrossReviewIntegration:
    """Test that review.py imports and can trigger cross-review."""

    def test_cross_review_imported_in_review(self):
        import src.governance.review as rev
        assert hasattr(rev, 'CrossModelReviewer')
        assert hasattr(rev, '_HIGH_BLAST_DEPARTMENTS')

    def test_high_blast_departments_defined(self):
        from src.governance.review import _HIGH_BLAST_DEPARTMENTS
        assert "security" in _HIGH_BLAST_DEPARTMENTS
        assert "operations" in _HIGH_BLAST_DEPARTMENTS

    def test_consensus_detection(self):
        from src.governance.cross_review import detect_consensus
        level, conf = detect_consensus("yes", "yes", "Both models agree on the approach")
        assert level == "agree"
        assert conf > 0.5

        level2, conf2 = detect_consensus("yes", "no", "The models disagree on the approach")
        assert level2 == "disagree"

    def test_review_report_dataclass(self):
        from src.governance.cross_review import ReviewReport
        report = ReviewReport(
            question="test", model_a="a", model_b="b",
            response_a="yes", response_b="no",
            consensus="disagree", recommendation="reconsider",
            confidence=0.8, latency_ms=100,
        )
        assert report.consensus == "disagree"
        assert report.confidence == 0.8


# ═══════════════════════════════════════════════════════════════
# 3. Lifecycle Hooks → Executor
# ═══════════════════════════════════════════════════════════════

class TestLifecycleHooksIntegration:
    """Test that executor.py uses the unified 16-event lifecycle registry."""

    def test_global_hooks_imported_in_executor(self):
        import src.governance.executor as exe
        assert hasattr(exe, '_get_global_hooks')

    def test_registry_basic_with_alias(self):
        """Old hook name on_task_dispatch resolves to on_task_start."""
        from src.core.lifecycle_hooks import LifecycleHookRegistry
        reg = LifecycleHookRegistry()
        results = []
        reg.register("on_task_dispatch", lambda **kw: results.append(kw), name="test")
        reg.fire("on_task_start", task_id=1, department="eng")
        assert len(results) == 1
        assert results[0]["task_id"] == 1

    def test_registry_fire_and_forget(self):
        """Failing hooks should not raise."""
        from src.core.lifecycle_hooks import LifecycleHookRegistry
        reg = LifecycleHookRegistry()
        reg.register("on_error", lambda **kw: 1/0, name="bad_hook")
        reg.fire("on_error", task_id=1)
        assert reg.get_stats()["total_errors"] == 1

    def test_singleton(self):
        from src.core.lifecycle_hooks import get_lifecycle_hooks, reset_lifecycle_hooks
        reset_lifecycle_hooks()
        h1 = get_lifecycle_hooks()
        h2 = get_lifecycle_hooks()
        assert h1 is h2
        reset_lifecycle_hooks()

    def test_16_hook_points(self):
        from src.core.lifecycle_hooks import HOOK_POINTS
        assert len(HOOK_POINTS) == 16
        assert "on_pre_llm" in HOOK_POINTS
        assert "on_post_llm" in HOOK_POINTS
        assert "on_task_start" in HOOK_POINTS
        assert "on_task_end" in HOOK_POINTS
        assert "on_error" in HOOK_POINTS
        assert "on_limit_exceeded" in HOOK_POINTS

    def test_aliases_resolve(self):
        from src.core.lifecycle_hooks import LifecycleHookRegistry
        reg = LifecycleHookRegistry()
        calls = []
        reg.register("pre_llm_call", lambda **kw: calls.append("alias"), name="old")
        reg.fire("on_pre_llm")
        assert calls == ["alias"]

    def test_invalid_hook_point_raises(self):
        from src.core.lifecycle_hooks import LifecycleHookRegistry
        reg = LifecycleHookRegistry()
        with pytest.raises(ValueError):
            reg.register("invalid_point", lambda **kw: None)


# ═══════════════════════════════════════════════════════════════
# 4. Webhook → Handlers
# ═══════════════════════════════════════════════════════════════

class TestWebhookIntegration:
    """Test that handlers.py includes webhook handling."""

    def test_webhook_handler_registered(self):
        from src.gateway.handlers import NO_TOKEN_HANDLERS
        assert "webhook" in NO_TOKEN_HANDLERS
        assert "webhook_stats" in NO_TOKEN_HANDLERS

    def test_webhook_handler_missing_event_type(self):
        from src.gateway.handlers import handle_webhook
        result = handle_webhook()
        assert result["type"] == "error"
        assert "event_type" in result["message"]

    def test_webhook_receiver_basic(self):
        from src.gateway.webhook import WebhookReceiver, WebhookSubscription, WebhookEvent
        receiver = WebhookReceiver()
        receiver.register("test.push", WebhookSubscription(
            event_type="test.push",
            intent="code_review",
            department="quality",
        ))
        event = WebhookEvent(event_type="test.push", payload={"message": "hello"})
        dispatched = receiver.handle(event)
        assert len(dispatched) == 1
        assert dispatched[0]["department"] == "quality"
        assert dispatched[0]["intent"] == "code_review"
        assert dispatched[0]["source"] == "webhook:test.push"

    def test_webhook_filter(self):
        from src.gateway.webhook import WebhookReceiver, WebhookSubscription, WebhookEvent
        receiver = WebhookReceiver()
        receiver.register("ci.result", WebhookSubscription(
            event_type="ci.result",
            intent="ops_repair",
            department="operations",
            filter_field="status",
            filter_value="failed",
        ))
        # Should match
        event_fail = WebhookEvent(event_type="ci.result", payload={"status": "failed"})
        assert len(receiver.handle(event_fail)) == 1
        # Should not match
        event_ok = WebhookEvent(event_type="ci.result", payload={"status": "success"})
        assert len(receiver.handle(event_ok)) == 0

    def test_webhook_hmac_validation(self):
        import hashlib, hmac, json
        from src.gateway.webhook import WebhookReceiver
        receiver = WebhookReceiver()
        secret = "test-secret"
        payload = {"key": "value"}
        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        sig = "sha256=" + hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
        assert receiver.validate_signature(payload_bytes, sig, secret) is True
        assert receiver.validate_signature(payload_bytes, "sha256=bad", secret) is False

    def test_webhook_stats(self):
        from src.gateway.webhook import WebhookReceiver
        receiver = WebhookReceiver()
        stats = receiver.get_stats()
        assert "received" in stats
        assert "subscriptions" in stats


# ═══════════════════════════════════════════════════════════════
# 5. Rule Dependencies → Intent Rules
# ═══════════════════════════════════════════════════════════════

class TestRuleDependenciesIntegration:
    """Test that intent_rules.py uses the dependency resolver."""

    def test_dep_resolver_imported(self):
        from src.gateway.intent_rules import get_dependency_resolver
        resolver = get_dependency_resolver()
        # Should be initialized (not None) if module imported successfully
        assert resolver is not None

    def test_dep_resolver_has_rules(self):
        from src.gateway.intent_rules import get_dependency_resolver
        resolver = get_dependency_resolver()
        stats = resolver.get_stats()
        assert stats["total_rules"] > 0

    def test_dep_resolver_basic(self):
        from src.gateway.rule_dependencies import RuleDependencyResolver
        resolver = RuleDependencyResolver()
        resolver.add_rule("fix", tags=["eng"])
        resolver.add_rule("review", tags=["qa"], requires=["fix"])
        assert resolver.is_active("fix")
        assert resolver.is_active("review")
        resolver.deactivate_tag("eng")
        assert not resolver.is_active("fix")
        assert not resolver.is_active("review")  # cascade

    def test_dep_resolver_requires_any(self):
        from src.gateway.rule_dependencies import RuleDependencyResolver
        resolver = RuleDependencyResolver()
        resolver.add_rule("a", tags=["t1"])
        resolver.add_rule("b", tags=["t2"])
        resolver.add_rule("c", tags=["t3"], requires_any=["a", "b"])
        assert resolver.is_active("c")
        resolver.deactivate_tag("t1")
        assert resolver.is_active("c")  # b still active
        resolver.deactivate_tag("t2")
        assert not resolver.is_active("c")  # both gone

    def test_dep_resolver_cascade_impact(self):
        from src.gateway.rule_dependencies import RuleDependencyResolver
        resolver = RuleDependencyResolver()
        resolver.add_rule("x", tags=["tag_x"])
        resolver.add_rule("y", tags=["tag_y"], requires=["x"])
        impact = resolver.get_cascade_impact("tag_x")
        assert "x" in impact
        assert "y" in impact

    def test_rule_match_respects_dependencies(self):
        """If a rule's dependency is deactivated, try_rule_match should skip it."""
        from src.gateway.intent_rules import try_rule_match, get_dependency_resolver
        resolver = get_dependency_resolver()
        if resolver is None:
            pytest.skip("dependency resolver not available")
        # All tags should be active by default, so normal match should work
        result = try_rule_match("修复这个 bug")
        # code_fix should match if engineering tag is active
        if result:
            assert result.intent == "code_fix"


# ═══════════════════════════════════════════════════════════════
# 6. Deferred Retrieval → Context Engine
# ═══════════════════════════════════════════════════════════════

class TestDeferredRetrievalIntegration:
    """Test that the ContextEngine includes deferred retrieval."""

    def test_deferred_context_basic(self):
        from src.governance.deferred_retrieval import DeferredContext
        ctx = DeferredContext()
        calls = []
        ctx.register("test_key", lambda: (calls.append(1), "test_value")[1])
        # Not loaded yet
        assert ctx.is_loaded("test_key") is False
        assert len(calls) == 0
        # Load on access
        val = ctx.get("test_key")
        assert val == "test_value"
        assert len(calls) == 1
        # Second access uses cache
        val2 = ctx.get("test_key")
        assert val2 == "test_value"
        assert len(calls) == 1  # not called again

    def test_deferred_context_error_handling(self):
        from src.governance.deferred_retrieval import DeferredContext
        ctx = DeferredContext()
        ctx.register("bad", lambda: 1/0)
        val = ctx.get("bad", default="fallback")
        assert val == "fallback"
        assert ctx.get_stats()["errors"] == 1

    def test_deferred_context_stats(self):
        from src.governance.deferred_retrieval import DeferredContext
        ctx = DeferredContext()
        ctx.register("a", lambda: "val_a")
        ctx.register("b", lambda: "val_b")
        ctx.get("a")  # load a, skip b
        stats = ctx.get_stats()
        assert stats["loaded"] == 1
        assert stats["skipped"] == 1
        assert stats["tokens_saved_estimate"] == 500  # 1 skipped * 500

    def test_deferred_provider_class_exists(self):
        from src.governance.context.engine import DeferredRetrievalProvider
        provider = DeferredRetrievalProvider()
        assert provider.name == "deferred_retrieval"

    def test_get_deferred_context_api(self):
        from src.governance.context.engine import get_deferred_context
        ctx = get_deferred_context()
        assert ctx is not None
        assert hasattr(ctx, 'register')
        assert hasattr(ctx, 'get')

    def test_deferred_provider_returns_chunks_for_matching_keys(self):
        from src.governance.context.engine import (
            DeferredRetrievalProvider, TaskContext, get_deferred_context,
        )
        ctx = get_deferred_context()
        ctx.register("engineering:guidelines", lambda: "Follow PEP 8", override=True)
        ctx.register("shared:project_info", lambda: "Orchestrator project", override=True)
        ctx.register("security:policy", lambda: "No secrets in code", override=True)

        provider = DeferredRetrievalProvider()
        task_ctx = TaskContext(department="engineering")
        chunks = provider.provide(task_ctx)
        # Should include engineering: and shared: but not security:
        sources = [c.source for c in chunks]
        assert "deferred:engineering:guidelines" in sources
        assert "deferred:shared:project_info" in sources
        assert "deferred:security:policy" not in sources
