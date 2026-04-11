"""R48 (Hermes v0.8): Credential Pool with Lease/Release.

Multiple API keys pooled. acquire_lease() grants exclusive use,
release_lease() returns key to pool. Prevents concurrent conflicts
when multiple agents use the same provider.
"""
import logging
import time
from dataclasses import dataclass, field
from threading import Lock

log = logging.getLogger(__name__)

LEASE_TIMEOUT_S = 300  # auto-release after 5 minutes


@dataclass
class Credential:
    """A pooled credential."""
    key_id: str
    provider: str  # 'anthropic', 'openai', etc.
    api_key: str
    leased_to: str | None = None
    leased_at: float | None = None
    use_count: int = 0
    error_count: int = 0

    @property
    def is_available(self) -> bool:
        if self.leased_to is None:
            return True
        # Auto-release stale leases
        if self.leased_at and (time.monotonic() - self.leased_at) > LEASE_TIMEOUT_S:
            return True
        return False


class CredentialPool:
    """Thread-safe API key pool with lease/release semantics."""

    def __init__(self):
        self._lock = Lock()
        self._credentials: list[Credential] = []

    def add(self, key_id: str, provider: str, api_key: str) -> None:
        with self._lock:
            self._credentials.append(Credential(
                key_id=key_id, provider=provider, api_key=api_key
            ))

    def acquire_lease(self, provider: str, lessee: str) -> Credential | None:
        """Acquire exclusive use of a credential. Returns None if none available."""
        with self._lock:
            # Find available credential for provider, prefer least-used
            candidates = [
                c for c in self._credentials
                if c.provider == provider and c.is_available
            ]
            if not candidates:
                return None

            # Least-used first (load balancing)
            cred = min(candidates, key=lambda c: c.use_count)
            cred.leased_to = lessee
            cred.leased_at = time.monotonic()
            cred.use_count += 1
            log.info("credential_pool: %s leased %s/%s (use #%d)",
                     lessee, provider, cred.key_id, cred.use_count)
            return cred

    def release_lease(self, key_id: str) -> None:
        """Release a leased credential back to the pool."""
        with self._lock:
            for cred in self._credentials:
                if cred.key_id == key_id:
                    cred.leased_to = None
                    cred.leased_at = None
                    return

    def report_error(self, key_id: str) -> None:
        """Report an error for a credential (for health tracking)."""
        with self._lock:
            for cred in self._credentials:
                if cred.key_id == key_id:
                    cred.error_count += 1
                    return

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "total": len(self._credentials),
                "available": sum(1 for c in self._credentials if c.is_available),
                "leased": sum(1 for c in self._credentials if not c.is_available),
                "by_provider": self._by_provider(),
            }

    def _by_provider(self) -> dict:
        providers: dict[str, dict] = {}
        for c in self._credentials:
            p = providers.setdefault(c.provider, {"total": 0, "available": 0, "errors": 0})
            p["total"] += 1
            if c.is_available:
                p["available"] += 1
            p["errors"] += c.error_count
        return providers


# ── Singleton ──
_instance: CredentialPool | None = None


def get_credential_pool() -> CredentialPool:
    global _instance
    if _instance is None:
        _instance = CredentialPool()
    return _instance
