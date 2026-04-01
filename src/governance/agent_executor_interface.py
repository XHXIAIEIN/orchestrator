"""
Unified Agent Executor Interface — abstract backend for agent lifecycle.

Stolen from: Claude Code backends/types.ts (TeammateExecutor)
            + claw-code AgentRuntime

Three backends implement this: Docker, In-Process (Agent SDK), SSH (future).
Governor dispatches through this interface without caring about execution method.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from src.core.protocol_messages import ProtocolMessage


class AgentKind(Enum):
    """Agent lifecycle classification. Stolen from Claude Code session kinds."""
    DISPATCH = "dispatch"        # Governor-dispatched, destroy on completion
    COLLECTOR = "collector"      # Data collection daemon, restart on crash
    INTERACTIVE = "interactive"  # Dashboard/user session, user-controlled
    DAEMON = "daemon"            # Proactive background agent (future Kairos)


@dataclass(frozen=True)
class AgentConfig:
    """Immutable agent spawn configuration."""
    agent_id: str
    kind: AgentKind
    department: str
    task_spec: str
    model: str = "claude-sonnet-4-6"
    max_turns: int = 25
    timeout_s: int = 300
    max_tool_iterations: int = 16  # Stolen from claw-code: prevent runaway loops
    allowed_tools: tuple[str, ...] = ()
    denied_tools: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentHandle:
    """Handle to a running agent. Frozen — state queries go through executor."""
    agent_id: str
    kind: AgentKind
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    backend_ref: Any = None  # Backend-specific reference (container ID, process handle, etc.)


class AgentExecutor(ABC):
    """Abstract agent execution backend.

    Implementations:
        DockerExecutor  — runs agents in Docker containers
        InProcessExecutor — runs agents via Agent SDK in current process
        SSHExecutor — runs agents on remote machines (future)
    """

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """Backend identifier: 'docker', 'in-process', 'ssh'."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if this backend can accept new agents."""
        ...

    @abstractmethod
    async def spawn(self, config: AgentConfig) -> AgentHandle:
        """Start a new agent with the given configuration."""
        ...

    @abstractmethod
    async def send_message(self, agent_id: str, message: ProtocolMessage) -> None:
        """Send a structured message to a running agent."""
        ...

    @abstractmethod
    async def terminate(self, agent_id: str, reason: str = "") -> bool:
        """Request graceful shutdown. Returns True if agent was running."""
        ...

    @abstractmethod
    async def is_active(self, agent_id: str) -> bool:
        """Check if agent is still running."""
        ...


class AgentRegistry:
    """Registry of active agents. Stolen from Claude Code concurrentSessions.ts.

    Each agent registers on spawn, deregisters on termination.
    Stale entries (crashed agents) cleaned up on next enumeration.
    """

    def __init__(self):
        self._agents: dict[str, AgentHandle] = {}
        self._executors: dict[str, AgentExecutor] = {}
        self._max_depth: int = 5  # Max agent nesting depth (from Codex registry.rs)

    def register_executor(self, executor: AgentExecutor) -> None:
        self._executors[executor.backend_type] = executor

    def register(self, handle: AgentHandle) -> None:
        self._agents[handle.agent_id] = handle

    def deregister(self, agent_id: str) -> Optional[AgentHandle]:
        return self._agents.pop(agent_id, None)

    def get(self, agent_id: str) -> Optional[AgentHandle]:
        return self._agents.get(agent_id)

    def enumerate_active(self) -> list[AgentHandle]:
        return list(self._agents.values())

    def count_by_kind(self, kind: AgentKind) -> int:
        return sum(1 for h in self._agents.values() if h.kind == kind)

    async def cleanup_stale(self) -> int:
        """Remove entries for agents that are no longer running."""
        stale = []
        for agent_id, handle in self._agents.items():
            executor = self._executors.get(handle.backend_ref)
            if executor and not await executor.is_active(agent_id):
                stale.append(agent_id)
        for agent_id in stale:
            self._agents.pop(agent_id, None)
        return len(stale)
