"""
tests/governance/test_supervisor.py

RuntimeSupervisor 单元测试 -- 9 个检测器 x 5 级干预。
"""
import pytest
from src.governance.supervisor import (
    InterventionLevel,
    RuntimeSupervisor,
    SupervisorDecision,
)


def _worst(decisions: list[SupervisorDecision]) -> SupervisorDecision | None:
    """取列表中最严重的决定，空列表返回 None。"""
    return decisions[0] if decisions else None


# ── 签名重复 (保留检测器) ────────────────────────────────────────────────────

class TestSignatureRepeat:
    """签名重复检测测试。"""

    def test_no_repeat_no_intervention(self):
        sv = RuntimeSupervisor()
        sv.record_tool_call("Edit",   {"path": "a.py"})
        sv.record_tool_call("Read",   {"path": "b.py"})
        sv.record_tool_call("Bash",   {"command": "ls"})
        assert _worst(sv.evaluate(iteration=1)) is None

    def test_3_repeats_nudge(self):
        sv = RuntimeSupervisor()
        for _ in range(3):
            sv.record_tool_call("Bash", {"command": "pytest"})
        d = _worst(sv.evaluate(iteration=1))
        assert d is not None
        assert d.level == InterventionLevel.NUDGE
        assert d.pattern == "signature_repeat"

    def test_5_repeats_terminate(self):
        sv = RuntimeSupervisor()
        for _ in range(5):
            sv.record_tool_call("Bash", {"command": "pytest"})
        d = _worst(sv.evaluate(iteration=1))
        assert d is not None
        assert d.level == InterventionLevel.TERMINATE
        assert d.pattern == "signature_repeat"

    def test_different_params_no_repeat(self):
        sv = RuntimeSupervisor()
        for i in range(5):
            sv.record_tool_call("Bash", {"command": f"echo {i}"})
        assert _worst(sv.evaluate(iteration=1)) is None


# ── #1 Edit Jitter ───────────────────────────────────────────────────────

class TestEditJitter:
    """同一文件在 N 轮内被编辑 3+ 次 → NUDGE。"""

    def test_no_jitter_different_files(self):
        sv = RuntimeSupervisor()
        for i in range(5):
            sv.record_tool_call("Edit", {"path": f"file_{i}.py", "content": "x"})
            sv.end_turn()
        decisions = sv.evaluate()
        jitter = [d for d in decisions if d.detector_name == "edit_jitter"]
        assert len(jitter) == 0

    def test_jitter_same_file(self):
        sv = RuntimeSupervisor()
        for i in range(3):
            sv.record_tool_call("Edit", {"path": "main.py", "content": f"v{i}"})
            sv.end_turn()
        decisions = sv.evaluate()
        jitter = [d for d in decisions if d.detector_name == "edit_jitter"]
        assert len(jitter) == 1
        assert jitter[0].level == InterventionLevel.NUDGE


# ── #2 Reasoning Loop ───────────────────────────────────────────────────

class TestReasoningLoop:
    """相同推理模式重复 → STRATEGY_SWITCH。"""

    def test_no_loop_different_reasoning(self):
        sv = RuntimeSupervisor()
        for i in range(5):
            sv.record_reasoning(f"completely different thought {i}")
        decisions = sv.evaluate()
        loop = [d for d in decisions if d.detector_name == "reasoning_loop"]
        assert len(loop) == 0

    def test_loop_triggers_strategy_switch(self):
        sv = RuntimeSupervisor()
        for _ in range(4):
            sv.record_reasoning("I should try reading the file again")
        decisions = sv.evaluate()
        loop = [d for d in decisions if d.detector_name == "reasoning_loop"]
        assert len(loop) == 1
        assert loop[0].level == InterventionLevel.STRATEGY_SWITCH


# ── #3 Token Anomaly ─────────────────────────────────────────────────────

class TestTokenAnomaly:
    """单轮 token 占预算 >50% → NUDGE。"""

    def test_normal_usage_no_alert(self):
        sv = RuntimeSupervisor(context_budget=200_000)
        sv.record_turn_tokens(input_tokens=5000, output_tokens=5000)
        decisions = sv.evaluate()
        anomaly = [d for d in decisions if d.detector_name == "token_anomaly"]
        assert len(anomaly) == 0

    def test_heavy_turn_triggers_nudge(self):
        sv = RuntimeSupervisor(context_budget=200_000)
        sv.record_turn_tokens(input_tokens=80_000, output_tokens=30_000)
        decisions = sv.evaluate()
        anomaly = [d for d in decisions if d.detector_name == "token_anomaly"]
        assert len(anomaly) == 1
        assert anomaly[0].level == InterventionLevel.NUDGE


