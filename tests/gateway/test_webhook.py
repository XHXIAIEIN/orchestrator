"""Tests for Webhook Event-Driven Trigger."""
from src.gateway.webhook import (
    WebhookReceiver, WebhookSubscription, WebhookEvent,
)


def test_register_and_handle():
    """Basic flow: register subscription, handle matching event."""
    receiver = WebhookReceiver()
    receiver.register("github.push", WebhookSubscription(
        event_type="github.push",
        intent="code_review",
        department="quality",
    ))
    results = receiver.handle(WebhookEvent(
        event_type="github.push",
        payload={"ref": "refs/heads/main", "message": "fix bug"},
    ))
    assert len(results) == 1
    assert results[0]["department"] == "quality"
    assert results[0]["intent"] == "code_review"
    assert results[0]["source"] == "webhook:github.push"


def test_no_subscription_returns_empty():
    """No matching subscription -> empty results."""
    receiver = WebhookReceiver()
    results = receiver.handle(WebhookEvent(event_type="unknown", payload={}))
    assert results == []


def test_filter_field_match():
    """Subscription with filter_field should only match when field exists."""
    receiver = WebhookReceiver()
    receiver.register("ci.complete", WebhookSubscription(
        event_type="ci.complete",
        intent="ops_deploy",
        department="operations",
        filter_field="status",
        filter_value="success",
    ))
    # Matching
    results = receiver.handle(WebhookEvent(
        event_type="ci.complete",
        payload={"status": "success", "build_id": "123"},
    ))
    assert len(results) == 1

    # Not matching
    results = receiver.handle(WebhookEvent(
        event_type="ci.complete",
        payload={"status": "failed", "build_id": "124"},
    ))
    assert results == []


def test_filter_nested_field():
    """Filter should work with dot-notation for nested fields."""
    receiver = WebhookReceiver()
    receiver.register("github.push", WebhookSubscription(
        event_type="github.push",
        intent="code_review",
        department="quality",
        filter_field="repository.name",
        filter_value="orchestrator",
    ))
    results = receiver.handle(WebhookEvent(
        event_type="github.push",
        payload={"repository": {"name": "orchestrator"}, "ref": "main"},
    ))
    assert len(results) == 1


def test_disabled_subscription_skipped():
    """Disabled subscriptions should be skipped."""
    receiver = WebhookReceiver()
    receiver.register("test.event", WebhookSubscription(
        event_type="test.event",
        intent="test",
        department="engineering",
        enabled=False,
    ))
    results = receiver.handle(WebhookEvent(event_type="test.event", payload={}))
    assert results == []


def test_signature_validation():
    """HMAC signature validation."""
    receiver = WebhookReceiver()
    import hashlib, hmac as hmac_mod, json
    secret = "test-secret"
    payload = {"action": "test"}
    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    sig = "sha256=" + hmac_mod.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

    receiver.register("secure.event", WebhookSubscription(
        event_type="secure.event",
        intent="security_scan",
        department="security",
        secret=secret,
    ))

    # Valid signature
    results = receiver.handle(WebhookEvent(
        event_type="secure.event", payload=payload, signature=sig,
    ))
    assert len(results) == 1

    # Invalid signature
    results = receiver.handle(WebhookEvent(
        event_type="secure.event", payload=payload, signature="sha256=bad",
    ))
    assert results == []


def test_multiple_subscriptions():
    """Multiple subs for same event type should all fire."""
    receiver = WebhookReceiver()
    receiver.register("deploy.done", WebhookSubscription(
        event_type="deploy.done", intent="ops_health", department="operations",
    ))
    receiver.register("deploy.done", WebhookSubscription(
        event_type="deploy.done", intent="quality_regression", department="quality",
    ))
    results = receiver.handle(WebhookEvent(event_type="deploy.done", payload={}))
    assert len(results) == 2


def test_stats_tracking():
    """Stats should track received/dispatched/filtered."""
    receiver = WebhookReceiver()
    receiver.register("test", WebhookSubscription(
        event_type="test", intent="test", department="engineering",
    ))
    receiver.handle(WebhookEvent(event_type="test", payload={}))
    receiver.handle(WebhookEvent(event_type="unknown", payload={}))

    stats = receiver.get_stats()
    assert stats["received"] == 2
    assert stats["dispatched"] == 1
    assert stats["filtered"] == 1
    assert stats["subscriptions"] == 1


def test_unregister():
    """Unregister removes all subscriptions for an event type."""
    receiver = WebhookReceiver()
    receiver.register("test", WebhookSubscription(
        event_type="test", intent="test", department="engineering",
    ))
    assert receiver.get_subscriptions().get("test")
    receiver.unregister("test")
    assert not receiver.get_subscriptions().get("test")


def test_load_from_yaml(tmp_path):
    """Load subscriptions from YAML config."""
    config = tmp_path / "webhooks.yaml"
    config.write_text("""
webhooks:
  - event_type: github.push
    intent: code_review
    department: quality
    description: "Review pushed commits"
    filter_field: ref
    filter_value: refs/heads/main
  - event_type: ci.fail
    intent: incident_response
    department: operations
    priority: high
""")
    receiver = WebhookReceiver()
    receiver.load_from_yaml(config)
    subs = receiver.get_subscriptions()
    assert "github.push" in subs
    assert "ci.fail" in subs
    assert subs["ci.fail"][0].priority == "high"
