"""R62 DeerFlow: Three-State Circuit Breaker + Exponential Backoff.

States:
    CLOSED  → normal operation, failures are counted
    OPEN    → fast-fail all requests (after failure_threshold breaches)
    HALF_OPEN → allow one probe request to test recovery

Transitions:
    CLOSED → OPEN: consecutive failures >= failure_threshold
    OPEN → HALF_OPEN: recovery_timeout elapsed
    HALF_OPEN → CLOSED: probe succeeds
    HALF_OPEN → OPEN: probe fails (reset recovery timer)

Integration: Wraps LLM API calls in executor.py / any external service.
Complements resilient_retry.py (which handles per-call retries;
circuit breaker handles cross-call failure accumulation).

Source: DeerFlow 2.0 LLMErrorHandlingMiddleware (R62 deep steal)
"""
from __future__ import annotations

import logging
import random
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    failure_threshold: int = 5          # consecutive failures to trip open
    recovery_timeout_s: float = 60.0    # seconds before OPEN → HALF_OPEN
    half_open_max_calls: int = 1        # probes allowed in HALF_OPEN
    success_threshold: int = 1          # successes in HALF_OPEN to close

    # Exponential backoff for retry-after hints
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0
    jitter: bool = True

    # Optional: respect Retry-After header from API responses
    respect_retry_after: bool = True


class CircuitBreakerError(Exception):
    """Raised when circuit is OPEN and call is rejected."""

    def __init__(self, breaker_name: str, time_until_probe: float):
        self.breaker_name = breaker_name
        self.time_until_probe = time_until_probe
        super().__init__(
            f"Circuit breaker '{breaker_name}' is OPEN. "
            f"Next probe in {time_until_probe:.1f}s."
        )


class CircuitBreaker:
    """Three-state circuit breaker for external service calls.

    Usage:
        breaker = CircuitBreaker("llm-api")

        # Option 1: decorator-style
        result = breaker.call(lambda: api_client.complete(prompt))

        # Option 2: context manager
        with breaker.guard():
            result = api_client.complete(prompt)
            # if this raises, breaker records failure
    """

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0
        self._last_retry_after: float | None = None
        self._half_open_calls = 0
        self._lock = threading.Lock()
        self._total_calls = 0
        self._total_failures = 0
        self._total_rejections = 0

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    def call(self, fn: Callable[[], T]) -> T:
        """Execute fn through the circuit breaker.

        Raises CircuitBreakerError if circuit is OPEN.
        Records success/failure and manages state transitions.
        """
        self._pre_call_check()

        try:
            result = fn()
            self._record_success()
            return result
        except Exception as exc:
            self._record_failure(exc)
            raise

    def _pre_call_check(self):
        """Check if the call is allowed. Raise if circuit is OPEN."""
        with self._lock:
            self._total_calls += 1
            self._maybe_transition_to_half_open()

            if self._state == CircuitState.OPEN:
                wait = self._time_until_probe()
                self._total_rejections += 1
                raise CircuitBreakerError(self.name, wait)

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    wait = self._time_until_probe()
                    self._total_rejections += 1
                    raise CircuitBreakerError(self.name, wait)
                self._half_open_calls += 1

    def _record_success(self):
        """Record a successful call."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    log.info(
                        "circuit_breaker[%s]: HALF_OPEN → CLOSED (probe succeeded)",
                        self.name,
                    )
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._half_open_calls = 0
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    def _record_failure(self, exc: Exception):
        """Record a failed call and potentially trip the breaker."""
        with self._lock:
            self._total_failures += 1
            self._last_failure_time = time.monotonic()

            # Extract Retry-After if present
            if self.config.respect_retry_after:
                retry_after = self._extract_retry_after(exc)
                if retry_after is not None:
                    self._last_retry_after = retry_after

            if self._state == CircuitState.HALF_OPEN:
                # Probe failed → back to OPEN
                log.warning(
                    "circuit_breaker[%s]: HALF_OPEN → OPEN (probe failed: %s)",
                    self.name, type(exc).__name__,
                )
                self._state = CircuitState.OPEN
                self._success_count = 0
                self._half_open_calls = 0

            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.config.failure_threshold:
                    log.warning(
                        "circuit_breaker[%s]: CLOSED → OPEN (%d consecutive failures)",
                        self.name, self._failure_count,
                    )
                    self._state = CircuitState.OPEN

    def _maybe_transition_to_half_open(self):
        """Check if enough time has passed to probe (must hold lock)."""
        if self._state != CircuitState.OPEN:
            return

        elapsed = time.monotonic() - self._last_failure_time
        timeout = self._effective_recovery_timeout()

        if elapsed >= timeout:
            log.info(
                "circuit_breaker[%s]: OPEN → HALF_OPEN (%.1fs elapsed, timeout=%.1fs)",
                self.name, elapsed, timeout,
            )
            self._state = CircuitState.HALF_OPEN
            self._half_open_calls = 0
            self._success_count = 0

    def _effective_recovery_timeout(self) -> float:
        """Compute recovery timeout, respecting Retry-After if set."""
        base = self.config.recovery_timeout_s
        if self._last_retry_after is not None:
            base = max(base, self._last_retry_after)
            self._last_retry_after = None  # consume once
        return base

    def _time_until_probe(self) -> float:
        """Seconds until next probe attempt (must hold lock)."""
        elapsed = time.monotonic() - self._last_failure_time
        timeout = self._effective_recovery_timeout()
        return max(0.0, timeout - elapsed)

    @staticmethod
    def _extract_retry_after(exc: Exception) -> float | None:
        """Try to extract Retry-After from API error responses."""
        # Check for retry_after attribute (httpx, anthropic SDK)
        for attr in ("retry_after", "retry_after_seconds"):
            val = getattr(exc, attr, None)
            if isinstance(val, (int, float)) and val > 0:
                return float(val)

        # Check response headers if available
        response = getattr(exc, "response", None)
        if response is not None:
            headers = getattr(response, "headers", {})
            ra = headers.get("Retry-After") or headers.get("retry-after")
            if ra:
                try:
                    return float(ra)
                except ValueError:
                    pass

        return None

    def backoff_delay(self, attempt: int) -> float:
        """Compute exponential backoff delay for a given attempt number."""
        delay = self.config.base_delay_s * (2 ** attempt)
        delay = min(delay, self.config.max_delay_s)
        if self.config.jitter:
            delay *= 0.5 + random.random()
        return delay

    def get_stats(self) -> dict:
        """Return breaker health snapshot."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "total_calls": self._total_calls,
                "total_failures": self._total_failures,
                "total_rejections": self._total_rejections,
            }

    def force_open(self):
        """Manually trip the breaker (for testing or emergency)."""
        with self._lock:
            self._state = CircuitState.OPEN
            self._last_failure_time = time.monotonic()
            log.warning("circuit_breaker[%s]: manually forced OPEN", self.name)

    def force_close(self):
        """Manually reset the breaker (for testing or recovery)."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            log.info("circuit_breaker[%s]: manually forced CLOSED", self.name)


# ── Registry for named breakers ──

_breakers: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(
    name: str, config: CircuitBreakerConfig | None = None
) -> CircuitBreaker:
    """Get or create a named circuit breaker (singleton per name)."""
    with _registry_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(name, config)
        return _breakers[name]


def get_all_breaker_stats() -> list[dict]:
    """Return stats for all registered breakers."""
    with _registry_lock:
        return [b.get_stats() for b in _breakers.values()]