# ── #4 Idle Spin ─────────────────────────────────────────────────────────

class TestIdleSpin:
    """3+ 轮无工具调用 → STRATEGY_SWITCH。"""

    def test_active_turns_no_alert(self):
        sv = RuntimeSupervisor()
        for i in range(5):
            sv.record_tool_call("Edit", {"path": f"f{i}.py", "content": "x"})
            sv.end_turn()
        decisions = sv.evaluate()
        idle = [d for d in decisions if d.detector_name == "idle_spin"]
        assert len(idle) == 0

    def test_idle_triggers_strategy_switch(self):
        sv = RuntimeSupervisor()
        for _ in range(3):
            sv.end_turn()  # 无工具调用
        decisions = sv.evaluate()
        idle = [d for d in decisions if d.detector_name == "idle_spin"]
        assert len(idle) == 1
        assert idle[0].level == InterventionLevel.STRATEGY_SWITCH


# ── #5 Error Cascade ─────────────────────────────────────────────────────

class TestErrorCascade:
    """3+ 连续工具错误 → MODEL_SWITCH。"""

    def test_mixed_results_no_cascade(self):
        sv = RuntimeSupervisor()
        sv.record_tool_result(success=False)
        sv.record_tool_result(success=True)
        sv.record_tool_result(success=False)
        decisions = sv.evaluate()
        cascade = [d for d in decisions if d.detector_name == "error_cascade"]
        assert len(cascade) == 0

    def test_consecutive_errors_trigger_model_switch(self):
        sv = RuntimeSupervisor()
        for _ in range(3):
            sv.record_tool_result(success=False)
        decisions = sv.evaluate()
        cascade = [d for d in decisions if d.detector_name == "error_cascade"]
        assert len(cascade) == 1
        assert cascade[0].level == InterventionLevel.MODEL_SWITCH

    def test_success_resets_counter(self):
        sv = RuntimeSupervisor()
        sv.record_tool_result(success=False)
        sv.record_tool_result(success=False)
        sv.record_tool_result(success=True)  # 重置
        sv.record_tool_result(success=False)
        decisions = sv.evaluate()
        cascade = [d for d in decisions if d.detector_name == "error_cascade"]
        assert len(cascade) == 0


# ── #6 Output Regression ────────────────────────────────────────────────

class TestOutputRegression:
    """输出长度连续缩短 + 下降超 50% → NUDGE。"""

    def test_stable_output_no_alert(self):
        sv = RuntimeSupervisor()
        for _ in range(5):
            sv.record_output_length(500)
        decisions = sv.evaluate()
        reg = [d for d in decisions if d.detector_name == "output_regression"]
        assert len(reg) == 0

    def test_shrinking_output_triggers_nudge(self):
        sv = RuntimeSupervisor()
        for length in [1000, 700, 400, 200]:
            sv.record_output_length(length)
        decisions = sv.evaluate()
        reg = [d for d in decisions if d.detector_name == "output_regression"]
        assert len(reg) == 1
        assert reg[0].level == InterventionLevel.NUDGE

    def test_slight_shrink_no_trigger(self):
        """缩短但未跌破 50% → 不触发。"""
        sv = RuntimeSupervisor()
        for length in [1000, 900, 800, 700]:
            sv.record_output_length(length)
        decisions = sv.evaluate()
        reg = [d for d in decisions if d.detector_name == "output_regression"]
        assert len(reg) == 0


# ── #7 Scope Creep ──────────────────────────────────────────────────────

