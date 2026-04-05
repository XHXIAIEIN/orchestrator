"""ExecutionResponse — structured result from agent execution.

Stolen from OpenAI Swarm's Response object: instead of returning a plain string,
return a rich object with metadata (turns, cost, duration, status).
Backward-compatible: str(response) returns .output for existing code.
"""
from dataclasses import dataclass, field


@dataclass
class ExecutionResponse:
    """Structured result from a single agent execution."""
    status: str = "done"          # done | failed | stuck | doom_loop | timeout | terminated
    output: str = ""              # the text result
    turns_taken: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    stop_reason: str = ""
    is_error: bool = False
    tool_calls_count: int = 0
    context_variables: dict = field(default_factory=dict)
    trajectory_summary: dict = field(default_factory=dict)  # R39: eval trajectory data

    def to_dict(self) -> dict:
        d = {
            "status": self.status,
            "output": self.output[:500],
            "turns_taken": self.turns_taken,
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
            "stop_reason": self.stop_reason,
            "is_error": self.is_error,
            "tool_calls_count": self.tool_calls_count,
        }
        if self.trajectory_summary:
            d["trajectory_summary"] = self.trajectory_summary
        return d

    def __str__(self) -> str:
        """Backward compat: str coercion returns output text."""
        return self.output

    def __bool__(self) -> bool:
        return bool(self.output)
