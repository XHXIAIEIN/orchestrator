"""Tests for AgentRuntime — type-safe DI container (R68 LangGraph steal)."""
import pytest
from src.core.runtime import AgentRuntime


def _make_runtime(**overrides) -> AgentRuntime:
    """Factory with sensible defaults for testing."""
    defaults = dict(
        task_id=1,
        session_id="test-session-001",
        prompt="Do something",
        dept_prompt="You are an engineer.",
        allowed_tools=("Read", "Write", "Bash"),
        cwd="/tmp/test",
        max_turns=25,
    )
    defaults.update(overrides)
    return AgentRuntime(**defaults)


class TestAgentRuntimeBasics:
    def test_construction(self):
        rt = _make_runtime()
        assert rt.task_id == 1
        assert rt.session_id == "test-session-001"
        assert rt.allowed_tools == ("Read", "Write", "Bash")
        assert rt.cwd == "/tmp/test"
        assert rt.max_turns == 25
        assert rt.timeout_s is None

    def test_frozen_prevents_mutation(self):
        rt = _make_runtime()
        with pytest.raises(AttributeError):
            rt.task_id = 99  # type: ignore
        with pytest.raises(AttributeError):
            rt.prompt = "hacked"  # type: ignore

    def test_slots_no_dict(self):
        rt = _make_runtime()
        assert not hasattr(rt, "__dict__")

    def test_allowed_tools_is_tuple(self):
        """Tuple enforces immutability at data structure level."""
        rt = _make_runtime()
        assert isinstance(rt.allowed_tools, tuple)
        with pytest.raises(AttributeError):
            rt.allowed_tools.append("Grep")  # type: ignore

    def test_metadata_defaults(self):
        rt = _make_runtime()
        assert rt.department == ""
        assert rt.project == ""
        assert rt.model == ""
        assert rt.tier_name == ""
        assert rt.cognitive_mode == ""
        assert rt.extra is None


class TestAgentRuntimeOverride:
    def test_override_creates_new_instance(self):
        rt = _make_runtime()
        rt2 = rt.override(task_id=42)
        assert rt2.task_id == 42
        assert rt.task_id == 1  # original unchanged
        assert rt2 is not rt

    def test_override_preserves_other_fields(self):
        rt = _make_runtime(department="research", model="sonnet")
        rt2 = rt.override(max_turns=50)
        assert rt2.max_turns == 50
        assert rt2.department == "research"
        assert rt2.model == "sonnet"
        assert rt2.prompt == rt.prompt

    def test_override_list_to_tuple_conversion(self):
        """Callers may pass list — override() auto-converts to tuple."""
        rt = _make_runtime()
        rt2 = rt.override(allowed_tools=["Grep", "Read"])
        assert rt2.allowed_tools == ("Grep", "Read")
        assert isinstance(rt2.allowed_tools, tuple)

    def test_override_multiple_fields(self):
        rt = _make_runtime()
        rt2 = rt.override(task_id=99, cwd="/new/path", timeout_s=300.0)
        assert rt2.task_id == 99
        assert rt2.cwd == "/new/path"
        assert rt2.timeout_s == 300.0


class TestAgentRuntimeForSubtask:
    def test_for_subtask_overrides_task_id_and_prompt(self):
        parent = _make_runtime(department="engineering", model="opus")
        child = parent.for_subtask(task_id=42, prompt="Sub-task prompt")
        assert child.task_id == 42
        assert child.prompt == "Sub-task prompt"
        # Inherited from parent
        assert child.department == "engineering"
        assert child.model == "opus"
        assert child.dept_prompt == parent.dept_prompt
        assert child.allowed_tools == parent.allowed_tools

    def test_for_subtask_with_extra_overrides(self):
        parent = _make_runtime()
        child = parent.for_subtask(
            task_id=42,
            prompt="Sub-task",
            cwd="/tmp/subtask",
            max_turns=10,
        )
        assert child.cwd == "/tmp/subtask"
        assert child.max_turns == 10


class TestAgentRuntimeEquality:
    def test_same_fields_are_equal(self):
        rt1 = _make_runtime()
        rt2 = _make_runtime()
        assert rt1 == rt2

    def test_different_fields_are_not_equal(self):
        rt1 = _make_runtime(task_id=1)
        rt2 = _make_runtime(task_id=2)
        assert rt1 != rt2

    def test_hashable(self):
        """Frozen dataclass should be hashable."""
        rt = _make_runtime()
        h = hash(rt)
        assert isinstance(h, int)
