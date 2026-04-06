"""
CostTracking — 全链路成本追踪器，偷自 Firecrawl cost-tracking.ts。

每个请求/任务创建一个 CostTracking 实例，贯穿整个处理流水线。
任何 LLM 调用都往里 addCall()，带 stack trace 方便调试。
可设置 limit，超限自动抛 CostLimitExceededError 中断执行。

用法:
    tracker = CostTracker(limit=0.50)  # 最多花 $0.50
    tracker.add_call("generate", model="claude-haiku-4-5", cost=0.001, tokens={"in": 500, "out": 100})
    tracker.add_call("generate", model="claude-sonnet-4-6", cost=0.015, tokens={"in": 800, "out": 200})
    print(tracker.total_cost)   # 0.016
    print(tracker.summary())    # 人类可读摘要

    # 超限自动中断
    tracker.add_call("extract", model="claude-sonnet-4-6", cost=0.50)  # raises CostLimitExceededError
"""
import logging
import threading
import traceback
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class CostLimitExceededError(Exception):
    """成本超限，中断执行。"""
    def __init__(self, limit: float, actual: float):
        self.limit = limit
        self.actual = actual
        super().__init__(f"Cost limit exceeded: ${actual:.4f} > ${limit:.4f}")


@dataclass
class CostCall:
    """单次 LLM 调用的成本记录。"""
    call_type: str           # "generate", "extract", "vision", ...
    model: str               # 模型 ID
    cost: float              # 美元成本
    tokens: dict = field(default_factory=dict)  # {"in": N, "out": N}
    stack: str = ""          # 调用栈（调试用）