class TestScopeCreep:
    """触及范围外文件 → NUDGE。"""

    def test_in_scope_no_alert(self):
        sv = RuntimeSupervisor(task_scope=["/src/governance/"])
        sv.record_tool_call("Edit", {"path": "/src/governance/supervisor.py", "content": "x"})
        decisions = sv.evaluate()
        creep = [d for d in decisions if d.detector_name == "scope_creep"]
        assert len(creep) == 0

    def test_out_of_scope_triggers_nudge(self):
        sv = RuntimeSupervisor(task_scope=["/src/governance/"])
        sv.record_tool_call("Edit", {"path": "/src/channels/telegram.py", "content": "x"})
        decisions = sv.evaluate()
        creep = [d for d in decisions if d.detector_name == "scope_creep"]
        assert len(creep) == 1
        assert creep[0].level == InterventionLevel.NUDGE

    def test_no_scope_means_no_check(self):
        """未设置 task_scope → 不检查 scope creep。"""
        sv = RuntimeSupervisor()  # no task_scope
        sv.record_tool_call("Edit", {"path": "/anywhere/file.py", "content": "x"})
        decisions = sv.evaluate()
        creep = [d for d in decisions if d.detector_name == "scope_creep"]
        assert len(creep) == 0


# ── #8 Context Exhaustion ───────────────────────────────────────────────

class TestContextExhaustion:
    """上下文占用 >85% → MODEL_SWITCH。"""

    def test_low_usage_no_alert(self):
        sv = RuntimeSupervisor(context_budget=200_000)
        sv.record_turn_tokens(input_tokens=10_000, output_tokens=5_000)
        decisions = sv.evaluate()
        exh = [d for d in decisions if d.detector_name == "context_exhaustion"]
        assert len(exh) == 0

    def test_high_usage_triggers_model_switch(self):
        sv = RuntimeSupervisor(context_budget=200_000)
        sv.record_turn_tokens(input_tokens=100_000, output_tokens=80_000)
        decisions = sv.evaluate()
        exh = [d for d in decisions if d.detector_name == "context_exhaustion"]
        assert len(exh) == 1
        assert exh[0].level == InterventionLevel.MODEL_SWITCH


# ── evaluate 排序 + evaluate_worst 兼容 ─────────────────────────────────

class TestEvaluateIntegration:
    """evaluate() 返回按严重度降序排列的决定列表。"""

    def test_multiple_detectors_sorted_by_severity(self):
        """同时触发 idle_spin(STRATEGY_SWITCH) + error_cascade(MODEL_SWITCH)。"""
        sv = RuntimeSupervisor()
        for _ in range(3):
            sv.end_turn()  # idle_spin
            sv.record_tool_result(success=False)  # error_cascade
        decisions = sv.evaluate()
        assert len(decisions) >= 2
        # 最严重的在前
        assert decisions[0].level >= decisions[1].level

    def test_evaluate_worst_compat(self):
        """evaluate_worst() 返回单个最严重干预。"""
        sv = RuntimeSupervisor()
        for _ in range(3):
            sv.end_turn()
        d = sv.evaluate_worst()
        assert d is not None
        assert d.detector_name == "idle_spin"

    def test_evaluate_worst_returns_none_when_clean(self):
        sv = RuntimeSupervisor()
        sv.record_tool_call("Edit", {"path": "a.py", "content": "x"})
        sv.end_turn()
        assert sv.evaluate_worst() is None


# ── StuckDetector 集成 ──────────────────────────────────────────────────

class TestStuckDetectorIntegration:
    """integrate_stuck_detector + should_escalate → ESCALATE。"""

    def test_stuck_detector_escalation(self):
        class FakeStuckDetector:
            def should_escalate(self):
                return True, "EDIT_LOOP failed 5x"
        sv = RuntimeSupervisor()
        sv.integrate_stuck_detector(FakeStuckDetector())
        decisions = sv.evaluate()
        stuck = [d for d in decisions if d.detector_name == "stuck_persistent"]
        assert len(stuck) == 1
        assert stuck[0].level == InterventionLevel.ESCALATE

    def test_stuck_detector_no_escalation(self):
        class FakeStuckDetector:
            def should_escalate(self):
                return False, ""
        sv = RuntimeSupervisor()
        sv.integrate_stuck_detector(FakeStuckDetector())
        sv.record_tool_call("Edit", {"path": "a.py", "content": "x"})
        sv.end_turn()
        decisions = sv.evaluate()
        stuck = [d for d in decisions if d.detector_name == "stuck_persistent"]
        assert len(stuck) == 0


# ── 向后兼容: .pattern / .message 属性 ──────────────────────────────────

class TestBackwardCompat:
    """SupervisorDecision.pattern 和 .message 属性保持向后兼容。"""

    def test_pattern_is_detector_name(self):
        d = SupervisorDecision(
            level=InterventionLevel.NUDGE,
            detector_name="test_detector",
            reason="test reason",
        )
        assert d.pattern == "test_detector"
        assert d.message == "test reason"
