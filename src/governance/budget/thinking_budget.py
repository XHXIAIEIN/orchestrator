# src/governance/budget/thinking_budget.py
"""
Adaptive Thinking Budget — 按任务复杂度动态调整推理 token 预算 (R39 PraisonAI steal).

五个级别:
  MINIMAL(2K) → LOW(4K) → MEDIUM(8K) → HIGH(16K) → MAXIMUM(32K)

公式: budget = min_tokens + (max_tokens - min_tokens) × complexity × multiplier

ThinkingTracker 统计每次推理的 token 消耗, 用于后续优化。

灵感: PraisonAI thinking/budget.py
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger(__name__)


class ThinkingLevel(Enum):
    """推理深度级别。"""
    MINIMAL = "minimal"    # 简单查询, 事实检索
    LOW = "low"            # 单步推理, 简单转换
    MEDIUM = "medium"      # 多步推理, 代码生成
    HIGH = "high"          # 复杂分析, 架构设计
    MAXIMUM = "maximum"    # 深度推理, 数学证明, 安全审计


# 各级别的 token 预算
LEVEL_BUDGETS: dict[ThinkingLevel, int] = {
    ThinkingLevel.MINIMAL: 2_000,
    ThinkingLevel.LOW: 4_000,
    ThinkingLevel.MEDIUM: 8_000,
    ThinkingLevel.HIGH: 16_000,
    ThinkingLevel.MAXIMUM: 32_000,
}

# 各级别的复杂度区间 [lower, upper)
LEVEL_THRESHOLDS: list[tuple[float, ThinkingLevel]] = [
    (0.0, ThinkingLevel.MINIMAL),
    (0.2, ThinkingLevel.LOW),
    (0.4, ThinkingLevel.MEDIUM),
    (0.6, ThinkingLevel.HIGH),
    (0.8, ThinkingLevel.MAXIMUM),
]


@dataclass
class ThinkingBudget:
    """推理 token 预算管理。

    支持两种模式:
    1. 离散级别: ThinkingBudget.high() → 16K
    2. 自适应插值: ThinkingBudget.adaptive(complexity=0.7) → 根据公式计算

    Usage:
        budget = ThinkingBudget.adaptive(complexity=0.65)
        print(budget.tokens)     # 12800
        print(budget.level)      # ThinkingLevel.HIGH
    """
    level: ThinkingLevel
    tokens: int
    complexity: float = 0.5
    multiplier: float = 1.0

    # ── Factory Methods ──────────────────────────────────────

    @classmethod
    def minimal(cls) -> ThinkingBudget:
        return cls(level=ThinkingLevel.MINIMAL, tokens=LEVEL_BUDGETS[ThinkingLevel.MINIMAL], complexity=0.0)

    @classmethod
    def low(cls) -> ThinkingBudget:
        return cls(level=ThinkingLevel.LOW, tokens=LEVEL_BUDGETS[ThinkingLevel.LOW], complexity=0.2)

    @classmethod
    def medium(cls) -> ThinkingBudget:
        return cls(level=ThinkingLevel.MEDIUM, tokens=LEVEL_BUDGETS[ThinkingLevel.MEDIUM], complexity=0.5)

    @classmethod
    def high(cls) -> ThinkingBudget:
        return cls(level=ThinkingLevel.HIGH, tokens=LEVEL_BUDGETS[ThinkingLevel.HIGH], complexity=0.7)

    @classmethod
    def maximum(cls) -> ThinkingBudget:
        return cls(level=ThinkingLevel.MAXIMUM, tokens=LEVEL_BUDGETS[ThinkingLevel.MAXIMUM], complexity=1.0)

    @classmethod
    def adaptive(cls, complexity: float, multiplier: float = 1.0) -> ThinkingBudget:
        """根据复杂度 (0.0-1.0) 自适应计算预算。

        公式: budget = min + (max - min) × complexity × multiplier
        """
        complexity = max(0.0, min(1.0, complexity))
        multiplier = max(0.1, min(3.0, multiplier))

        min_tokens = LEVEL_BUDGETS[ThinkingLevel.MINIMAL]
        max_tokens = LEVEL_BUDGETS[ThinkingLevel.MAXIMUM]
        tokens = int(min_tokens + (max_tokens - min_tokens) * complexity * multiplier)
        tokens = max(min_tokens, min(max_tokens * 3, tokens))  # 硬上限 = 3x maximum

        # 找到对应的离散级别
        level = ThinkingLevel.MINIMAL
        for threshold, lvl in LEVEL_THRESHOLDS:
            if complexity >= threshold:
                level = lvl

        return cls(level=level, tokens=tokens, complexity=complexity, multiplier=multiplier)

    @classmethod
    def from_level(cls, level: ThinkingLevel, multiplier: float = 1.0) -> ThinkingBudget:
        """从离散级别创建, 支持 multiplier 微调。"""
        base_tokens = LEVEL_BUDGETS[level]
        tokens = int(base_tokens * max(0.1, min(3.0, multiplier)))
        return cls(level=level, tokens=tokens, multiplier=multiplier)

    def __repr__(self) -> str:
        return f"ThinkingBudget({self.level.value}, {self.tokens:,} tokens, complexity={self.complexity:.2f})"


@dataclass
class ThinkingRecord:
    """单次推理的 token 消耗记录。"""
    task_id: str
    level: ThinkingLevel
    budget_tokens: int
    actual_tokens: int
    complexity: float
    duration_ms: float
    timestamp: float


@dataclass
class ThinkingTracker:
    """统计推理 token 消耗, 用于调优 complexity 估算。

    Usage:
        tracker = ThinkingTracker()
        tracker.start("task-123", ThinkingBudget.high())
        # ... LLM 推理 ...
        tracker.finish("task-123", actual_tokens=12345)
        print(tracker.stats)
    """
    _active: dict[str, tuple[ThinkingBudget, float]] = field(default_factory=dict, repr=False)
    _records: list[ThinkingRecord] = field(default_factory=list, repr=False)

    def start(self, task_id: str, budget: ThinkingBudget) -> None:
        """开始追踪一次推理。"""
        self._active[task_id] = (budget, time.time())

    def finish(self, task_id: str, actual_tokens: int) -> ThinkingRecord | None:
        """结束追踪, 记录实际消耗。"""
        if task_id not in self._active:
            log.warning(f"ThinkingTracker: unknown task_id {task_id}")
            return None

        budget, start_time = self._active.pop(task_id)
        duration_ms = (time.time() - start_time) * 1000

        record = ThinkingRecord(
            task_id=task_id,
            level=budget.level,
            budget_tokens=budget.tokens,
            actual_tokens=actual_tokens,
            complexity=budget.complexity,
            duration_ms=duration_ms,
            timestamp=start_time,
        )
        self._records.append(record)

        utilization = actual_tokens / budget.tokens * 100 if budget.tokens > 0 else 0
        if utilization > 120:
            log.warning(
                f"ThinkingTracker: task {task_id} exceeded budget "
                f"({actual_tokens}/{budget.tokens} tokens, {utilization:.0f}%)"
            )
        elif utilization < 30:
            log.info(
                f"ThinkingTracker: task {task_id} under-utilized budget "
                f"({actual_tokens}/{budget.tokens} tokens, {utilization:.0f}%)"
            )

        return record

    @property
    def stats(self) -> dict:
        """统计摘要。"""
        if not self._records:
            return {"total_records": 0}

        total_budget = sum(r.budget_tokens for r in self._records)
        total_actual = sum(r.actual_tokens for r in self._records)
        avg_utilization = total_actual / total_budget * 100 if total_budget > 0 else 0

        by_level: dict[str, dict] = {}
        for r in self._records:
            key = r.level.value
            if key not in by_level:
                by_level[key] = {"count": 0, "total_budget": 0, "total_actual": 0}
            by_level[key]["count"] += 1
            by_level[key]["total_budget"] += r.budget_tokens
            by_level[key]["total_actual"] += r.actual_tokens

        for v in by_level.values():
            v["avg_utilization_pct"] = round(v["total_actual"] / v["total_budget"] * 100, 1) if v["total_budget"] > 0 else 0

        return {
            "total_records": len(self._records),
            "total_budget_tokens": total_budget,
            "total_actual_tokens": total_actual,
            "avg_utilization_pct": round(avg_utilization, 1),
            "by_level": by_level,
        }
