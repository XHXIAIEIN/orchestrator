"""
内置 Context Processors — 变换上下文片段列表。

偷师来源: LobeHub (Round 16, P0 #3)
  - PriorityProcessor: 按 priority 排序（低值 = 高优先）
  - TruncateProcessor: 按 token budget 从低优先级开始截断
"""
import logging

from src.governance.context.engine import BaseProcessor, ContextChunk

log = logging.getLogger(__name__)


class PriorityProcessor(BaseProcessor):
    """按 priority 排序。priority 值越小越靠前（越不容易被截断）。"""
    name = "priority"

    def process(self, chunks: list[ContextChunk]) -> list[ContextChunk]:
        return sorted(chunks, key=lambda c: c.priority)


class TruncateProcessor(BaseProcessor):
    """按 token budget 截断。

    从排序后的 chunks 头部开始保留，超出 budget 的尾部 chunks 被丢弃。
    最后一个 chunk 如果部分超出，做字符级截断。
    """
    name = "truncate"

    def __init__(self, budget_tokens: int = 4000):
        self.budget_tokens = budget_tokens

    def process(self, chunks: list[ContextChunk]) -> list[ContextChunk]:
        if not chunks:
            return chunks

        kept: list[ContextChunk] = []
        total = 0

        for chunk in chunks:
            if total + chunk.token_estimate <= self.budget_tokens:
                kept.append(chunk)
                total += chunk.token_estimate
            else:
                # 尝试部分保留
                remaining_tokens = self.budget_tokens - total
                if remaining_tokens > 50:
                    char_budget = remaining_tokens * 4
                    truncated = ContextChunk(
                        source=chunk.source,
                        content=chunk.content[:char_budget] + "\n[...truncated]",
                        priority=chunk.priority,
                        token_estimate=remaining_tokens,
                    )
                    kept.append(truncated)
                    total += remaining_tokens

                dropped = len(chunks) - len(kept)
                if dropped > 0:
                    log.info(
                        f"TruncateProcessor: kept {len(kept)} chunks (~{total} tokens), "
                        f"dropped {dropped} (budget={self.budget_tokens})"
                    )
                break

        return kept
