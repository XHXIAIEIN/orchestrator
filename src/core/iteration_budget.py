"""迭代预算控制器 — 防中途放弃 + Grace Call。

偷自 Hermes Agent v0.9 run_agent.py lines 170-211, 793-815, 8067-8092 (R59)。

核心洞察（来自 hermes #7915）：
  **不要在中途警告模型预算快用完** — 中间压力警告会导致模型提前放弃复杂任务。
  正确做法：预算耗尽时才通知，并给一次 grace call 让模型体面地总结。

三个机制协同：
  1. IterationBudget — 线程安全的 consume/refund 计数器
  2. Grace call — 预算耗尽后注入"请总结"消息，再给一次 toolless API 调用
  3. Refund — execute_code 等程序化工具调用不消耗预算

用法示例：
    budget = IterationBudget(max_total=25)

    while budget.consume():
        response = call_api(messages)
        if is_programmatic_tool_call(response):
            budget.refund()  # 程序化调用不计入
        process(response)

    # 预算耗尽 → grace call
    if not got_final_response:
        messages.append({"role": "user", "content": budget.grace_message})
        final = call_api(messages, tools=[])  # toolless
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 默认的 grace call 提示 — 让模型总结已完成的工作
DEFAULT_GRACE_MESSAGE = (
    "You've reached the maximum number of iterations for this task. "
    "Please provide a concise summary of what you've accomplished so far, "
    "what remains to be done, and any important findings or decisions made."
)


@dataclass
class IterationBudget:
    """线程安全的迭代预算计数器。

    关键设计决策（来自 hermes #7915）：
    - 不在 consume() 中注入任何"预算即将耗尽"的警告
    - 不暴露 remaining 给模型 prompt（只暴露给控制逻辑）
    - 预算耗尽后通过 grace_call_available 提供一次最终调用
    """

    max_total: int = 25
    grace_message: str = field(default=DEFAULT_GRACE_MESSAGE, repr=False)

    # 内部状态
    _used: int = field(default=0, init=False, repr=False)
    _grace_consumed: bool = field(default=False, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    @property
    def remaining(self) -> int:
        """剩余可用迭代数（仅供控制逻辑使用，不要暴露给模型）。"""
        with self._lock:
            return max(0, self.max_total - self._used)

    @property
    def used(self) -> int:
        """已消耗的迭代数。"""
        with self._lock:
            return self._used

    @property
    def exhausted(self) -> bool:
        """预算是否已耗尽。"""
        return self.remaining <= 0

    @property
    def grace_call_available(self) -> bool:
        """是否可以进行 grace call（预算耗尽且未消费过 grace）。"""
        with self._lock:
            return self._used >= self.max_total and not self._grace_consumed

    def consume(self) -> bool:
        """消费一次迭代。成功返回 True，预算耗尽返回 False。

        注意：返回 False 不意味着任务结束 — 检查 grace_call_available。
        """
        with self._lock:
            if self._used >= self.max_total:
                return False
            self._used += 1
            return True

    def refund(self) -> None:
        """退还一次迭代（用于不应计入预算的程序化工具调用）。"""
        with self._lock:
            if self._used > 0:
                self._used -= 1
                logger.debug("迭代预算退还: used=%d/%d", self._used, self.max_total)

    def consume_grace(self) -> bool:
        """消费 grace call。成功返回 True，已消费过返回 False。

        调用方应该：
        1. 检查 grace_call_available
        2. 向 messages 追加 grace_message（role=user）
        3. 发起一次 toolless API 调用
        4. 调用 consume_grace() 标记已使用
        """
        with self._lock:
            if self._grace_consumed:
                return False
            self._grace_consumed = True
            logger.debug("Grace call 已消费")
            return True

    def reset(self) -> None:
        """重置预算（新会话时调用）。"""
        with self._lock:
            self._used = 0
            self._grace_consumed = False
