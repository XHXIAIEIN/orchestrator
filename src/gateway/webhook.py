"""Webhook Event-Driven Trigger — stolen from Hermes.

External events (GitHub push, CI fail, Stripe payment, etc.) trigger
agent runs through the standard IntentGateway -> Governor pipeline.

Subscriptions define: event_type -> intent mapping + optional filters.

Usage:
    receiver = WebhookReceiver()
    receiver.register("github.push", WebhookSubscription(
        event_type="github.push",
        intent="code_review",
        department="quality",
        filter_jq=".ref == 'refs/heads/main'",
    ))
    # On incoming webhook:
    task_id = receiver.handle(event_type="github.push", payload={...})
"""
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class WebhookSubscription:
    """A webhook subscription — maps an event type to an intent."""
    event_type: str              # e.g. "github.push", "ci.fail"
    intent: str                  # maps to IntentRoute
    department: str              # target department
    description: str = ""        # human-readable
    priority: str = "medium"     # default priority
    cognitive_mode: str = "react"
    filter_field: str = ""       # optional: only trigger if this JSON field exists
    filter_value: str = ""       # optional: only trigger if field == value
    secret: str = ""             # HMAC secret for signature validation
    enabled: bool = True


@dataclass
class WebhookEvent:
    """An incoming webhook event."""
    event_type: str
    payload: dict
    source_ip: str = ""
    signature: str = ""          # X-Hub-Signature-256 or similar
    received_at: float = field(default_factory=time.time)


class WebhookReceiver:
    """Registry and dispatcher for webhook-triggered agent runs."""

    def __init__(self):
        self._subscriptions: dict[str, list[WebhookSubscription]] = {}
        self._stats = {"received": 0, "dispatched": 0, "filtered": 0, "errors": 0}

    def register(self, event_type: str, sub: WebhookSubscription):
        """Register a subscription for an event type."""
        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []
        self._subscriptions[event_type].append(sub)
        log.info(f"webhook: registered {event_type} -> {sub.department}/{sub.intent}")

    def unregister(self, event_type: str):
        """Remove all subscriptions for an event type."""
        removed = self._subscriptions.pop(event_type, [])
        if removed:
            log.info(f"webhook: unregistered {len(removed)} subs for {event_type}")

    def get_subscriptions(self) -> dict[str, list[WebhookSubscription]]:
        """Return all registered subscriptions."""
        return dict(self._subscriptions)

    def validate_signature(self, payload_bytes: bytes, signature: str, secret: str) -> bool:
        """Validate HMAC-SHA256 signature (GitHub-style)."""
        if not secret or not signature:
            return True  # no secret configured = skip validation
        expected = "sha256=" + hmac.new(
            secret.encode(), payload_bytes, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def match_filter(self, sub: WebhookSubscription, payload: dict) -> bool:
        """Check if payload matches subscription filter."""
        if not sub.filter_field:
            return True  # no filter = always match
        value = payload
        for key in sub.filter_field.split("."):
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return False
        if sub.filter_value:
            return str(value) == sub.filter_value
        return value is not None  # field exists

    def handle(self, event: WebhookEvent) -> list[dict]:
        """Process an incoming webhook event. Returns list of dispatched task specs.

        For each matching subscription:
        1. Validate signature (if secret configured)
        2. Apply filter
        3. Create TaskIntent and dispatch
        """
        self._stats["received"] += 1
        subs = self._subscriptions.get(event.event_type, [])

        if not subs:
            log.debug(f"webhook: no subscriptions for {event.event_type}")
            self._stats["filtered"] += 1
            return []

        dispatched = []
        for sub in subs:
            if not sub.enabled:
                continue

            # Signature validation
            if sub.secret:
                payload_bytes = json.dumps(event.payload, sort_keys=True).encode()
                if not self.validate_signature(payload_bytes, event.signature, sub.secret):
                    log.warning(f"webhook: signature mismatch for {event.event_type}")
                    self._stats["errors"] += 1
                    continue

            # Filter check
            if not self.match_filter(sub, event.payload):
                self._stats["filtered"] += 1
                continue

            # Build task spec (same format as IntentGateway output)
            summary = self._build_summary(sub, event)
            spec = {
                "department": sub.department,
                "intent": sub.intent,
                "cognitive_mode": sub.cognitive_mode,
                "priority": sub.priority,
                "problem": summary,
                "expected": f"Handle {event.event_type} event",
                "summary": summary,
                "source": f"webhook:{event.event_type}",
                "observation": f"Webhook event: {event.event_type}",
                "importance": f"External event trigger, priority {sub.priority}",
            }
            dispatched.append(spec)
            self._stats["dispatched"] += 1
            log.info(f"webhook: dispatched {event.event_type} -> {sub.department}/{sub.intent}")

        return dispatched

    def _build_summary(self, sub: WebhookSubscription, event: WebhookEvent) -> str:
        """Build a human-readable summary from the event payload."""
        payload = event.payload
        parts = [f"[Webhook: {event.event_type}]"]

        if sub.description:
            parts.append(sub.description)

        # Try common payload fields
        for key in ("message", "description", "title", "text", "commit_message"):
            if key in payload and payload[key]:
                parts.append(str(payload[key])[:200])
                break

        return " — ".join(parts)

    def load_from_yaml(self, path: str | Path):
        """Load subscriptions from a YAML config file.

        Format:
            webhooks:
              - event_type: github.push
                intent: code_review
                department: quality
                description: "Review pushed commits"
                filter_field: ref
                filter_value: refs/heads/main
                secret: ${GITHUB_WEBHOOK_SECRET}
        """
        import yaml
        import os

        path = Path(path)
        if not path.exists():
            log.debug(f"webhook: config {path} not found, skipping")
            return

        with open(path) as f:
            config = yaml.safe_load(f)

        if not config or "webhooks" not in config:
            return

        for entry in config["webhooks"]:
            # Resolve env vars in secret
            secret = entry.get("secret", "")
            if secret.startswith("${") and secret.endswith("}"):
                env_var = secret[2:-1]
                secret = os.environ.get(env_var, "")

            sub = WebhookSubscription(
                event_type=entry["event_type"],
                intent=entry.get("intent", ""),
                department=entry.get("department", "engineering"),
                description=entry.get("description", ""),
                priority=entry.get("priority", "medium"),
                cognitive_mode=entry.get("cognitive_mode", "react"),
                filter_field=entry.get("filter_field", ""),
                filter_value=entry.get("filter_value", ""),
                secret=secret,
                enabled=entry.get("enabled", True),
            )
            self.register(entry["event_type"], sub)

        log.info(f"webhook: loaded {len(config['webhooks'])} subscriptions from {path}")

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "subscriptions": sum(len(v) for v in self._subscriptions.values()),
        }


# Singleton
_receiver: Optional[WebhookReceiver] = None


def get_webhook_receiver() -> WebhookReceiver:
    global _receiver
    if _receiver is None:
        _receiver = WebhookReceiver()
    return _receiver
