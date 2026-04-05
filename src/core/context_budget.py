# src/core/context_budget.py
"""
ContextBudget — 上下文窗口预算管理器，偷自 OpenFang context_budget.rs。
ContextLedger + SegmentBudget — per-segment 预算追踪，偷自 PraisonAI context/budgeter.py (R39).

双层动态截断：
  Layer 1: 单个工具结果不超过 context window 的 30%（硬限 50%）
  Layer 2: 总工具输出超过可用空间 75% 时，按时间序压缩最旧的结果

Segment 预算 (R39 新增):
  将 context window 按功能区划分预算:
    system: 2K, rules: 500, memory: 1K, tools_schema: 2K,
    tool_outputs: 20K, history: 动态余量
  ContextLedger 逐段追踪，超额预警。

用法:
    budget = ContextBudget(context_window_tokens=200_000)
    result = budget.trim_single(tool_output, tool_name="Bash")
    budget.record_output(tool_name, result)
    compressed = budget.compress_if_needed()

    # Segment 预算
    ledger = ContextLedger(context_window_tokens=200_000)
    ledger.record("system", 1800)
    ledger.record("tool_outputs", 15000)
    warnings = ledger.check_overflow()
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple

log = logging.getLogger(__name__)


# ── Segment Budget (R39 PraisonAI steal) ───────────────────────


class Segment(str, Enum):
    """Context window 功能区段。"""
    SYSTEM = "system"
    RULES = "rules"
    MEMORY = "memory"
    TOOLS_SCHEMA = "tools_schema"
    TOOL_OUTPUTS = "tool_outputs"
    HISTORY = "history"


# 默认 segment 预算 (tokens)。HISTORY 是动态余量，这里只定义固定段。
DEFAULT_SEGMENT_BUDGETS: dict[str, int] = {
    Segment.SYSTEM: 2_000,
    Segment.RULES: 500,
    Segment.MEMORY: 1_000,
    Segment.TOOLS_SCHEMA: 2_000,
    Segment.TOOL_OUTPUTS: 20_000,
    # HISTORY: 动态计算 = total - sum(fixed segments)
}


@dataclass
class SegmentEntry:
    """单个 segment 的预算与实际使用。"""
    budget: int
    used: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.used)

    @property
    def usage_pct(self) -> float:
        if self.budget <= 0:
            return 100.0 if self.used > 0 else 0.0
        return round(self.used / self.budget * 100, 1)

    @property
    def overflow(self) -> bool:
        return self.used > self.budget


@dataclass
class ContextLedger:
    """Per-segment token 预算追踪器。

    追踪 context window 各段的 token 用量, 超额时发出预警。
    HISTORY segment 的预算动态计算为: total - sum(固定段预算)。
    """

    context_window_tokens: int = 200_000
    segment_budgets: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_SEGMENT_BUDGETS))
    # 超额警告阈值 (占 segment 预算的百分比)
    warn_threshold_pct: float = 90.0

    _entries: dict[str, SegmentEntry] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        # 初始化固定段
        for seg, budget in self.segment_budgets.items():
            self._entries[seg] = SegmentEntry(budget=budget)
        # 动态计算 HISTORY 预算
        fixed_total = sum(self.segment_budgets.values())
        history_budget = max(0, self.context_window_tokens - fixed_total)
        self._entries[Segment.HISTORY] = SegmentEntry(budget=history_budget)

    def record(self, segment: str, tokens: int) -> SegmentEntry:
        """记录某段的 token 使用量 (累加)。"""
        if segment not in self._entries:
            # 未知 segment, 给一个无限预算
            self._entries[segment] = SegmentEntry(budget=self.context_window_tokens)
        entry = self._entries[segment]
        entry.used += tokens
        return entry

    def set_usage(self, segment: str, tokens: int) -> SegmentEntry:
        """设置某段的 token 使用量 (覆盖, 非累加)。"""
        if segment not in self._entries:
            self._entries[segment] = SegmentEntry(budget=self.context_window_tokens)
        self._entries[segment].used = tokens
        return self._entries[segment]

    def check_overflow(self) -> list[dict]:
        """检查所有段, 返回超额或接近超额的预警列表。"""
        warnings = []
        for seg, entry in self._entries.items():
            if entry.overflow:
                warnings.append({
                    "segment": seg,
                    "level": "overflow",
                    "budget": entry.budget,
                    "used": entry.used,
                    "over_by": entry.used - entry.budget,
                })
            elif entry.usage_pct >= self.warn_threshold_pct:
                warnings.append({
                    "segment": seg,
                    "level": "warning",
                    "budget": entry.budget,
                    "used": entry.used,
                    "usage_pct": entry.usage_pct,
                })
        return warnings

    @property
    def total_used(self) -> int:
        return sum(e.used for e in self._entries.values())

    @property
    def total_remaining(self) -> int:
        return max(0, self.context_window_tokens - self.total_used)

    @property
    def summary(self) -> dict:
        """各段用量摘要。"""
        segments = {}
        for seg, entry in self._entries.items():
            segments[seg] = {
                "budget": entry.budget,
                "used": entry.used,
                "remaining": entry.remaining,
                "usage_pct": entry.usage_pct,
            }
        return {
            "context_window": self.context_window_tokens,
            "total_used": self.total_used,
            "total_remaining": self.total_remaining,
            "segments": segments,
        }


class OutputRecord(NamedTuple):
    """单次工具输出记录。"""
    tool_name: str
    content: str
    char_count: int
    est_tokens: int
    turn: int


@dataclass
class ContextBudget:
    """上下文窗口预算管理器。"""

    context_window_tokens: int = 200_000
    # 工具输出更密集（代码/日志），每 token 约 2 字符
    tool_chars_per_token: float = 2.0
    # 一般文本每 token 约 4 字符
    general_chars_per_token: float = 4.0
    # 单结果上限占比
    single_result_soft: float = 0.30
    single_result_hard: float = 0.50
    # 总输出压缩触发阈值
    global_compress_threshold: float = 0.75

    _outputs: list[OutputRecord] = field(default_factory=list, repr=False)
    _turn: int = field(default=0, repr=False)
    _total_est_tokens: int = field(default=0, repr=False)

    def _estimate_tokens(self, text: str, is_tool: bool = True) -> int:
        """粗略估算 token 数。"""
        cpt = self.tool_chars_per_token if is_tool else self.general_chars_per_token
        return max(1, int(len(text) / cpt))

    def _utf8_safe_truncate(self, text: str, max_chars: int) -> str:
        """UTF-8 安全截断：不在多字节字符中间切断。"""
        if len(text) <= max_chars:
            return text
        # 回退到最近的完整字符
        truncated = text[:max_chars]
        # Python str 本身是 Unicode，不存在多字节切断问题
        # 但要处理 surrogate pair（罕见但存在）
        try:
            truncated.encode("utf-8")
        except UnicodeEncodeError:
            truncated = truncated[:-1]
        return truncated + "\n\n… [truncated by ContextBudget]"

    def advance_turn(self) -> None:
        """推进 turn 计数。"""
        self._turn += 1

    def trim_single(self, output: str, tool_name: str = "") -> str:
        """
        Layer 1 — 单结果截断。

        超过 context window 30% → 截断到 30%（硬限 50%）。
        """
        est_tokens = self._estimate_tokens(output)
        soft_limit = int(self.context_window_tokens * self.single_result_soft)
        hard_limit = int(self.context_window_tokens * self.single_result_hard)

        if est_tokens <= soft_limit:
            return output

        # 截断到 soft limit 对应的字符数
        max_chars = int(soft_limit * self.tool_chars_per_token)
        trimmed = self._utf8_safe_truncate(output, max_chars)

        original_tokens = est_tokens
        new_tokens = self._estimate_tokens(trimmed)
        log.info(f"ContextBudget: trimmed '{tool_name}' output "
                 f"{original_tokens}→{new_tokens} tokens (soft limit: {soft_limit})")
        return trimmed

    def record_output(self, tool_name: str, content: str) -> None:
        """记录一次工具输出（trim_single 之后的结果）。"""
        est_tokens = self._estimate_tokens(content)
        record = OutputRecord(
            tool_name=tool_name,
            content=content,
            char_count=len(content),
            est_tokens=est_tokens,
            turn=self._turn,
        )
        self._outputs.append(record)
        self._total_est_tokens += est_tokens

    def compress_if_needed(self) -> list[dict]:
        """
        Layer 2 — 全局守卫。

        总工具输出超过 headroom 75% 时，按时间序压缩最旧的结果。
        返回被压缩的记录列表（审计用）。
        """
        headroom = self.context_window_tokens
        threshold = int(headroom * self.global_compress_threshold)

        if self._total_est_tokens <= threshold:
            return []

        compressed = []
        # 从最旧的开始压缩，直到回到阈值以下
        target = int(headroom * 0.50)  # 压缩到 50%
        i = 0
        while i < len(self._outputs) and self._total_est_tokens > target:
            record = self._outputs[i]
            if record.est_tokens > 50:  # 不压缩已经很小的记录
                old_tokens = record.est_tokens
                summary = f"[ContextBudget compressed: {record.tool_name} output " \
                          f"from turn {record.turn}, ~{old_tokens} tokens → summary]\n" \
                          f"{record.content[:200]}…"
                new_tokens = self._estimate_tokens(summary)
                self._outputs[i] = OutputRecord(
                    tool_name=record.tool_name,
                    content=summary,
                    char_count=len(summary),
                    est_tokens=new_tokens,
                    turn=record.turn,
                )
                saved = old_tokens - new_tokens
                self._total_est_tokens -= saved
                compressed.append({
                    "tool": record.tool_name,
                    "turn": record.turn,
                    "saved_tokens": saved,
                })
                log.info(f"ContextBudget: compressed '{record.tool_name}' "
                         f"turn {record.turn}: saved ~{saved} tokens")
            i += 1

        return compressed

    @property
    def usage(self) -> dict:
        """当前用量统计。"""
        return {
            "total_est_tokens": self._total_est_tokens,
            "window_tokens": self.context_window_tokens,
            "usage_pct": round(self._total_est_tokens / self.context_window_tokens * 100, 1),
            "output_count": len(self._outputs),
            "turn": self._turn,
        }

    @property
    def remaining_tokens(self) -> int:
        """估算剩余可用 token。"""
        return max(0, self.context_window_tokens - self._total_est_tokens)
