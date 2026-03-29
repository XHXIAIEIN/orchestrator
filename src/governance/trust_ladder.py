"""Trust Ladder — stolen from gstack.

First-time operations require full approval. Once approved, the operation
pattern is trusted for future invocations (within TTL). Config fingerprint
changes reset all trust (stolen from gstack's Config Decay Detection).

Usage:
    ladder = TrustLadder()
    if ladder.is_trusted(operation, description):
        # auto-approve
    else:
        # request human approval
        # on approval: ladder.record_approval(operation, description)
"""
import logging
import time

log = logging.getLogger(__name__)

DEFAULT_TRUST_TTL = 86400  # 24 hours


class TrustLadder:
    """Track approved operations and auto-trust repeats."""

    def __init__(self, trust_ttl_s: int = DEFAULT_TRUST_TTL):
        self._trust_ttl = trust_ttl_s
        self._trusted: dict[str, float] = {}  # operation_key → approved_at timestamp
        self._fingerprint: str = ""
        self._auto_approved_count = 0

    def _make_key(self, operation: str, description: str) -> str:
        """Create a stable key for an operation pattern."""
        # Use operation type as key — description varies but operation type is stable
        return operation.strip().lower()

    def is_trusted(self, operation: str, description: str) -> bool:
        """Check if this operation has been previously approved and is still within TTL."""
        key = self._make_key(operation, description)
        approved_at = self._trusted.get(key)
        if approved_at is None:
            return False
        if (time.time() - approved_at) >= self._trust_ttl:
            del self._trusted[key]
            log.info(f"trust_ladder: {key} trust expired")
            return False
        return True

    def record_approval(self, operation: str, description: str):
        """Record that an operation was approved by a human."""
        key = self._make_key(operation, description)
        self._trusted[key] = time.time()
        log.info(f"trust_ladder: recorded approval for {key}")

    def auto_approve_if_trusted(self, operation: str, description: str) -> bool:
        """Check trust and log if auto-approved. Returns True if trusted."""
        if self.is_trusted(operation, description):
            self._auto_approved_count += 1
            log.info(f"trust_ladder: auto-approved {operation} (trusted)")
            return True
        return False

    def update_fingerprint(self, new_fingerprint: str):
        """Update config fingerprint. If changed, reset all trust."""
        if new_fingerprint != self._fingerprint:
            count = len(self._trusted)
            self._trusted.clear()
            log.warning(f"trust_ladder: config fingerprint changed, reset {count} trusted operations")
        self._fingerprint = new_fingerprint

    def get_stats(self) -> dict:
        return {
            "trusted_operations": len(self._trusted),
            "auto_approved_total": self._auto_approved_count,
            "fingerprint": self._fingerprint,
        }
