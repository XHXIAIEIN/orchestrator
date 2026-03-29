"""Session Manager — stolen from OpenHands /clear.

Manages agent session lifecycle with inheritance:
- New session inherits parent's environment (CWD, env vars, config)
- But starts with fresh conversation context
- Parent-child links enable tracing session lineage

Usage:
    mgr = SessionManager()
    parent = mgr.create("task_1", cwd="/project", env={"KEY": "val"})
    child = mgr.fork(parent.id, reason="context overflow")
    # child has same cwd/env but empty message history
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class Session:
    """An agent session with environment and lineage."""
    id: str
    task_id: str
    cwd: str = ""
    env: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    parent_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    status: str = "active"       # active, completed, forked, failed
    fork_reason: str = ""
    turns: int = 0
    cost_usd: float = 0.0

    @property
    def has_parent(self) -> bool:
        return self.parent_id is not None


class SessionManager:
    """Manage agent sessions with fork/inheritance support."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._counter = 0

    def _next_id(self, task_id: str) -> str:
        self._counter += 1
        return f"session_{task_id}_{self._counter}"

    def create(self, task_id: str, cwd: str = "", env: dict = None,
               config: dict = None) -> Session:
        """Create a new root session."""
        session = Session(
            id=self._next_id(task_id),
            task_id=task_id,
            cwd=cwd,
            env=env or {},
            config=config or {},
        )
        self._sessions[session.id] = session
        log.info(f"session: created {session.id} for task {task_id}")
        return session

    def fork(self, parent_id: str, reason: str = "context_reset") -> Optional[Session]:
        """Fork a session — inherit environment, reset context.

        The parent session is marked as 'forked' and a new child session
        is created with the same cwd/env/config but fresh state.
        """
        parent = self._sessions.get(parent_id)
        if not parent:
            log.warning(f"session: cannot fork unknown session {parent_id}")
            return None

        # Mark parent as forked
        parent.status = "forked"
        parent.fork_reason = reason

        # Create child inheriting environment
        child = Session(
            id=self._next_id(parent.task_id),
            task_id=parent.task_id,
            cwd=parent.cwd,
            env=dict(parent.env),      # shallow copy
            config=dict(parent.config),
            parent_id=parent.id,
            fork_reason=reason,
        )
        self._sessions[child.id] = child

        log.info(
            f"session: forked {parent.id} → {child.id} "
            f"(reason={reason}, inherited cwd={parent.cwd})"
        )
        return child

    def complete(self, session_id: str, cost_usd: float = 0.0):
        """Mark a session as completed."""
        session = self._sessions.get(session_id)
        if session:
            session.status = "completed"
            session.cost_usd = cost_usd

    def fail(self, session_id: str, reason: str = ""):
        """Mark a session as failed."""
        session = self._sessions.get(session_id)
        if session:
            session.status = "failed"
            session.fork_reason = reason

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def get_lineage(self, session_id: str) -> list[Session]:
        """Get the full lineage chain (parent → ... → current)."""
        chain = []
        current = self._sessions.get(session_id)
        while current:
            chain.append(current)
            current = self._sessions.get(current.parent_id) if current.parent_id else None
        chain.reverse()
        return chain

    def get_children(self, session_id: str) -> list[Session]:
        """Get all direct children of a session."""
        return [s for s in self._sessions.values() if s.parent_id == session_id]

    def get_active(self) -> list[Session]:
        """Get all active sessions."""
        return [s for s in self._sessions.values() if s.status == "active"]

    def get_stats(self) -> dict:
        statuses = {}
        for s in self._sessions.values():
            statuses[s.status] = statuses.get(s.status, 0) + 1
        return {
            "total": len(self._sessions),
            "by_status": statuses,
            "active": len(self.get_active()),
        }
