"""Tests for src.core.circuit_breaker — state transitions + global registry."""
import pytest
from src.core.circuit_breaker import (
    CircuitBreaker, CircuitBreakerConfig, CircuitBreakerError,
    CircuitState, get_breaker, get_all_breaker_stats,
)


class TestCircuitBreakerStateTransitions:
    def test_starts_closed(self):
        cb = CircuitBreaker("test-closed", CircuitBreakerConfig(failure_threshold=2))
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker("test-open", CircuitBreakerConfig(failure_threshold=2, recovery_timeout_s=60))
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_raises_error(self):
        cb = CircuitBreaker("test-reject", CircuitBreakerConfig(failure_threshold=1, recovery_timeout_s=60))
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        with pytest.raises(CircuitBreakerError):
            cb.call(lambda: "should not run")

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker("test-reset", CircuitBreakerConfig(failure_threshold=3))
        # 1 failure then 1 success → counter resets
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        assert cb.call(lambda: "ok") == "ok"
        assert cb.state == CircuitState.CLOSED

    def test_half_open_on_timeout(self):
        cb = CircuitBreaker("test-half", CircuitBreakerConfig(failure_threshold=1, recovery_timeout_s=0))
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        # recovery_timeout_s=0 → immediately transition to HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN


class TestGlobalRegistry:
    def test_get_breaker_returns_same_instance(self):
        b1 = get_breaker("test-svc-singleton")
        b2 = get_breaker("test-svc-singleton")
        assert b1 is b2

    def test_get_all_stats(self):
        get_breaker("stats-test-digest")
        stats = get_all_breaker_stats()
        names = [s["name"] for s in stats]
        assert "stats-test-digest" in names
