"""Integration tests for ChatDev 2.0 Round 13 modules wired into production.

Tests that resilient_retry, event_stream, future_gate, and function_catalog
are properly integrated into executor, event_bus, group_orchestration, and
tool_policy respectively.
"""
import threading
import time
import pytest


# ═══════════════════════════════════════════════════════════════════
# 1. resilient_retry → executor._classify_failure
# ═══════════════════════════════════════════════════════════════════

class TestResilientRetryIntegration:
    """Test that _classify_failure uses exception chain traversal."""

    def test_classify_failure_string_based_preserved(self):
        """Original string-based classification still works."""
        from src.governance.executor import _classify_failure
        assert _classify_failure("timeout after 300s") == "timeout"
        assert _classify_failure("[WATCHDOG: execution timed out]") == "timeout"
        assert _classify_failure("[STUCK: repeated tool calls]") == "stuck"
        assert _classify_failure("[DOOM LOOP: circular]") == "stuck"
        assert _classify_failure("cost limit exceeded") == "cost_limit"
        assert _classify_failure("unresponsive agent") == "unresponsive"
        assert _classify_failure("something else") == "unknown"

    def test_classify_failure_with_timeout_exception(self):
        """Exception chain: TimeoutError should be classified as timeout."""
        from src.governance.executor import _classify_failure
        exc = TimeoutError("connection timed out")
        result = _classify_failure("some output", exc=exc)
        assert result == "timeout"

    def test_classify_failure_with_connection_error(self):
        """Exception chain: ConnectionError should be classified as transient."""
        from src.governance.executor import _classify_failure
        exc = ConnectionError("refused")
        result = _classify_failure("some output", exc=exc)
        assert result == "transient_server_error"

    def test_classify_failure_with_wrapped_exception(self):
        """Exception chain traversal: wrapped TimeoutError."""
        from src.governance.executor import _classify_failure
        inner = TimeoutError("inner timeout")
        outer = RuntimeError("wrapper")
        outer.__cause__ = inner
        result = _classify_failure("some output", exc=outer)
        assert result == "timeout"

    def test_classify_failure_with_rate_limit_status(self):
        """Exception with status_code=429 should be rate_limited."""
        from src.governance.executor import _classify_failure

        class APIError(Exception):
            def __init__(self):
                super().__init__("rate limited")
                self.status_code = 429

        result = _classify_failure("some output", exc=APIError())
        assert result == "rate_limited"

    def test_classify_failure_rate_limit_string(self):
        """String-based rate limit detection."""
        from src.governance.executor import _classify_failure
        assert _classify_failure("rate limit exceeded") == "rate_limited"

    def test_resilient_should_retry_used_as_fallback(self):
        """resilient_should_retry is consulted when string classification says unknown."""
        from src.core.resilient_retry import RetryPolicy, should_retry

        policy = RetryPolicy(
            retry_on_types=["ConnectionError"],
            no_retry_types=["KeyboardInterrupt"],
        )
        exc = ConnectionError("refused")
        assert should_retry(exc, policy) is True

        exc2 = KeyboardInterrupt()
        assert should_retry(exc2, policy) is False

    def test_default_resilient_policy_exists(self):
        """The default policy is configured in executor.py."""
        from src.governance.executor import _DEFAULT_RESILIENT_POLICY
        assert _DEFAULT_RESILIENT_POLICY is not None
        assert _DEFAULT_RESILIENT_POLICY.enabled is True
        assert 429 in _DEFAULT_RESILIENT_POLICY.retry_on_status_codes
        assert "CostLimitExceededError" in _DEFAULT_RESILIENT_POLICY.no_retry_types

    def test_retryable_conditions_includes_new_types(self):
        """RETRYABLE_CONDITIONS includes the new failure types."""
        from src.governance.executor import RETRYABLE_CONDITIONS
        assert "rate_limited" in RETRYABLE_CONDITIONS
        assert "transient_server_error" in RETRYABLE_CONDITIONS


# ═══════════════════════════════════════════════════════════════════
# 2. event_stream → event_bus (EventBusWithStream)
# ═══════════════════════════════════════════════════════════════════

