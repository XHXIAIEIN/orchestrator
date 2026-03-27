"""Delegation Span — track agent delegation chains for audit.

Records parent→child task relationships with timing for:
- Debugging: why did sub-agent X do Y?
- Cost allocation: which parent consumed what budget?
- Depth monitoring: prevent runaway delegation chains.
"""

import time
from dataclasses import dataclass, field


@dataclass
class DelegationSpan:
    """A single delegation in the chain."""
    span_id: str
    parent_span_id: str | None
    task_id: str
    department: str
    depth: int
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    status: str = "running"  # running, completed, failed
    tokens_used: int = 0
    children: list["DelegationSpan"] = field(default_factory=list)

    @property
    def duration_s(self) -> float | None:
        if self.ended_at:
            return round(self.ended_at - self.started_at, 2)
        return None

    def complete(self, status: str = "completed", tokens: int = 0):
        self.ended_at = time.time()
        self.status = status
        self.tokens_used = tokens

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "parent": self.parent_span_id,
            "task_id": self.task_id,
            "department": self.department,
            "depth": self.depth,
            "duration_s": self.duration_s,
            "status": self.status,
            "tokens_used": self.tokens_used,
            "children": [c.to_dict() for c in self.children],
        }


class DelegationTracker:
    """Track the full delegation tree for a rollout."""

    def __init__(self, max_depth: int = 5):
        self._spans: dict[str, DelegationSpan] = {}
        self._roots: list[str] = []
        self._max_depth = max_depth
        self._counter = 0

    def start_span(
        self,
        task_id: str,
        department: str,
        parent_span_id: str | None = None,
    ) -> DelegationSpan:
        """Start a new delegation span."""
        self._counter += 1
        span_id = f"span-{self._counter}"

        depth = 0
        if parent_span_id and parent_span_id in self._spans:
            parent = self._spans[parent_span_id]
            depth = parent.depth + 1
            if depth > self._max_depth:
                raise ValueError(f"Delegation depth {depth} exceeds max {self._max_depth}")

        span = DelegationSpan(
            span_id=span_id,
            parent_span_id=parent_span_id,
            task_id=task_id,
            department=department,
            depth=depth,
        )
        self._spans[span_id] = span

        if parent_span_id and parent_span_id in self._spans:
            self._spans[parent_span_id].children.append(span)
        else:
            self._roots.append(span_id)

        return span

    def end_span(self, span_id: str, status: str = "completed", tokens: int = 0):
        if span_id in self._spans:
            self._spans[span_id].complete(status, tokens)

    def get_tree(self) -> list[dict]:
        """Return the full delegation tree."""
        return [self._spans[r].to_dict() for r in self._roots if r in self._spans]

    def get_max_depth(self) -> int:
        return max((s.depth for s in self._spans.values()), default=0)

    def get_total_tokens(self) -> int:
        return sum(s.tokens_used for s in self._spans.values())

    def get_summary(self) -> dict:
        return {
            "total_spans": len(self._spans),
            "max_depth": self.get_max_depth(),
            "total_tokens": self.get_total_tokens(),
            "roots": len(self._roots),
        }
