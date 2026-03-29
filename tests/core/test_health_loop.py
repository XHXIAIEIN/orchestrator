# tests/core/test_health_loop.py
"""Tests for event loop health probe."""
import time
from unittest.mock import MagicMock
from src.core.health import HealthCheck


def test_event_loop_health_returns_latency():
    """Event loop probe should return latency_ms and status."""
    hc = HealthCheck.__new__(HealthCheck)
    hc.db = MagicMock()
    hc.db_path = ":memory:"
    hc.issues = []
    result = hc._check_event_loop()
    assert "latency_ms" in result
    assert "status" in result
    assert result["status"] in ("healthy", "degraded", "unhealthy")


def test_event_loop_healthy_under_100ms():
    """Normal system should report healthy."""
    hc = HealthCheck.__new__(HealthCheck)
    hc.db = MagicMock()
    hc.db_path = ":memory:"
    hc.issues = []
    result = hc._check_event_loop()
    # On any modern machine, callback latency should be well under 100ms
    assert result["latency_ms"] < 100
    assert result["status"] == "healthy"
