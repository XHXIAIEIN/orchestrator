# src/governance/condenser/tool_output_pruner.py
"""
Tool Output Pruner — 针对 tool role 消息的专项裁剪 (R39 PraisonAI steal).

策略: >500 chars 时保留前 200 + 后 20%, 中间省略。
仅处理 source="environment" (工具输出) 的 Event, 用户消息不动。

灵感: PraisonAI compaction/compactor.py:_prune()
插入位置: CondenserPipeline 中 UploadStripper 之后。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .base import Condenser, Event, View

log = logging.getLogger(__name__)


@dataclass
class PruneConfig:
    """裁剪配置。"""
    # 触发裁剪的字符阈值
    trigger_chars: int = 500
    # 保留头部字符数
    head_chars: int = 200
    # 保留尾部占比 (剩余部分的百分比)
    tail_ratio: float = 0.20
    # 最小尾部字符数 (即使比例算出来更小)
    tail_min_chars: int = 50
    # 跳过已 condensed 的 event
    skip_condensed: bool = True
    # 只处理 environment source (工具输出)
    tool_sources: tuple[str, ...] = ("environment", "tool")


class ToolOutputPruner(Condenser):
    """Tool 输出专项裁剪器。

    保留策略:
    - 头部 200 chars: 通常包含关键信息 (文件名、命令、首行结果)
    - 尾部 20%: 通常包含总结、返回值、最终状态
    - 中间省略: 重复性数据 (日志行、搜索结果中间页)

    与 UploadStripper 的区别:
    - UploadStripper: 移除无用引用 (临时文件路径)
    - ToolOutputPruner: 压缩有用但过长的内容
    """

    def __init__(self, config: PruneConfig | None = None):
        self.config = config or PruneConfig()

    def prune_text(self, text: str) -> str:
        """对单段文本执行裁剪。"""
        c = self.config
        if len(text) <= c.trigger_chars:
            return text

        head = text[:c.head_chars]
        remaining = text[c.head_chars:]
        tail_chars = max(c.tail_min_chars, int(len(remaining) * c.tail_ratio))
        tail = remaining[-tail_chars:] if tail_chars < len(remaining) else remaining

        omitted = len(text) - len(head) - len(tail)
        separator = f"\n\n… [{omitted:,} chars pruned by ToolOutputPruner] …\n\n"

        return head + separator + tail

    def condense(self, view: View) -> View:
        """裁剪 View 中所有 tool 输出。"""
        events = view.events
        pruned: list[Event] = []
        prune_count = 0
        chars_saved = 0

        for e in events:
            # 只处理工具输出
            if (e.source not in self.config.tool_sources
                    or (self.config.skip_condensed and e.condensed)):
                pruned.append(e)
                continue

            new_content = self.prune_text(e.content)
            if new_content != e.content:
                prune_count += 1
                chars_saved += len(e.content) - len(new_content)
                pruned.append(Event(
                    id=e.id,
                    event_type=e.event_type,
                    source=e.source,
                    content=new_content,
                    metadata={**e.metadata, "pruned": True, "original_chars": len(e.content)},
                    condensed=True,
                ))
            else:
                pruned.append(e)

        if prune_count:
            log.info(
                f"ToolOutputPruner: pruned {prune_count}/{len(events)} events, "
                f"saved {chars_saved:,} chars"
            )

        return View(pruned)
