# src/core/context_budget.py
"""
ContextBudget — 上下文窗口预算管理器，偷自 OpenFang context_budget.rs。

双层动态截断：
  Layer 1: 单个工具结果不超过 context window 的 30%（硬限 50%）
  Layer 2: 总工具输出超过可用空间 75% 时，按时间序压缩最旧的结果

用法:
    budget = ContextBudget(context_window_tokens=200_000)
    result = budget.trim_single(tool_output, tool_name="Bash")
    budget.record_output(tool_name, result)
    # 全局检查
    compressed = budget.compress_if_needed()
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import NamedTuple

log = logging.getLogger(__name__)


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