class CostTracker:
    """线程安全的全链路成本追踪器。"""

    def __init__(self, limit: float | None = None, source: str = "",
                 token_limit: int | None = None):
        self.limit = limit
        self.token_limit = token_limit
        self.source = source
        self._calls: list[CostCall] = []
        self._lock = threading.Lock()
        # Sub-budget tree (parent ↔ children)
        self._parent: CostTracker | None = None
        self._label: str = ""
        self._children: list[CostTracker] = []

    def add_call(self, call_type: str, model: str = "", cost: float = 0.0,
                 tokens: dict | None = None) -> None:
        """记录一次 LLM 调用。超限时抛 CostLimitExceededError。"""
        call = CostCall(
            call_type=call_type,
            model=model,
            cost=cost,
            tokens=tokens or {},
            stack=_short_stack(),
        )
        with self._lock:
            self._calls.append(call)
            total = sum(c.cost for c in self._calls)
            total_tokens = sum(
                c.tokens.get("in", 0) + c.tokens.get("out", 0)
                for c in self._calls
            )

        if self.limit is not None and total > self.limit:
            log.warning(f"CostTracker[{self.source}]: cost limit exceeded ${total:.4f} > ${self.limit:.4f}")
            raise CostLimitExceededError(self.limit, total)

        if self.token_limit is not None and total_tokens > self.token_limit:
            log.warning(f"CostTracker[{self.source}]: token limit exceeded {total_tokens} > {self.token_limit}")
            raise CostLimitExceededError(self.token_limit, total_tokens)

    @property
    def total_cost(self) -> float:
        with self._lock:
            return sum(c.cost for c in self._calls)

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self._calls)

    @property
    def calls(self) -> list[CostCall]:
        with self._lock:
            return list(self._calls)

    def summary(self) -> str:
        """人类可读的成本摘要。"""
        with self._lock:
            if not self._calls:
                return "no LLM calls"
            total = sum(c.cost for c in self._calls)
            models = {}
            for c in self._calls:
                m = c.model or "unknown"
                if m not in models:
                    models[m] = {"count": 0, "cost": 0.0}
                models[m]["count"] += 1
                models[m]["cost"] += c.cost
            parts = [f"{m}: {d['count']}x ${d['cost']:.4f}" for m, d in models.items()]
            return f"${total:.4f} ({len(self._calls)} calls: {', '.join(parts)})"

    @property
    def total_tokens(self) -> int:
        """所有调用的 token 总数（in + out）。"""
        with self._lock:
            return sum(
                c.tokens.get("in", 0) + c.tokens.get("out", 0)
                for c in self._calls
            )

    def to_dict(self) -> dict:
        """序列化为 dict，方便存 DB 或日志。"""
        with self._lock:
            return {
                "total_cost": round(sum(c.cost for c in self._calls), 6),
                "call_count": len(self._calls),
                "limit": self.limit,
                "token_limit": self.token_limit,
                "calls": [
                    {"type": c.call_type, "model": c.model, "cost": c.cost,
                     "tokens": c.tokens, "stack": c.stack}
                    for c in self._calls
                ],
            }

    # ── Sub-budget proportional allocation ──────────────────────────

    def create_child_budget(self, fraction: float, label: str = "") -> "CostTracker":
        """按比例从剩余预算中分配子预算。

        Args:
            fraction: (0, 1]，分配剩余预算的比例
            label: 可选标签，方便追踪（如 "subtask-research"）

        Returns:
            新的 CostTracker，limit 按比例缩减。
        """
        if not 0.0 < fraction <= 1.0:
            raise ValueError(f"fraction must be (0, 1], got {fraction}")

        remaining_cost = (self.limit - self.total_cost) if self.limit is not None else None
        remaining_tokens = (self.token_limit - self.total_tokens) if self.token_limit is not None else None

        child = CostTracker(
            limit=remaining_cost * fraction if remaining_cost is not None else None,
            token_limit=int(remaining_tokens * fraction) if remaining_tokens is not None else None,
            source=f"{self.source}>{label}" if self.source else label,
        )
        child._parent = self
        child._label = label
        self._children.append(child)
        return child

    def report_to_parent(self) -> None:
        """子任务完成后，把用量上报给父 tracker。"""
        if not self._parent:
            return
        # 把子调用记录直接灌入父级（保留完整 stack trace）
        with self._parent._lock:
            self._parent._calls.extend(self.calls)
        log.debug(
            "CostTracker[%s] reported to parent: $%.4f, %d tokens",
            self._label, self.total_cost, self.total_tokens,
        )

    def session_summary(self) -> dict:
        """Per-session cost summary with token breakdown by type and model."""
        with self._lock:
            total_cost = 0.0
            total_tokens = {"input": 0, "output": 0, "cache_read": 0, "reasoning": 0}
            by_model: dict[str, dict] = {}
            for c in self._calls:
                total_cost += c.cost
                for key in total_tokens:
                    total_tokens[key] += c.tokens.get(key, 0)
                m = c.model or "unknown"
                if m not in by_model:
                    by_model[m] = {"calls": 0, "cost": 0.0,
                                   "tokens": {"input": 0, "output": 0, "cache_read": 0, "reasoning": 0}}
                by_model[m]["calls"] += 1
                by_model[m]["cost"] += c.cost
                for key in by_model[m]["tokens"]:
                    by_model[m]["tokens"][key] += c.tokens.get(key, 0)
            return {
                "total_cost": round(total_cost, 6),
                "total_tokens": total_tokens,
                "by_model": by_model,
                "needs_compaction": False,
            }

    def get_budget_summary(self) -> dict:
        """返回预算状态，含子预算树。"""
        summary = {
            "label": self._label,
            "cost": {"used": self.total_cost, "limit": self.limit},
            "tokens": {"used": self.total_tokens, "limit": self.token_limit},
        }
        if self._children:
            summary["children"] = [c.get_budget_summary() for c in self._children]
        return summary


def _short_stack(depth: int = 3) -> str:
    """取调用栈的关键几帧（跳过自身），方便调试。"""
    frames = traceback.extract_stack()
    # 跳过最后 2 帧（_short_stack 自身 + add_call）
    relevant = frames[-(depth + 2):-2]
    return " → ".join(f"{f.filename.split('/')[-1]}:{f.lineno}" for f in relevant)
