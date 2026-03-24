# src/governance/condenser/llm_summarizing.py
"""LLM-based context compression — summarize middle events into a compact digest.

Uses a cheap/fast model to compress verbose event histories while preserving
key decisions, errors, and outcomes. Falls back to AmortizedForgetting if
LLM is unavailable.
"""
from __future__ import annotations

import logging

from .base import Condenser, Event, View

log = logging.getLogger(__name__)

# Default: trigger when events exceed this count
DEFAULT_THRESHOLD = 60
# Keep first N events (task setup, initial instructions)
DEFAULT_KEEP_HEAD = 8
# Keep last N events (recent context, still relevant)
DEFAULT_KEEP_TAIL = 20

SUMMARIZE_PROMPT = """\
你是一个事件压缩器。将以下 agent 执行事件序列压缩为简洁摘要。

保留：
- 关键决策和转折点
- 错误和修复尝试
- 文件修改记录
- 最终结果和状态变化

丢弃：
- 重复的搜索/读取操作
- 冗余的中间思考
- 已被后续操作覆盖的旧状态

输出一段连贯的中文摘要，不超过 500 字。

事件序列：
{events_text}
"""


class LLMSummarizingCondenser(Condenser):
    """Compress middle events using a lightweight LLM call.

    Strategy:
    1. If total events <= threshold, pass through unchanged
    2. Keep head (setup context) + tail (recent) intact
    3. Compress middle section into a single summary event via LLM
    4. If LLM fails, fall back to AmortizedForgetting behavior
    """

    def __init__(
        self,
        llm_fn=None,
        threshold: int = DEFAULT_THRESHOLD,
        keep_head: int = DEFAULT_KEEP_HEAD,
        keep_tail: int = DEFAULT_KEEP_TAIL,
    ):
        self.llm_fn = llm_fn  # async fn(prompt) -> str, or None
        self.threshold = threshold
        self.keep_head = keep_head
        self.keep_tail = keep_tail

    def condense(self, view: View) -> View:
        if len(view) <= self.threshold:
            return view

        events = view.events
        head = events[: self.keep_head]
        middle = events[self.keep_head : -self.keep_tail]
        tail = events[-self.keep_tail :]

        summary_text = self._summarize(middle)

        summary_event = Event(
            id=-1,
            event_type="system",
            source="condenser:llm",
            content=summary_text,
            metadata={"condensed_count": len(middle), "strategy": "llm_summarizing"},
            condensed=True,
        )
        return View(head + [summary_event] + tail)

    def _summarize(self, events: list[Event]) -> str:
        """Attempt LLM summary, fall back to mechanical compression."""
        events_text = "\n".join(
            f"[{e.event_type}:{e.source}] {e.content[:200]}" for e in events
        )

        if self.llm_fn:
            try:
                prompt = SUMMARIZE_PROMPT.format(events_text=events_text[:4000])
                result = self.llm_fn(prompt)
                if result and len(result) > 20:
                    return f"[LLM摘要: {len(events)} 事件压缩]\n{result}"
            except Exception as e:
                log.warning(f"LLM condenser failed, falling back: {e}")

        # Fallback: mechanical compression
        return self._mechanical_summary(events)

    def _mechanical_summary(self, events: list[Event]) -> str:
        """Rule-based compression when LLM is unavailable."""
        # Keep only events with errors, tool calls, or decisions
        significant = []
        for e in events:
            meta = e.metadata
            has_error = meta.get("error") or "error" in e.content.lower()[:100]
            has_tools = bool(meta.get("tools"))
            is_result = e.event_type in ("observation", "result")
            if has_error or has_tools or is_result:
                significant.append(e)

        if not significant:
            return f"[机械压缩: {len(events)} 事件，无显著内容]"

        lines = [f"[机械压缩: {len(events)} → {len(significant)} 事件]"]
        for e in significant[:15]:  # Cap at 15
            lines.append(f"- [{e.event_type}] {e.content[:120]}")
        return "\n".join(lines)
