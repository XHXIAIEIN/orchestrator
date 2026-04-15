"""AgentRuntime — Type-safe dependency injection container for agent execution.

Stolen from LangGraph Runtime (R68, Round 43):
Replaces scattered parameter passing (task_id, prompt, dept_prompt,
allowed_tools, task_cwd, max_turns, timeout) with a single typed,
immutable object. Benefits:

- Type safety: IDE autocompletion, typo detection at write-time
- Immutability: frozen dataclass prevents accidental mutation
- Composability: override() creates child runtimes for sub-tasks
- Memory efficiency: slots=True eliminates per-instance __dict__
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentRuntime:
    """Immutable execution context for a single agent session.

    Constructed once in TaskExecutor.execute_task(), then threaded through
    ExecutionStrategy → AgentSessionRunner without unpacking.

    Fields are split into two tiers:
    - Execution-critical: used by the Agent SDK call (prompt, tools, cwd, etc.)
    - Metadata: used for logging/tracing, not execution logic
    """

    # ── Execution-critical ──
    task_id: int
    session_id: str
    prompt: str
    dept_prompt: str
    allowed_tools: tuple[str, ...]   # frozen → tuple, not list
    cwd: str
    max_turns: int
    timeout_s: float | None = None

    # ── Metadata (logging/tracing) ──
    department: str = ""
    project: str = ""
    model: str = ""
    tier_name: str = ""
    cognitive_mode: str = ""

    # ── Extensible context bag ──
    # For downstream components that need arbitrary data without
    # polluting the core signature. Prefer named fields for common data.
    extra: dict[str, Any] | None = None

    def override(self, **kwargs) -> AgentRuntime:
        """Create a new Runtime with selected fields overridden.

        Useful for sub-tasks that inherit parent config but need
        different cwd, tools, or prompt.

        Example:
            child = runtime.override(task_id=new_id, prompt=new_prompt)
        """
        # Convert list to tuple if caller passes allowed_tools as list
        if "allowed_tools" in kwargs and isinstance(kwargs["allowed_tools"], list):
            kwargs["allowed_tools"] = tuple(kwargs["allowed_tools"])
        return replace(self, **kwargs)

    def for_subtask(self, task_id: int, prompt: str, **kwargs) -> AgentRuntime:
        """Derive a child runtime for a sub-task.

        Inherits all parent fields except task_id and prompt,
        which are always overridden. Additional overrides via kwargs.
        """
        return self.override(task_id=task_id, prompt=prompt, **kwargs)
