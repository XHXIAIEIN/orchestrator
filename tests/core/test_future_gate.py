"""Tests for FutureGate — stolen from ChatDev 2.0's SessionExecutionController."""
import threading
import time
import pytest
from src.core.future_gate import FutureGate, GateTimeout, GateCancelled


def test_basic_wait_and_provide():
    gate = FutureGate()
    gate_id = gate.open("test_gate")
    result = {}
    def waiter():
        result["value"] = gate.wait(gate_id, timeout=5.0)
    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    time.sleep(0.1)
    gate.provide(gate_id, {"approved": True})
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert result["value"] == {"approved": True}


def test_timeout():
    gate = FutureGate()
    gate_id = gate.open("timeout_test")
    with pytest.raises(GateTimeout):
        gate.wait(gate_id, timeout=0.2)


def test_cancel():
    gate = FutureGate()
    gate_id = gate.open("cancel_test")
    raised = {}
    def waiter():
        try:
            gate.wait(gate_id, timeout=10.0)
        except GateCancelled as e:
            raised["reason"] = str(e)
    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    time.sleep(0.1)
    gate.cancel(gate_id, reason="user disconnected")
    t.join(timeout=2.0)
    assert "reason" in raised
    assert "user disconnected" in raised["reason"]


def test_cleanup_after_wait():
    gate = FutureGate()
    gate_id = gate.open("cleanup_test")
    gate.provide(gate_id, "done")
    gate.wait(gate_id, timeout=1.0)
    assert not gate.is_waiting(gate_id)


def test_provide_before_wait():
    gate = FutureGate()
    gate_id = gate.open("pre_provide")
    gate.provide(gate_id, "early_value")
    result = gate.wait(gate_id, timeout=1.0)
    assert result == "early_value"


def test_status():
    gate = FutureGate()
    gate_id = gate.open("status_test")
    assert gate.is_waiting(gate_id)
    gate.provide(gate_id, "x")
    info = gate.status(gate_id)
    assert info["done"]
