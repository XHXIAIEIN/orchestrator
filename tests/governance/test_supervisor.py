"""
tests/governance/test_supervisor.py

RuntimeSupervisor 单元测试 — 覆盖三类检测模式：
  - 签名重复 (signature_repeat)
  - 编辑抖动 (edit_thrashing)
  - 空转循环 (unproductive_loop)
"""
import pytest
from src.governance.supervisor import (
    InterventionLevel,
    RuntimeSupervisor,
)


# ── 签名重复 ─────────────────────────────────────────────────────────────────

class TestSignatureRepeat:
    """签名重复检测测试。"""

    def test_no_repeat_no_intervention(self):
        """3 个不同工具调用 → 无干预。"""
        sv = RuntimeSupervisor()
        sv.record_tool_call("Edit",   {"path": "a.py"})
        sv.record_tool_call("Read",   {"path": "b.py"})
        sv.record_tool_call("Bash",   {"command": "ls"})
        result = sv.evaluate(iteration=1)
        assert result is None

    def test_3_repeats_nudge(self):
        """同一工具+参数重复 3 次 → NUDGE，pattern = 'signature_repeat'。"""
        sv = RuntimeSupervisor()
        for _ in range(3):
            sv.record_tool_call("Bash", {"command": "pytest"})
        result = sv.evaluate(iteration=1)
        assert result is not None
        assert result.level == InterventionLevel.NUDGE
        assert result.pattern == "signature_repeat"

    def test_5_repeats_terminate(self):
        """同一工具+参数重复 5 次 → TERMINATE。"""
        sv = RuntimeSupervisor()
        for _ in range(5):
            sv.record_tool_call("Bash", {"command": "pytest"})
        result = sv.evaluate(iteration=1)
        assert result is not None
        assert result.level == InterventionLevel.TERMINATE
        assert result.pattern == "signature_repeat"

    def test_different_params_no_repeat(self):
        """同一工具但参数不同，重复 5 次 → None（签名各异）。"""
        sv = RuntimeSupervisor()
        for i in range(5):
            sv.record_tool_call("Bash", {"command": f"echo {i}"})
        result = sv.evaluate(iteration=1)
        assert result is None


# ── 编辑抖动 ─────────────────────────────────────────────────────────────────

class TestEditThrashing:
    """编辑抖动检测测试。"""

    def test_no_thrash_different_files(self):
        """在不同文件上交替读写 → None。"""
        sv = RuntimeSupervisor()
        files = ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py"]
        for f in files:
            sv.record_tool_call("Read", {"path": f})
            sv.record_tool_call("Edit", {"path": f})
        result = sv.evaluate(iteration=1)
        assert result is None

    def test_thrash_same_file(self):
        """同一文件 Read→Edit 交替 3 次 → NUDGE，pattern = 'edit_thrashing'。

        Read 用不同 offset 参数避免触发签名重复，Edit 用不同 content 参数同理。
        """
        sv = RuntimeSupervisor()
        for i in range(3):
            sv.record_tool_call("Read", {"path": "main.py", "offset": i})
            sv.record_tool_call("Edit", {"path": "main.py", "content": f"patch_{i}"})
        result = sv.evaluate(iteration=1)
        assert result is not None
        assert result.level == InterventionLevel.NUDGE
        assert result.pattern == "edit_thrashing"


# ── 空转循环 ─────────────────────────────────────────────────────────────────

class TestUnproductive:
    """空转循环检测测试。"""

    def test_productive_no_alert(self):
        """5 轮均有 Edit 调用（生产性工具）→ None。

        每轮 content 不同，避免触发签名重复。
        """
        sv = RuntimeSupervisor()
        for i in range(5):
            sv.record_tool_call("Edit", {"path": "x.py", "content": f"line_{i}"})
            sv.end_turn()
        result = sv.evaluate(iteration=1)
        assert result is None

    def test_idle_triggers_nudge(self):
        """5 轮只调用 TodoWrite（管理工具）→ NUDGE，pattern = 'unproductive_loop'。

        todos 列表各不相同，避免触发签名重复，专注测试空转计数逻辑。
        """
        sv = RuntimeSupervisor()
        for i in range(5):
            sv.record_tool_call("TodoWrite", {"todos": [i]})
            sv.end_turn()
        result = sv.evaluate(iteration=1)
        assert result is not None
        assert result.level == InterventionLevel.NUDGE
        assert result.pattern == "unproductive_loop"
