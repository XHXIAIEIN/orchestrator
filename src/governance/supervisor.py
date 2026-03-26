"""
RuntimeSupervisor — 运行时行为监督器。

灵感来自 OpenAkita，检测三类 agent 失控模式并分级干预：
  1. 签名重复 (signature_repeat)   — 同一工具+参数反复调用
  2. 编辑抖动 (edit_thrashing)     — 同一文件读写反复横跳
  3. 空转循环 (unproductive_loop)  — 连续多轮只用管理类工具

干预等级从低到高：NONE → NUDGE → STRATEGY_SWITCH → ESCALATE → TERMINATE
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

SIG_REPEAT_NUDGE = 3
SIG_REPEAT_TERMINATE = 5
EDIT_THRASH_THRESHOLD = 3
UNPRODUCTIVE_THRESHOLD = 5
SIG_WINDOW = 20

MANAGEMENT_TOOLS = frozenset({
    "TodoRead", "TodoWrite",
    "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
})


# ── 数据结构 ─────────────────────────────────────────────────────────────────

class InterventionLevel(IntEnum):
    NONE = 0
    NUDGE = 1             # 注入提示消息
    STRATEGY_SWITCH = 2   # 回滚 + 切换策略
    ESCALATE = 3          # 请求人工干预
    TERMINATE = 4         # 安全终止


@dataclass
class Intervention:
    level: InterventionLevel
    pattern: str    # 检测模式名称
    message: str    # 给 agent / 日志的消息
    details: dict = field(default_factory=dict)


# ── 核心类 ──────────────────────────────────────────────────────────────────

class RuntimeSupervisor:
    """运行时 agent 行为监督器。

    使用方式：
        supervisor = RuntimeSupervisor()
        supervisor.record_tool_call("Edit", {"path": "/foo.py", "content": "..."})
        supervisor.end_turn()
        intervention = supervisor.evaluate(iteration=3)
        if intervention:
            handle(intervention)
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """清空所有状态。"""
        # 签名重复：滑动窗口，存储 (sig, tool_name) 元组
        self._sig_window: list[tuple[str, str]] = []
        # 编辑抖动：每个文件的操作历史 {"path": str, "op": "read"|"write"}
        self._file_ops: list[dict] = []
        # 空转计数：连续全管理工具的轮次数
        self._idle_turns: int = 0
        # 当前轮次是否有非管理工具调用
        self._current_turn_productive: bool = False

    # ── 记录接口 ──────────────────────────────────────────────────────────

    def record_tool_call(self, tool_name: str, params: dict) -> None:
        """记录一次工具调用。

        Args:
            tool_name: 工具名称
            params:    工具参数字典
        """
        sig = self._make_sig(tool_name, params)
        self._sig_window.append((sig, tool_name))
        # 窗口裁剪，避免无限增长
        if len(self._sig_window) > SIG_WINDOW * 2:
            self._sig_window = self._sig_window[-SIG_WINDOW:]

        # 记录文件操作（Read / Edit / Write 类工具）
        op = self._classify_file_op(tool_name, params)
        if op is not None:
            path, kind = op
            self._file_ops.append({"path": path, "op": kind})
            if len(self._file_ops) > SIG_WINDOW * 2:
                self._file_ops = self._file_ops[-SIG_WINDOW:]

        # 标记当前轮次是否有生产性工具调用
        if tool_name not in MANAGEMENT_TOOLS:
            self._current_turn_productive = True

    def end_turn(self) -> None:
        """标记一轮对话结束，更新空转计数器。"""
        if self._current_turn_productive:
            self._idle_turns = 0
        else:
            self._idle_turns += 1
        self._current_turn_productive = False

    # ── 评估接口 ──────────────────────────────────────────────────────────

    def evaluate(self, iteration: int) -> Optional[Intervention]:
        """评估当前状态，返回最严重的干预建议。

        Args:
            iteration: 当前迭代编号（用于日志）

        Returns:
            最严重的 Intervention，无问题则返回 None
        """
        candidates: list[Intervention] = []

        sig_iv = self._check_signature_repeat()
        if sig_iv:
            candidates.append(sig_iv)

        thrash_iv = self._check_edit_thrashing()
        if thrash_iv:
            candidates.append(thrash_iv)

        idle_iv = self._check_unproductive_loop()
        if idle_iv:
            candidates.append(idle_iv)

        if not candidates:
            return None

        worst = max(candidates, key=lambda iv: iv.level)
        log.warning(
            "[supervisor] iter=%d pattern=%s level=%s: %s",
            iteration, worst.pattern, worst.level.name, worst.message,
        )
        return worst

    # ── 内部检测逻辑 ──────────────────────────────────────────────────────

    def _check_signature_repeat(self) -> Optional[Intervention]:
        """检测签名重复：同一工具+参数在窗口内出现多次。"""
        window = self._sig_window[-SIG_WINDOW:]
        counts: dict[str, int] = defaultdict(int)
        for sig, _ in window:
            counts[sig] += 1

        max_count = max(counts.values(), default=0)
        if max_count >= SIG_REPEAT_TERMINATE:
            # 找出重复最多的签名对应的工具名
            worst_sig = max(counts, key=lambda s: counts[s])
            tool = next(t for s, t in window if s == worst_sig)
            return Intervention(
                level=InterventionLevel.TERMINATE,
                pattern="signature_repeat",
                message=f"工具 {tool!r} 签名重复 {max_count} 次，触发终止阈值",
                details={"count": max_count, "tool": tool},
            )
        if max_count >= SIG_REPEAT_NUDGE:
            worst_sig = max(counts, key=lambda s: counts[s])
            tool = next(t for s, t in window if s == worst_sig)
            return Intervention(
                level=InterventionLevel.NUDGE,
                pattern="signature_repeat",
                message=f"工具 {tool!r} 签名重复 {max_count} 次，请尝试不同方法",
                details={"count": max_count, "tool": tool},
            )
        return None

    def _check_edit_thrashing(self) -> Optional[Intervention]:
        """检测编辑抖动：同一文件读→写或写→读交替 3+ 次。"""
        # 按文件分组，统计交替次数
        by_file: dict[str, list[str]] = defaultdict(list)
        for entry in self._file_ops[-SIG_WINDOW:]:
            by_file[entry["path"]].append(entry["op"])

        for path, ops in by_file.items():
            alternations = sum(
                1 for i in range(1, len(ops)) if ops[i] != ops[i - 1]
            )
            if alternations >= EDIT_THRASH_THRESHOLD:
                return Intervention(
                    level=InterventionLevel.NUDGE,
                    pattern="edit_thrashing",
                    message=f"文件 {path!r} 读写交替 {alternations} 次，可能陷入抖动",
                    details={"path": path, "alternations": alternations, "ops": ops},
                )
        return None

    def _check_unproductive_loop(self) -> Optional[Intervention]:
        """检测空转循环：连续多轮只调用管理类工具。"""
        if self._idle_turns >= UNPRODUCTIVE_THRESHOLD:
            return Intervention(
                level=InterventionLevel.NUDGE,
                pattern="unproductive_loop",
                message=f"连续 {self._idle_turns} 轮未调用生产性工具，请检查是否卡住",
                details={"idle_turns": self._idle_turns},
            )
        return None

    # ── 工具函数 ──────────────────────────────────────────────────────────

    @staticmethod
    def _make_sig(tool_name: str, params: dict) -> str:
        """生成工具调用签名：tool_name(md5(params)[:8])。"""
        raw = str(sorted(params.items())).encode()
        digest = hashlib.md5(raw).hexdigest()[:8]
        return f"{tool_name}({digest})"

    @staticmethod
    def _classify_file_op(
        tool_name: str, params: dict
    ) -> Optional[tuple[str, str]]:
        """将工具调用映射为文件操作 (path, "read"|"write")，无关工具返回 None。"""
        path = params.get("path") or params.get("file_path") or params.get("file")
        if not path:
            return None
        if tool_name in ("Read",):
            return str(path), "read"
        if tool_name in ("Edit", "Write"):
            return str(path), "write"
        return None