class TestEventStreamIntegration:
    """Test that EventBusWithStream mirrors events to EventStream."""

    def test_event_bus_with_stream_exists(self):
        """EventBusWithStream class should be importable."""
        from src.core.event_bus import EventBusWithStream
        assert EventBusWithStream is not None

    def test_publish_mirrors_to_stream(self, tmp_path):
        """Published events appear in both SQLite and stream."""
        from src.core.event_bus import EventBusWithStream, Event, Priority

        bus = EventBusWithStream(db_path=str(tmp_path / "test_bus.db"))
        event = Event(
            event_type="test.event",
            payload={"key": "value"},
            priority=Priority.NORMAL,
        )
        bus.publish(event)

        # Check stream polling
        events, cursor = bus.poll_stream(after=0)
        assert len(events) == 1
        assert events[0]["event_type"] == "test.event"
        assert events[0]["data"] == {"key": "value"}
        assert cursor > 0

    def test_poll_stream_cursor(self, tmp_path):
        """Cursor-based polling returns only new events."""
        from src.core.event_bus import EventBusWithStream, Event

        bus = EventBusWithStream(db_path=str(tmp_path / "test_bus.db"))
        bus.publish(Event(event_type="a", payload={"n": 1}))
        bus.publish(Event(event_type="b", payload={"n": 2}))

        events1, cursor1 = bus.poll_stream(after=0)
        assert len(events1) == 2

        bus.publish(Event(event_type="c", payload={"n": 3}))
        events2, cursor2 = bus.poll_stream(after=cursor1)
        assert len(events2) == 1
        assert events2[0]["event_type"] == "c"

    def test_stream_stats(self, tmp_path):
        """stream_stats returns EventStream statistics."""
        from src.core.event_bus import EventBusWithStream, Event

        bus = EventBusWithStream(db_path=str(tmp_path / "test_bus.db"))
        bus.publish(Event(event_type="x", payload={}))

        stats = bus.stream_stats()
        assert stats["current_size"] == 1
        assert stats["total_appended"] == 1

    def test_get_stats_includes_stream(self, tmp_path):
        """get_stats includes stream section."""
        from src.core.event_bus import EventBusWithStream, Event

        bus = EventBusWithStream(db_path=str(tmp_path / "test_bus.db"))
        bus.publish(Event(event_type="x", payload={}))

        stats = bus.get_stats()
        assert "stream" in stats
        assert stats["stream"]["total_appended"] == 1

    def test_get_event_bus_returns_stream_variant(self):
        """get_event_bus(use_stream=True) returns EventBusWithStream."""
        import src.core.event_bus as eb
        # Reset singleton for test isolation
        eb._bus = None
        try:
            bus = eb.get_event_bus(use_stream=True)
            assert isinstance(bus, eb.EventBusWithStream)
        finally:
            eb._bus = None

    def test_get_event_bus_plain_variant(self):
        """get_event_bus(use_stream=False) returns plain EventBus."""
        import src.core.event_bus as eb
        eb._bus = None
        try:
            bus = eb.get_event_bus(use_stream=False)
            assert type(bus) is eb.EventBus
        finally:
            eb._bus = None

    def test_wait_stream_timeout(self, tmp_path):
        """wait_stream returns timed_out=True when no events arrive."""
        from src.core.event_bus import EventBusWithStream

        bus = EventBusWithStream(db_path=str(tmp_path / "test_bus.db"))
        events, cursor, timed_out = bus.wait_stream(after=0, timeout=0.1)
        assert timed_out is True
        assert len(events) == 0


# ═══════════════════════════════════════════════════════════════════
# 3. future_gate → group_orchestration
# ═══════════════════════════════════════════════════════════════════

