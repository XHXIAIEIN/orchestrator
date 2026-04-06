"""Continuous Scheduler — DAG-aware FIRST_COMPLETED scheduling (R40-P1+P2).

Instead of layer-by-layer execution (wait for all nodes in a layer),
uses asyncio.wait(FIRST_COMPLETED) to start dependent nodes as soon as
their prerequisites complete. Combined with a decide lock (R40-P2) to
prevent concurrent scheduling decisions.

Architecture:
    DAGScheduler — pure dependency graph logic (sync, testable)
    ContinuousExecutor — async runtime that drives DAGScheduler with FIRST_COMPLETED
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from src.governance.execution_context import ExecutionContext

log = logging.getLogger(__name__)


@dataclass
class NodeSpec:
    node_id: str
    dependencies: list[str] = field(default_factory=list)
    handler: Callable[..., Awaitable[Any]] | None = None


class DAGScheduler:
    """Pure DAG dependency resolver. No async, no I/O — just graph logic."""

    def __init__(self) -> None:
        self._nodes: dict[str, NodeSpec] = {}

    def add_node(self, spec: NodeSpec) -> None:
        self._nodes[spec.node_id] = spec

    @property
    def node_ids(self) -> list[str]:
        return list(self._nodes.keys())

    def find_ready_nodes(self, completed: set[str], running: set[str] | None = None) -> list[str]:
        running = running or set()
        ready = []
        for nid, spec in self._nodes.items():
            if nid in completed or nid in running:
                continue
            if all(dep in completed for dep in spec.dependencies):
                ready.append(nid)
        return ready

    def validate(self) -> None:
        """Check for cycles using DFS. Raises ValueError if cycle found."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in self._nodes}

        def dfs(nid: str) -> None:
            color[nid] = GRAY
            for dep_id in self._nodes.get(nid, NodeSpec(node_id="")).dependencies:
                if dep_id not in color:
                    continue
                if color[dep_id] == GRAY:
                    raise ValueError(f"DAG cycle detected involving {nid} → {dep_id}")
                if color[dep_id] == WHITE:
                    dfs(dep_id)
            color[nid] = BLACK

        for nid in self._nodes:
            if color[nid] == WHITE:
                dfs(nid)

    def get_node(self, node_id: str) -> NodeSpec:
        return self._nodes[node_id]


class ContinuousExecutor:
    """Async DAG executor with FIRST_COMPLETED scheduling + decide lock."""

    def __init__(self, scheduler: DAGScheduler) -> None:
        self._scheduler = scheduler
        self._decide_lock = asyncio.Lock()

    async def run(self, ctx: ExecutionContext) -> ExecutionContext:
        self._scheduler.validate()
        completed: set[str] = set()
        running: set[str] = set()
        task_map: dict[asyncio.Task, str] = {}
        pending_tasks: set[asyncio.Task] = set()

        async with self._decide_lock:
            for nid in self._scheduler.find_ready_nodes(completed, running):
                task = asyncio.create_task(self._run_node(nid, ctx))
                task_map[task] = nid
                pending_tasks.add(task)
                running.add(nid)

        while pending_tasks:
            done, pending_tasks = await asyncio.wait(
                pending_tasks, return_when=asyncio.FIRST_COMPLETED
            )
            async with self._decide_lock:
                for task in done:
                    nid = task_map.pop(task)
                    running.discard(nid)
                    # Always mark as done so find_ready_nodes won't reschedule it.
                    completed.add(nid)
                    if task.exception():
                        log.warning(f"Node {nid} failed: {task.exception()}")
                    for ready_nid in self._scheduler.find_ready_nodes(completed, running):
                        new_task = asyncio.create_task(self._run_node(ready_nid, ctx))
                        task_map[new_task] = ready_nid
                        pending_tasks.add(new_task)
                        running.add(ready_nid)

        return ctx

    async def _run_node(self, node_id: str, ctx: ExecutionContext) -> Any:
        spec = self._scheduler.get_node(node_id)
        ctx.start_node(node_id)
        start = time.monotonic()
        try:
            result = await spec.handler(ctx) if spec.handler else None
            ctx.complete_node(node_id, output=result)
            elapsed = time.monotonic() - start
            log.info(f"Node {node_id} completed in {elapsed:.2f}s")
            return result
        except Exception:
            ctx.fail_node(node_id, error=str(Exception))
            raise
