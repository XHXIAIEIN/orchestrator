"""
内置 Context Providers — 从各数据源采集上下文片段。

偷师来源: LobeHub (Round 16, P0 #3)
  - SystemPromptProvider: 部门 SKILL.md
  - GuidelinesProvider: 复用 context_assembler.match_guidelines
  - MemoryProvider: 从 memory_tier 读取 extended memory
  - HistoryProvider: 从 run_logger 读取最近执行记录
"""
import logging
from pathlib import Path

from src.governance.context.engine import BaseProvider, ContextChunk, TaskContext

log = logging.getLogger(__name__)

# ── Repo root discovery (same pattern as memory_tier.py) ──
_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not (
    (_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()
):
    _REPO_ROOT = _REPO_ROOT.parent


class SystemPromptProvider(BaseProvider):
    """读取部门 SKILL.md 作为 system prompt 上下文。

    Priority 10 — 最高优先级，始终保留。
    """
    name = "system_prompt"

    def provide(self, ctx: TaskContext) -> list[ContextChunk]:
        if not ctx.department:
            return []

        skill_path = _REPO_ROOT / "departments" / ctx.department / "SKILL.md"
        if not skill_path.exists():
            return []

        try:
            content = skill_path.read_text(encoding="utf-8").strip()
            if not content:
                return []
            return [ContextChunk(
                source=self.name,
                content=content,
                priority=10,
            )]
        except Exception as e:
            log.warning(f"SystemPromptProvider: failed to read {skill_path}: {e}")
            return []


class GuidelinesProvider(BaseProvider):
    """复用 context_assembler.match_guidelines 做关键词匹配。

    Priority 30 — WARM 层，条件匹配。
    """
    name = "guidelines"

    def provide(self, ctx: TaskContext) -> list[ContextChunk]:
        if not ctx.department or not ctx.task_text:
            return []

        try:
            from src.governance.context.context_assembler import (
                match_guidelines, load_shared_knowledge,
            )
        except ImportError:
            log.warning("GuidelinesProvider: cannot import context_assembler")
            return []

        chunks = []

        # Matched department guidelines
        guidelines = match_guidelines(ctx.department, ctx.task_text)
        for i, guideline in enumerate(guidelines):
            chunks.append(ContextChunk(
                source=f"{self.name}/dept",
                content=guideline,
                priority=30,
            ))

        # Shared knowledge
        shared = load_shared_knowledge(ctx.task_text)
        if shared:
            chunks.append(ContextChunk(
                source=f"{self.name}/shared",
                content=shared,
                priority=35,
            ))

        return chunks


class MemoryProvider(BaseProvider):
    """从 memory_tier 加载 extended memory + learnings。

    Learnings → Priority 5 (HOT, 不可丢弃)
    Extended memory → Priority 70 (COLD, 优先被截断)
    """
    name = "memory"

    def provide(self, ctx: TaskContext) -> list[ContextChunk]:
        chunks = []

        # ── Learnings (HOT) ──
        learnings = ctx.spec.get("learnings", [])
        if learnings:
            content = (
                "[Learnings] Rules from past mistakes. "
                "Violating these will likely cause the same failures:\n"
                + "\n".join(learnings)
            )
            chunks.append(ContextChunk(
                source=f"{self.name}/learnings",
                content=content,
                priority=5,  # 最高优先，不可丢弃
            ))

        # ── Extended memory (COLD) ──
        try:
            from src.governance.context.memory_tier import (
                resolve_tags_from_spec, load_extended_memory,
                format_extended_for_prompt,
            )
            tags = resolve_tags_from_spec(ctx.spec)
            if tags:
                entries = load_extended_memory(tags)
                if entries:
                    formatted = format_extended_for_prompt(entries)
                    if formatted:
                        chunks.append(ContextChunk(
                            source=f"{self.name}/extended",
                            content=formatted,
                            priority=70,
                        ))
        except Exception as e:
            log.warning(f"MemoryProvider: extended memory load failed: {e}")

        # ── Learned skills (COLD) ──
        if ctx.department:
            learned_path = _REPO_ROOT / "departments" / ctx.department / "learned-skills.md"
            if learned_path.exists():
                try:
                    learned = learned_path.read_text(encoding="utf-8").strip()
                    if learned:
                        chunks.append(ContextChunk(
                            source=f"{self.name}/learned_skills",
                            content=f"[Learned Skills]\n{learned}",
                            priority=75,
                        ))
                except Exception:
                    pass

        return chunks


class TwoStageRAGProvider(BaseProvider):
    """Two-Stage RAG for learnings — 先搜索摘要，再按需加载详情。

    偷师来源: LobeHub (Round 16, P1) — searchKnowledgeBase → readKnowledge 两阶段。

    Stage 1: 从 DB 搜索相关 learnings 的 pattern_key + rule（摘要级，低 token）
    Stage 2: 只对 top-K 相关条目加载 detail（详情级）

    替代 MemoryProvider 中的全量 learnings 注入，减少 context 浪费。

    Priority 8 — 略低于直注 learnings(5)，因为这是搜索结果不是必中。
    """
    name = "two_stage_rag"

    def __init__(self, db=None, top_k: int = 8, detail_k: int = 3):
        self._db = db
        self.top_k = top_k
        self.detail_k = detail_k

    def _get_db(self):
        if self._db:
            return self._db
        try:
            from src.storage.events_db import EventsDB
            return EventsDB()
        except Exception:
            return None

    def provide(self, ctx: TaskContext) -> list[ContextChunk]:
        db = self._get_db()
        if not db:
            return []

        query_text = ctx.task_text or ctx.action
        if not query_text:
            return []

        # ── Stage 1: Search — 关键词匹配，取摘要级条目 ──
        try:
            candidates = db.get_learnings(
                status=None,  # pending + promoted
                area=None,
                limit=self.top_k * 3,  # 多取一些供排序
            )
            # 只保留 pending/promoted
            candidates = [c for c in candidates if c.get("status") in ("pending", "promoted")]
        except Exception as e:
            log.warning(f"TwoStageRAGProvider: stage 1 search failed: {e}")
            return []

        if not candidates:
            return []

        # 相关性排序：关键词命中计数
        query_lower = query_text.lower()
        query_words = set(query_lower.split())

        def relevance_score(entry):
            text = f"{entry.get('pattern_key', '')} {entry.get('rule', '')} {entry.get('area', '')}".lower()
            return sum(1 for w in query_words if w in text)

        ranked = sorted(candidates, key=relevance_score, reverse=True)[:self.top_k]

        if not ranked:
            return []

        # ── Stage 2: Read — 对 top detail_k 加载详情 ──
        chunks = []

        # 摘要层（所有 top_k）
        summary_lines = []
        for entry in ranked:
            pk = entry.get("pattern_key", "?")
            rule = entry.get("rule", "")
            rec = entry.get("recurrence", 1)
            summary_lines.append(f"- [{pk}] (×{rec}) {rule}")

        chunks.append(ContextChunk(
            source=f"{self.name}/summary",
            content="[Learnings — relevant rules]\n" + "\n".join(summary_lines),
            priority=8,
        ))

        # 详情层（只对最相关的 detail_k 个）
        detail_entries = ranked[:self.detail_k]
        detail_lines = []
        for entry in detail_entries:
            detail = entry.get("detail", "")
            if detail and len(detail) > 20:
                pk = entry.get("pattern_key", "?")
                # 截断过长详情
                if len(detail) > 500:
                    detail = detail[:500] + "..."
                detail_lines.append(f"### {pk}\n{detail}")

        if detail_lines:
            chunks.append(ContextChunk(
                source=f"{self.name}/detail",
                content="[Learnings — detailed context]\n" + "\n\n".join(detail_lines),
                priority=20,
            ))

        return chunks


class StructuredMemoryProvider(BaseProvider):
    """从 StructuredMemoryStore 提供 6 维结构化记忆。

    偷师来源: LobeHub (Round 16, P0 #1) — 6 维记忆系统。

    Hot 记忆 → Priority 15 (始终注入，仅次于 learnings)
    On-demand 搜索 → Priority 45 (按任务关键词检索 warm/cold 记忆)

    与 memory_tier.py 共存：memory_tier 处理 .md 文件级 extended memory，
    本 Provider 处理 SQLite 6 维结构化记忆。
    """
    name = "structured_memory"

    def __init__(self, store=None, hot_budget_chars: int = 4000):
        self._store = store
        self._hot_budget_chars = hot_budget_chars

    def _get_store(self):
        if self._store is not None:
            return self._store
        try:
            from src.governance.context.structured_memory import StructuredMemoryStore
            self._store = StructuredMemoryStore()
            return self._store
        except Exception as e:
            log.debug(f"StructuredMemoryProvider: store init failed: {e}")
            return None

    def provide(self, ctx: TaskContext) -> list[ContextChunk]:
        store = self._get_store()
        if not store:
            return []

        chunks = []

        # ── Hot memories (high confidence, recent) ──
        try:
            hot_entries = store.get_hot(budget_chars=self._hot_budget_chars)
            if hot_entries:
                lines = self._format_hot_entries(hot_entries)
                if lines:
                    chunks.append(ContextChunk(
                        source=f"{self.name}/hot",
                        content="[Structured Memory — hot tier]\n" + "\n".join(lines),
                        priority=15,
                    ))
        except Exception as e:
            log.warning(f"StructuredMemoryProvider: hot memory retrieval failed: {e}")

        # ── On-demand search (warm/cold) based on task keywords ──
        query = ctx.task_text or ctx.action
        if query:
            try:
                from src.governance.context.structured_memory import Dimension
                search_results = []
                for dim in Dimension:
                    results = store.search(dim, query, top_k=3)
                    for r in results:
                        r["_dimension"] = dim.value
                    search_results.extend(results)

                if search_results:
                    # Sort by confidence and take top entries
                    search_results.sort(
                        key=lambda e: e.get("confidence", 0), reverse=True
                    )
                    formatted = self._format_search_results(search_results[:8])
                    if formatted:
                        chunks.append(ContextChunk(
                            source=f"{self.name}/search",
                            content="[Structured Memory — relevant]\n" + "\n".join(formatted),
                            priority=45,
                        ))
            except Exception as e:
                log.warning(f"StructuredMemoryProvider: search failed: {e}")

        return chunks

    @staticmethod
    def _format_hot_entries(entries: list[dict]) -> list[str]:
        lines = []
        for e in entries:
            dim = e.get("dimension", "?")
            # Pick the most informative text field based on dimension
            text = (
                e.get("summary") or e.get("fact") or e.get("directive")
                or e.get("situation") or e.get("project") or e.get("aspect")
                or ""
            )
            if text:
                conf = e.get("confidence", 0)
                lines.append(f"- [{dim}] (conf={conf:.1f}) {text[:200]}")
        return lines

    @staticmethod
    def _format_search_results(results: list[dict]) -> list[str]:
        lines = []
        for r in results:
            dim = r.get("_dimension", "?")
            text = (
                r.get("summary") or r.get("fact") or r.get("directive")
                or r.get("situation") or r.get("project") or r.get("aspect")
                or ""
            )
            if text:
                detail = (
                    r.get("detail") or r.get("reasoning") or r.get("description")
                    or r.get("goal") or ""
                )
                line = f"- [{dim}] {text[:150]}"
                if detail:
                    line += f" — {detail[:100]}"
                lines.append(line)
        return lines


class HistoryProvider(BaseProvider):
    """从 run_logger 读取最近执行记录。

    Priority 40 — WARM 层，提供执行上下文。
    """
    name = "history"

    def provide(self, ctx: TaskContext) -> list[ContextChunk]:
        if not ctx.department:
            return []

        try:
            from src.governance.audit.run_logger import (
                load_recent_runs, format_runs_for_context,
            )
        except ImportError:
            return []

        try:
            runs = load_recent_runs(ctx.department, n=5)
            formatted = format_runs_for_context(runs)
            if formatted:
                return [ContextChunk(
                    source=self.name,
                    content=formatted,
                    priority=40,
                )]
        except Exception as e:
            log.warning(f"HistoryProvider: failed: {e}")

        return []
