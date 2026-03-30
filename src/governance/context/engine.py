"""
Context Engine — Provider/Processor 管道式上下文组装。

偷师来源: LobeHub (Round 16, P0 #3)
  - Provider 并行提供上下文源 → Processor 串行变换 → 按 budget 截断拼接
  - 替代 context_assembler.py 的硬编码拼接，提供可扩展的管道架构

向后兼容: context_assembler.py 不动，本模块是升级路径。
现有 executor_session.py / executor_prompt.py 暂不改，后续迁移时切换到 ContextEngine.assemble()。
"""
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


# ── Data ──────────────────────────────────────────────────────────

@dataclass
class ContextChunk:
    """单个上下文片段。"""
    source: str            # provider 名称，e.g. "system_prompt", "guidelines"
    content: str           # 实际文本
    priority: int = 50     # 0=最高优先, 100=最低优先
    token_estimate: int = 0  # 预估 token 数（0 = 自动计算）

    def __post_init__(self):
        if self.token_estimate <= 0 and self.content:
            # 粗估: 1 token ≈ 4 chars (中英混合场景偏保守)
            self.token_estimate = max(1, len(self.content) // 4)


@dataclass
class TaskContext:
    """传给 Provider 的任务描述，统一接口。"""
    department: str = ""
    action: str = ""
    task_text: str = ""         # 拼接后的任务文本 (problem + summary + action)
    spec: dict = field(default_factory=dict)
    task: dict = field(default_factory=dict)   # 原始 task dict，provider 自行取用
    project_name: str = ""
    cwd: str = ""

    @classmethod
    def from_task(cls, task: dict, department: str = "") -> "TaskContext":
        """从现有 task dict 构造。"""
        spec = task.get("spec", {}) if isinstance(task.get("spec"), dict) else {}
        task_text = " ".join(filter(None, [
            task.get("action", ""),
            spec.get("problem", ""),
            spec.get("summary", ""),
        ]))
        return cls(
            department=department,
            action=task.get("action", ""),
            task_text=task_text,
            spec=spec,
            task=task,
        )


# ── ABCs ──────────────────────────────────────────────────────────

class BaseProvider(ABC):
    """上下文源提供者。每个 Provider 产出 0~N 个 ContextChunk。"""
    name: str = "base"

    @abstractmethod
    def provide(self, ctx: TaskContext) -> list[ContextChunk]:
        ...


class BaseProcessor(ABC):
    """上下文变换器。串行执行，接收 chunks 列表并返回变换后的列表。"""
    name: str = "base"

    @abstractmethod
    def process(self, chunks: list[ContextChunk]) -> list[ContextChunk]:
        ...


# ── Engine ────────────────────────────────────────────────────────

class ContextEngine:
    """管道式上下文组装引擎。

    Usage:
        engine = ContextEngine()
        engine.register_provider(SystemPromptProvider())
        engine.register_provider(GuidelinesProvider())
        engine.register_processor(PriorityProcessor())
        engine.register_processor(TruncateProcessor(budget_tokens=4000))

        prompt_context = engine.assemble(TaskContext.from_task(task, "engineering"))
    """

    def __init__(self):
        self._providers: list[BaseProvider] = []
        self._processors: list[BaseProcessor] = []

    def register_provider(self, provider: BaseProvider) -> "ContextEngine":
        self._providers.append(provider)
        return self  # fluent API

    def register_processor(self, processor: BaseProcessor) -> "ContextEngine":
        self._processors.append(processor)
        return self

    def assemble(self, ctx: TaskContext, budget_tokens: int = 4000) -> str:
        """运行所有 Provider → 所有 Processor → 拼接输出。

        Provider 并行执行（ThreadPoolExecutor），Processor 按注册顺序串行。
        """
        # ── Phase 1: Provider 并行采集 ──
        chunks: list[ContextChunk] = []
        if not self._providers:
            return ""

        with ThreadPoolExecutor(max_workers=min(len(self._providers), 8)) as pool:
            futures = {
                pool.submit(self._safe_provide, p, ctx): p
                for p in self._providers
            }
            for future in as_completed(futures):
                provider = futures[future]
                try:
                    result = future.result()
                    chunks.extend(result)
                except Exception as e:
                    log.warning(f"ContextEngine: provider {provider.name} failed: {e}")

        log.info(f"ContextEngine: {len(chunks)} chunks from {len(self._providers)} providers")

        # ── Phase 2: Processor 串行变换 ──
        for proc in self._processors:
            try:
                chunks = proc.process(chunks)
            except Exception as e:
                log.warning(f"ContextEngine: processor {proc.name} failed: {e}")

        # ── Phase 3: 按 budget 截断 + 拼接 ──
        # TruncateProcessor 应该已经处理了 budget，这里做最终 safety net
        output_parts = []
        total_tokens = 0
        for chunk in chunks:
            if total_tokens + chunk.token_estimate > budget_tokens:
                remaining = budget_tokens - total_tokens
                if remaining > 50:  # 至少 50 tokens 才值得塞
                    char_budget = remaining * 4
                    output_parts.append(chunk.content[:char_budget] + "\n[...truncated]")
                break
            output_parts.append(chunk.content)
            total_tokens += chunk.token_estimate

        result = "\n\n---\n\n".join(output_parts)
        log.info(f"ContextEngine: assembled ~{total_tokens} tokens, {len(output_parts)} chunks")
        return result

    @staticmethod
    def _safe_provide(provider: BaseProvider, ctx: TaskContext) -> list[ContextChunk]:
        """安全调用 provider，异常不扩散。"""
        try:
            return provider.provide(ctx)
        except Exception as e:
            log.warning(f"Provider {provider.name} error: {e}")
            return []

    @classmethod
    def default(cls, budget_tokens: int = 4000) -> "ContextEngine":
        """创建带内置 Provider/Processor 的默认引擎。"""
        from src.governance.context.providers import (
            SystemPromptProvider, GuidelinesProvider,
            MemoryProvider, HistoryProvider, TwoStageRAGProvider,
        )
        from src.governance.context.processors import (
            PriorityProcessor, TruncateProcessor,
        )
        engine = cls()
        engine.register_provider(SystemPromptProvider())
        engine.register_provider(GuidelinesProvider())
        engine.register_provider(MemoryProvider())
        engine.register_provider(TwoStageRAGProvider())  # Two-Stage RAG (Round 16 P1)
        engine.register_provider(HistoryProvider())
        engine.register_processor(PriorityProcessor())
        engine.register_processor(TruncateProcessor(budget_tokens=budget_tokens))
        return engine
