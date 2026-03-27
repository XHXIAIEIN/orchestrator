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

    def __init__(self, limit: float | None = None, source: str = ""):
        self.limit = limit
        self.source = source
        self._calls: list[CostCall] = []
        self._lock = threading.Lock()

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

        if self.limit is not None and total > self.limit:
            log.warning(f"CostTracker[{self.source}]: limit exceeded ${total:.4f} > ${self.limit:.4f}")
            raise CostLimitExceededError(self.limit, total)

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

    def to_dict(self) -> dict:
        """序列化为 dict，方便存 DB 或日志。"""
        with self._lock:
            return {
                "total_cost": round(sum(c.cost for c in self._calls), 6),
                "call_count": len(self._calls),
                "limit": self.limit,
                "calls": [
                    {"type": c.call_type, "model": c.model, "cost": c.cost,
                     "tokens": c.tokens, "stack": c.stack}
                    for c in self._calls
                ],
            }


def _short_stack(depth: int = 3) -> str:
    """取调用栈的关键几帧（跳过自身），方便调试。"""
    frames = traceback.extract_stack()
    # 跳过最后 2 帧（_short_stack 自身 + add_call）
    relevant = frames[-(depth + 2):-2]
    return " → ".join(f"{f.filename.split('/')[-1]}:{f.lineno}" for f in relevant)
