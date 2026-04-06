"""ExecutionContext — per-execution isolated state (R40-P3).

Each workflow/task execution creates its own ExecutionContext with:
- execution_id: UUID for tracing
- node_executions: per-node state tracking
- outputs: result cache keyed by node_id
- checkpoints: ordered list of completed node_ids
- errors: structured error records
"""
from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class NodeExecution:
    node_id: str
    status: NodeStatus = NodeStatus.PENDING
    started_at: float = 0.0
    finished_at: float = 0.0
    error: str = ""
    attempts: int = 0


@dataclass
class ExecutionContext:
    execution_id: str
    workflow_id: str
    created_at: float
    node_executions: dict[str, NodeExecution] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    checkpoints: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    @classmethod
    def create(cls, workflow_id: str) -> ExecutionContext:
        return cls(
            execution_id=uuid.uuid4().hex[:12],
            workflow_id=workflow_id,
            created_at=time.time(),
        )

    def start_node(self, node_id: str) -> None:
        self.node_executions[node_id] = NodeExecution(
            node_id=node_id, status=NodeStatus.RUNNING, started_at=time.time(),
        )

    def complete_node(self, node_id: str, output: Any = None) -> None:
        node = self.node_executions[node_id]
        node.status = NodeStatus.COMPLETED
        node.finished_at = time.time()
        if output is not None:
            self.outputs[node_id] = output
        self.checkpoints.append(node_id)

    def fail_node(self, node_id: str, error: str = "") -> None:
        node = self.node_executions[node_id]
        node.status = NodeStatus.FAILED
        node.finished_at = time.time()
        node.error = error
        self.errors.append({"node": node_id, "error": error, "time": time.time()})

    def is_node_completed(self, node_id: str) -> bool:
        node = self.node_executions.get(node_id)
        return node is not None and node.status == NodeStatus.COMPLETED

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "created_at": self.created_at,
            "checkpoints": list(self.checkpoints),
            "outputs": {k: v for k, v in self.outputs.items()},
            "errors": list(self.errors),
            "nodes": {
                nid: {"status": n.status.value, "started_at": n.started_at,
                       "finished_at": n.finished_at, "error": n.error}
                for nid, n in self.node_executions.items()
            },
        }