class TestFutureGateIntegration:
    """Test that GroupOrchestrationSupervisor uses FutureGate for BATCH mode."""

    def test_supervisor_has_gate(self):
        """Supervisor should initialize with a FutureGate."""
        from src.governance.group_orchestration import GroupOrchestrationSupervisor
        sup = GroupOrchestrationSupervisor()
        assert sup._gate is not None

    def test_gate_basic_coordination(self):
        """FutureGate: open → provide → wait works end-to-end."""
        from src.core.future_gate import FutureGate

        gate = FutureGate()
        gate_id = gate.open(label="test")

        def provide_later():
            time.sleep(0.05)
            gate.provide(gate_id, {"result": "ok"})

        t = threading.Thread(target=provide_later)
        t.start()
        result = gate.wait(gate_id, timeout=2.0)
        t.join()
        assert result == {"result": "ok"}

    def test_gate_timeout(self):
        """FutureGate: wait times out if not provided."""
        from src.core.future_gate import FutureGate, GateTimeout

        gate = FutureGate()
        gate_id = gate.open(label="timeout-test")
        with pytest.raises(GateTimeout):
            gate.wait(gate_id, timeout=0.1)

    def test_gate_cancel(self):
        """FutureGate: cancel triggers GateCancelled."""
        from src.core.future_gate import FutureGate, GateCancelled

        gate = FutureGate()
        gate_id = gate.open(label="cancel-test")

        def cancel_later():
            time.sleep(0.05)
            gate.cancel(gate_id, reason="test cancel")

        t = threading.Thread(target=cancel_later)
        t.start()
        with pytest.raises(GateCancelled):
            gate.wait(gate_id, timeout=2.0)
        t.join()

    def test_supervisor_gate_timeout_config(self):
        """Supervisor respects gate_timeout parameter."""
        from src.governance.group_orchestration import GroupOrchestrationSupervisor
        sup = GroupOrchestrationSupervisor(gate_timeout=60.0)
        assert sup._gate_timeout == 60.0


# ═══════════════════════════════════════════════════════════════════
# 4. function_catalog → tool_policy
# ═══════════════════════════════════════════════════════════════════

class TestFunctionCatalogIntegration:
    """Test that ToolPolicy uses FunctionCatalog for parameter validation."""

    def test_validate_params_required_present(self):
        """Validation passes when all required params are provided."""
        from src.governance.policy.tool_policy import ToolPolicy

        def my_tool(name: str, count: int, verbose: bool = False):
            """A test tool."""
            pass

        policy = ToolPolicy()
        valid, errors = policy.validate_params(my_tool, {"name": "test", "count": 5})
        assert valid is True
        assert errors == []

    def test_validate_params_missing_required(self):
        """Validation fails when required params are missing."""
        from src.governance.policy.tool_policy import ToolPolicy

        def my_tool(name: str, count: int):
            """A test tool."""
            pass

        policy = ToolPolicy()
        valid, errors = policy.validate_params(my_tool, {"name": "test"})
        assert valid is False
        assert any("count" in e for e in errors)

    def test_validate_params_wrong_type(self):
        """Validation fails when param type is wrong."""
        from src.governance.policy.tool_policy import ToolPolicy

        def my_tool(name: str, count: int):
            """A test tool."""
            pass

        policy = ToolPolicy()
        valid, errors = policy.validate_params(my_tool, {"name": "test", "count": "not_int"})
        assert valid is False
        assert any("count" in e and "integer" in e for e in errors)

    def test_validate_params_extra_params_ok(self):
        """Extra parameters (not in schema) are allowed."""
        from src.governance.policy.tool_policy import ToolPolicy

        def my_tool(name: str):
            """A test tool."""
            pass

        policy = ToolPolicy()
        valid, errors = policy.validate_params(my_tool, {"name": "test", "extra": 42})
        assert valid is True

    def test_introspect_tool(self):
        """introspect_tool returns the function's schema."""
        from src.governance.policy.tool_policy import ToolPolicy

        def my_tool(name: str, count: int = 0):
            """A test tool that does things."""
            pass

        policy = ToolPolicy()
        schema = policy.introspect_tool(my_tool)
        assert schema is not None
        assert schema["name"] == "my_tool"
        assert "name" in schema["json_schema"]["properties"]
        assert "count" in schema["json_schema"]["properties"]
        assert "name" in schema["json_schema"]["required"]

    def test_introspect_tool_with_annotated(self):
        """introspect_tool handles Annotated types."""
        from typing import Annotated
        from src.governance.policy.tool_policy import ToolPolicy
        from src.core.function_catalog import ParamMeta

        def my_tool(
            name: Annotated[str, ParamMeta(description="The tool name")],
        ):
            """Annotated tool."""
            pass

        policy = ToolPolicy()
        schema = policy.introspect_tool(my_tool)
        assert schema is not None
        props = schema["json_schema"]["properties"]
        assert props["name"]["type"] == "string"

    def test_validate_with_defaults(self):
        """Parameters with defaults are not required."""
        from src.governance.policy.tool_policy import ToolPolicy

        def my_tool(name: str, verbose: bool = False, count: int = 1):
            """A tool with defaults."""
            pass

        policy = ToolPolicy()
        valid, errors = policy.validate_params(my_tool, {"name": "hello"})
        assert valid is True
        assert errors == []
