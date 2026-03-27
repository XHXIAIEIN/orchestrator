"""
RuntimeSupervisor -- 运行时行为监督器。

8 检测模式 x 5 级干预 (OpenAkita R2):

检测器:
  1. edit_jitter       -- 同一文件 5 轮内编辑 3+ 次 → NUDGE
  2. reasoning_loop    -- 相同推理模式重复出现 → STRATEGY_SWITCH
  3. token_anomaly     -- 单轮 token 消耗 >50% 预算 → NUDGE
  4. idle_spin         -- 3+ 轮无工具调用 → STRATEGY_SWITCH
  5. error_cascade     -- 3+ 连续工具错误 → MODEL_SWITCH
  6. output_regression -- 输出长度持续缩短 → NUDGE
  7. scope_creep       -- 触及任务范围外文件 → NUDGE
  8. context_exhaustion-- 上下文占用 >85% → MODEL_SWITCH

干预等级:
  NUDGE(1) → STRATEGY_SWITCH(2) → MODEL_SWITCH(3) → ESCALATE(4) → TERMINATE(5)
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

log = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────────────────────

# 旧检测器阈值 (保留向后兼容)
SIG_REPEAT_NUDGE = 3
SIG_REPEAT_TERMINATE = 5
EDIT_THRASH_THRESHOLD = 3
UNPRODUCTIVE_THRESHOLD = 5
SIG_WINDOW = 20

# 新检测器阈值
EDIT_JITTER_EDITS = 3        # 同一文件在 N 轮内编辑次数
EDIT_JITTER_WINDOW = 5       # 轮次窗口
IDLE_SPIN_TURNS = 3          # 连续无工具调用轮次
ERROR_CASCADE_COUNT = 3      # 连续工具错误次数
OUTPUT_REGRESSION_TURNS = 4  # 输出长度连续缩短的轮次
CONTEXT_EXHAUSTION_RATIO = 0.85  # 上下文占用比例
TOKEN_ANOMALY_RATIO = 0.50   # 单轮 token 占预算比

MANAGEMENT_TOOLS = frozenset({
    "TodoRead", "TodoWrite",
    "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
})


# ── 数据结构 ─────────────────────────────────────────────────────────────────

class InterventionLevel(IntEnum):
    NUDGE = 1             # 温和提示，注入 system prompt
    STRATEGY_SWITCH = 2   # 切换策略 (换工具/换方法)
    MODEL_SWITCH = 3      # 降级/升级模型
    ESCALATE = 4          # 暂停，请求人工介入
    TERMINATE = 5         # 终止任务


@dataclass
class SupervisorDecision:
    """单个检测器的判定结果。"""
    level: InterventionLevel
    detector_name: str   # 检测器名称 (8 种之一)
    reason: str          # 人类可读的原因
    suggestion: str = "" # 给 agent 或调度器的建议动作
    details: dict = field(default_factory=dict)

    # 向后兼容: 旧代码用 .pattern 和 .message
    @property
    def pattern(self) -> str:
        return self.detector_name

    @property
    def message(self) -> str:
        return self.reason


# 向后兼容别名
Intervention = SupervisorDecision


# ── 核心类 ──────────────────────────────────────────────────────────────────

class RuntimeSupervisor:
    """运行时 agent 行为监督器 -- 8 检测 x 5 级干预。

    使用方式::

        supervisor = RuntimeSupervisor(task_scope=["/src/foo/"])
        supervisor.record_tool_call("Edit", {"path": "/src/foo/bar.py"})
        supervisor.record_tool_result(success=True)
        supervisor.record_turn_tokens(input_tokens=1200, output_tokens=800)
        supervisor.end_turn()

        decisions = supervisor.evaluate()
        for d in decisions:
            handle(d)

    与 StuckDetector 集成::

        from src.governance.stuck_detector import StuckDetector
        supervisor.integrate_stuck_detector(stuck_detector_instance)
    """

    def __init__(
        self,
        task_scope: list[str] | None = None,
        context_budget: int = 200_000,
    ) -> None:
        self._task_scope = task_scope or []  # 允许触及的路径前缀
        self._context_budget = context_budget
        self.reset()

    def reset(self) -> None:
        """清空所有状态。"""
        # ── 签名重复 (旧检测器) ──
        self._sig_window: list[tuple[str, str]] = []

        # ── 编辑抖动 / edit jitter ──
        self._file_ops: list[dict] = []  # {"path", "op", "turn"}
        self._current_turn: int = 0

        # ── 空转 / idle spin ──
        self._idle_turns: int = 0
        self._current_turn_has_tools: bool = False

        # ── 推理循环 / reasoning loop ──
        self._reasoning_sigs: list[str] = []

        # ── Token 异常 ──
        self._turn_tokens: list[dict] = []  # {"input", "output"}
        self._total_tokens_used: int = 0

        # ── 错误瀑布 / error cascade ──
        self._consecutive_errors: int = 0

        # ── 输出回归 / output regression ──
        self._output_lengths: list[int] = []

        # ── 范围蔓延 / scope creep ──
        self._out_of_scope_files: list[str] = []

        # ── StuckDetector 集成 ──
        self._stuck_detector = None

    # ── 记录接口 ──────────────────────────────────────────────────────────

    def record_tool_call(self, tool_name: str, params: dict) -> None:
        """记录一次工具调用。"""
        self._current_turn_has_tools = True

        # 签名窗口
        sig = self._make_sig(tool_name, params)
        self._sig_window.append((sig, tool_name))
        if len(self._sig_window) > SIG_WINDOW * 2:
            self._sig_window = self._sig_window[-SIG_WINDOW:]

        # 文件操作 (edit jitter + scope creep)
        op = self._classify_file_op(tool_name, params)
        if op is not None:
            path, kind = op
            self._file_ops.append({
                "path": path, "op": kind, "turn": self._current_turn,
            })
            if len(self._file_ops) > SIG_WINDOW * 2:
                self._file_ops = self._file_ops[-SIG_WINDOW:]

            # scope creep: 检查是否在允许范围外
            if self._task_scope and not self._path_in_scope(path):
                self._out_of_scope_files.append(path)

    def record_tool_result(self, success: bool) -> None:
        """记录工具执行结果 (成功/失败)。"""
        if success:
            self._consecutive_errors = 0
        else:
            self._consecutive_errors += 1

    def record_turn_tokens(
        self, input_tokens: int = 0, output_tokens: int = 0,
    ) -> None:
        """记录当轮 token 消耗。"""
        total = input_tokens + output_tokens
        self._turn_tokens.append({"input": input_tokens, "output": output_tokens})
        self._total_tokens_used += total
        if len(self._turn_tokens) > SIG_WINDOW * 2:
            self._turn_tokens = self._turn_tokens[-SIG_WINDOW:]

    def record_output_length(self, length: int) -> None:
        """记录当轮输出长度 (字符数或 token 数皆可)。"""
        self._output_lengths.append(length)
        if len(self._output_lengths) > SIG_WINDOW:
            self._output_lengths = self._output_lengths[-SIG_WINDOW:]

    def record_reasoning(self, reasoning_text: str) -> None:
        """记录当轮推理文本摘要 (用于检测推理循环)。"""
        sig = hashlib.md5(reasoning_text.strip()[:500].encode()).hexdigest()[:12]
        self._reasoning_sigs.append(sig)
        if len(self._reasoning_sigs) > SIG_WINDOW:
            self._reasoning_sigs = self._reasoning_sigs[-SIG_WINDOW:]

    def end_turn(self) -> None:
        """标记一轮结束。"""
        if not self._current_turn_has_tools:
            self._idle_turns += 1
        else:
            self._idle_turns = 0
        self._current_turn_has_tools = False
        self._current_turn += 1

    def integrate_stuck_detector(self, detector) -> None:
        """挂载 StuckDetector 实例，evaluate 时会查询 should_escalate()。"""
        self._stuck_detector = detector

    # ── 评估接口 ──────────────────────────────────────────────────────────

    def evaluate(self, iteration: int = 0) -> list[SupervisorDecision]:
        """运行全部 8 个检测器，返回触发的决定列表 (按严重度降序)。

        Args:
            iteration: 当前迭代编号 (用于日志)

        Returns:
            触发的 SupervisorDecision 列表，严重度降序。空列表表示正常。
        """
        decisions: list[SupervisorDecision] = []

        # 8 个新检测器 + 1 个保留检测器
        for checker in (
            self._check_signature_repeat,
            self._check_edit_jitter,
            self._check_reasoning_loop,
            self._check_token_anomaly,
            self._check_idle_spin,
            self._check_error_cascade,
            self._check_output_regression,
            self._check_scope_creep,
            self._check_context_exhaustion,
        ):
            d = checker()
            if d is not None:
                decisions.append(d)

        # StuckDetector 集成: persistent failure → ESCALATE
        if self._stuck_detector is not None:
            escalate, reason = self._stuck_detector.should_escalate()
            if escalate:
                decisions.append(SupervisorDecision(
                    level=InterventionLevel.ESCALATE,
                    detector_name="stuck_persistent",
                    reason=reason,
                    suggestion="多次尝试后仍失败，建议人工介入或更换策略",
                ))

        # 按严重度降序
        decisions.sort(key=lambda d: d.level, reverse=True)

        for d in decisions:
            log.warning(
                "[supervisor] iter=%d detector=%s level=%s: %s",
                iteration, d.detector_name, d.level.name, d.reason,
            )

        return decisions

    # ── 向后兼容: 旧 evaluate 返回单个 Intervention ──

    def evaluate_worst(self, iteration: int = 0) -> Optional[SupervisorDecision]:
        """向后兼容接口: 返回最严重的单个干预，无问题返回 None。"""
        decisions = self.evaluate(iteration)
        return decisions[0] if decisions else None

    # ── 检测器 (8 新 + 1 保留) ───────────────────────────────────────────

    def _check_signature_repeat(self) -> Optional[SupervisorDecision]:
        """保留检测器: 同一工具+参数在窗口内重复。"""
        window = self._sig_window[-SIG_WINDOW:]
        counts: dict[str, int] = defaultdict(int)
        for sig, _ in window:
            counts[sig] += 1

        max_count = max(counts.values(), default=0)
        if max_count >= SIG_REPEAT_TERMINATE:
            worst_sig = max(counts, key=lambda s: counts[s])
            tool = next(t for s, t in window if s == worst_sig)
            return SupervisorDecision(
                level=InterventionLevel.TERMINATE,
                detector_name="signature_repeat",
                reason=f"工具 {tool!r} 签名重复 {max_count} 次，触发终止阈值",
                details={"count": max_count, "tool": tool},
            )
        if max_count >= SIG_REPEAT_NUDGE:
            worst_sig = max(counts, key=lambda s: counts[s])
            tool = next(t for s, t in window if s == worst_sig)
            return SupervisorDecision(
                level=InterventionLevel.NUDGE,
                detector_name="signature_repeat",
                reason=f"工具 {tool!r} 签名重复 {max_count} 次，请尝试不同方法",
                details={"count": max_count, "tool": tool},
            )
        return None

    def _check_edit_jitter(self) -> Optional[SupervisorDecision]:
        """#1 Edit Jitter: 同一文件在最近 N 轮内被编辑 3+ 次 → NUDGE。"""
        min_turn = self._current_turn - EDIT_JITTER_WINDOW
        recent_writes: dict[str, int] = defaultdict(int)
        for entry in self._file_ops:
            if entry["turn"] >= min_turn and entry["op"] == "write":
                recent_writes[entry["path"]] += 1

        for path, count in recent_writes.items():
            if count >= EDIT_JITTER_EDITS:
                return SupervisorDecision(
                    level=InterventionLevel.NUDGE,
                    detector_name="edit_jitter",
                    reason=f"文件 {path!r} 在最近 {EDIT_JITTER_WINDOW} 轮内被编辑 {count} 次",
                    suggestion="先想清楚再改，避免反复修改同一文件",
                    details={"path": path, "edit_count": count, "window": EDIT_JITTER_WINDOW},
                )
        return None

    def _check_reasoning_loop(self) -> Optional[SupervisorDecision]:
        """#2 Reasoning Loop: 相同推理模式在最近窗口重复 → STRATEGY_SWITCH。"""
        if len(self._reasoning_sigs) < 3:
            return None
        window = self._reasoning_sigs[-8:]
        counts: dict[str, int] = defaultdict(int)
        for sig in window:
            counts[sig] += 1
        max_sig = max(counts, key=lambda s: counts[s])
        max_count = counts[max_sig]
        if max_count >= 3:
            return SupervisorDecision(
                level=InterventionLevel.STRATEGY_SWITCH,
                detector_name="reasoning_loop",
                reason=f"相同推理模式在最近 8 轮内重复 {max_count} 次",
                suggestion="换一个角度思考，尝试完全不同的方法",
                details={"repeat_count": max_count},
            )
        return None

    def _check_token_anomaly(self) -> Optional[SupervisorDecision]:
        """#3 Token Anomaly: 单轮 token 占预算 >50% → NUDGE。"""
        if not self._turn_tokens or self._context_budget <= 0:
            return None
        last = self._turn_tokens[-1]
        turn_total = last["input"] + last["output"]
        ratio = turn_total / self._context_budget
        if ratio > TOKEN_ANOMALY_RATIO:
            return SupervisorDecision(
                level=InterventionLevel.NUDGE,
                detector_name="token_anomaly",
                reason=f"单轮 token 消耗 {turn_total:,} ({ratio:.0%} of budget)",
                suggestion="减少单轮输出量，考虑分步执行",
                details={"turn_tokens": turn_total, "budget": self._context_budget, "ratio": ratio},
            )
        return None

    def _check_idle_spin(self) -> Optional[SupervisorDecision]:
        """#4 Idle Spin: 3+ 轮无工具调用 → STRATEGY_SWITCH。"""
        if self._idle_turns >= IDLE_SPIN_TURNS:
            return SupervisorDecision(
                level=InterventionLevel.STRATEGY_SWITCH,
                detector_name="idle_spin",
                reason=f"连续 {self._idle_turns} 轮没有工具调用",
                suggestion="停止空转，使用工具执行具体操作",
                details={"idle_turns": self._idle_turns},
            )
        return None

    def _check_error_cascade(self) -> Optional[SupervisorDecision]:
        """#5 Error Cascade: 3+ 连续工具错误 → MODEL_SWITCH。"""
        if self._consecutive_errors >= ERROR_CASCADE_COUNT:
            return SupervisorDecision(
                level=InterventionLevel.MODEL_SWITCH,
                detector_name="error_cascade",
                reason=f"连续 {self._consecutive_errors} 次工具调用失败",
                suggestion="切换模型或降级到更稳定的模型处理",
                details={"consecutive_errors": self._consecutive_errors},
            )
        return None

    def _check_output_regression(self) -> Optional[SupervisorDecision]:
        """#6 Output Regression: 输出长度连续缩短 → NUDGE。"""
        if len(self._output_lengths) < OUTPUT_REGRESSION_TURNS:
            return None
        recent = self._output_lengths[-OUTPUT_REGRESSION_TURNS:]
        # 检查是否严格递减
        shrinking = all(recent[i] > recent[i + 1] for i in range(len(recent) - 1))
        if shrinking and recent[-1] < recent[0] * 0.5:
            return SupervisorDecision(
                level=InterventionLevel.NUDGE,
                detector_name="output_regression",
                reason=f"输出长度连续 {OUTPUT_REGRESSION_TURNS} 轮缩短 ({recent[0]} → {recent[-1]})",
                suggestion="输出质量可能在下降，检查是否遗漏了重要内容",
                details={"lengths": recent},
            )
        return None

    def _check_scope_creep(self) -> Optional[SupervisorDecision]:
        """#7 Scope Creep: 触及任务范围外文件 → NUDGE。"""
        if not self._out_of_scope_files:
            return None
        unique = list(dict.fromkeys(self._out_of_scope_files))  # 去重保序
        return SupervisorDecision(
            level=InterventionLevel.NUDGE,
            detector_name="scope_creep",
            reason=f"触及 {len(unique)} 个范围外文件: {', '.join(unique[:3])}",
            suggestion="专注于任务范围内的文件，避免不相关的修改",
            details={"files": unique},
        )

    def _check_context_exhaustion(self) -> Optional[SupervisorDecision]:
        """#8 Context Exhaustion: 累计 token 占预算 >85% → MODEL_SWITCH。"""
        if self._context_budget <= 0 or self._total_tokens_used <= 0:
            return None
        ratio = self._total_tokens_used / self._context_budget
        if ratio > CONTEXT_EXHAUSTION_RATIO:
            return SupervisorDecision(
                level=InterventionLevel.MODEL_SWITCH,
                detector_name="context_exhaustion",
                reason=f"上下文已使用 {ratio:.0%} ({self._total_tokens_used:,}/{self._context_budget:,})",
                suggestion="切换到摘要模型压缩上下文，或终止当前尝试",
                details={"used": self._total_tokens_used, "budget": self._context_budget, "ratio": ratio},
            )
        return None

    # ── 工具函数 ──────────────────────────────────────────────────────────

    def _path_in_scope(self, path: str) -> bool:
        """检查路径是否在任务允许范围内。"""
        normalized = path.replace("\\", "/")
        return any(normalized.startswith(s.replace("\\", "/")) for s in self._task_scope)

    @staticmethod
    def _make_sig(tool_name: str, params: dict) -> str:
        """生成工具调用签名：tool_name(md5(params)[:8])。"""
        raw = str(sorted(params.items())).encode()
        digest = hashlib.md5(raw).hexdigest()[:8]
        return f"{tool_name}({digest})"

    @staticmethod
    def _classify_file_op(
        tool_name: str, params: dict,
    ) -> Optional[tuple[str, str]]:
        """将工具调用映射为文件操作 (path, "read"|"write")，无关工具返回 None。"""
        path = params.get("path") or params.get("file_path") or params.get("file")
        if not path:
            return None
        if tool_name in ("Read", "Glob"):
            return str(path), "read"
        if tool_name in ("Edit", "Write"):
            return str(path), "write"
        return None
