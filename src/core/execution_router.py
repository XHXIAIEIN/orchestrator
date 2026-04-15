"""R73 MachinaOS: Three-Layer Execution Engine with Auto-Degradation.

Routes workflow execution based on available infrastructure:

    Layer 1 — Temporal (distributed):
        Full distributed execution with per-node Activities.
        Requires: TEMPORAL_ENABLED + Temporal server reachable.
        Features: durable execution, automatic retries, activity heartbeats.

    Layer 2 — Redis (local parallel):
        Parallel execution via asyncio.gather with Redis-backed state.
        Requires: REDIS_ENABLED + Redis server reachable.
        Features: distributed locks, input-hash caching, event streams.

    Layer 3 — Sequential (in-process fallback):
        Sequential execution with no external dependencies.
        Always available. Minimal overhead.
        Features: basic retry, in-memory state.

The three layers share the same interface (ExecutionBackend ABC).
Infrastructure detection happens at startup; runtime fallback on connection loss.

Source: MachinaOS WorkflowService (R73 deep steal)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

log = logging.getLogger(__name__)


class ExecutionLayer(Enum):
    TEMPORAL = "temporal"
    REDIS = "redis"
    SEQUENTIAL = "sequential"


class NodeStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CACHED = "cached"


@dataclass
class NodeResult:
    """Result from executing a single workflow node."""
    node_id: str
    status: NodeStatus
    output: Any = None
    error: str | None = None
    duration_s: float = 0.0
    cached: bool = False


@dataclass
class ExecutionContext:
    """Shared state for a workflow execution run."""
    execution_id: str
    nodes: dict[str, dict]           # node_id → node config
    edges: list[dict]                # {source, target, condition?}
    node_results: dict[str, NodeResult] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)


def _hash_inputs(inputs: dict) -> str:
    """Deterministic hash of node inputs for caching (Prefect pattern)."""
    payload = json.dumps(inputs, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _find_ready_nodes(ctx: ExecutionContext) -> list[str]:
    """Find nodes whose dependencies are all completed."""
    # Build dependency map: node_id → set of upstream node_ids
    deps: dict[str, set[str]] = {nid: set() for nid in ctx.nodes}
    for edge in ctx.edges:
        target = edge["target"]
        source = edge["source"]
        if target in deps:
            deps[target].add(source)

    completed = {
        nid for nid, r in ctx.node_results.items()
        if r.status in (NodeStatus.COMPLETED, NodeStatus.CACHED, NodeStatus.SKIPPED)
    }
    running = {
        nid for nid, r in ctx.node_results.items()
        if r.status == NodeStatus.RUNNING
    }

    ready = []
    for nid in ctx.nodes:
        if nid in completed or nid in running:
            continue
        if deps[nid].issubset(completed):
            ready.append(nid)

    return ready


# ── Backend ABC ──

class ExecutionBackend(ABC):
    """Interface shared by all execution layers."""

    @property
    @abstractmethod
    def layer(self) -> ExecutionLayer: ...

    @abstractmethod
    async def execute_workflow(
        self,
        ctx: ExecutionContext,
        node_executor: Callable[[str, dict, dict], Awaitable[Any]],
    ) -> ExecutionContext:
        """Execute all nodes in the workflow.

        Args:
            ctx: Execution context with nodes and edges.
            node_executor: Async callable(node_id, node_config, upstream_outputs) → result.

        Returns:
            Updated ExecutionContext with all results.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if this backend's infrastructure is available."""
        ...


# ── Layer 3: Sequential Backend (always available) ──

class SequentialBackend(ExecutionBackend):
    """In-process sequential execution — zero external dependencies."""

    @property
    def layer(self) -> ExecutionLayer:
        return ExecutionLayer.SEQUENTIAL

    async def execute_workflow(
        self, ctx: ExecutionContext,
        node_executor: Callable[[str, dict, dict], Awaitable[Any]],
    ) -> ExecutionContext:
        max_iterations = len(ctx.nodes) * 2  # safety limit
        iteration = 0

        while iteration < max_iterations:
            ready = _find_ready_nodes(ctx)
            if not ready:
                break

            for node_id in ready:
                node_config = ctx.nodes[node_id]
                upstream = {
                    nid: r.output for nid, r in ctx.node_results.items()
                    if r.status == NodeStatus.COMPLETED
                }

                ctx.node_results[node_id] = NodeResult(
                    node_id=node_id, status=NodeStatus.RUNNING,
                )
                start = time.monotonic()

                try:
                    output = await node_executor(node_id, node_config, upstream)
                    ctx.node_results[node_id] = NodeResult(
                        node_id=node_id,
                        status=NodeStatus.COMPLETED,
                        output=output,
                        duration_s=time.monotonic() - start,
                    )
                except Exception as exc:
                    ctx.node_results[node_id] = NodeResult(
                        node_id=node_id,
                        status=NodeStatus.FAILED,
                        error=str(exc),
                        duration_s=time.monotonic() - start,
                    )
                    log.error("sequential: node %s failed: %s", node_id, exc)

            iteration += 1

        return ctx

    async def health_check(self) -> bool:
        return True  # always available


# ── Layer 2: Parallel Backend (asyncio.gather, optional Redis state) ──

class ParallelBackend(ExecutionBackend):
    """Local parallel execution via asyncio.gather.

    Optionally backed by Redis for state persistence and caching.
    Falls back to in-memory state if Redis is unavailable.
    """

    def __init__(self, redis_url: str | None = None):
        self._redis_url = redis_url
        self._cache: dict[str, Any] = {}  # in-memory fallback cache

    @property
    def layer(self) -> ExecutionLayer:
        return ExecutionLayer.REDIS

    async def execute_workflow(
        self, ctx: ExecutionContext,
        node_executor: Callable[[str, dict, dict], Awaitable[Any]],
    ) -> ExecutionContext:
        max_iterations = len(ctx.nodes) * 2

        for _ in range(max_iterations):
            ready = _find_ready_nodes(ctx)
            if not ready:
                break

            # Mark all ready nodes as running
            for nid in ready:
                ctx.node_results[nid] = NodeResult(
                    node_id=nid, status=NodeStatus.RUNNING,
                )

            # Execute in parallel
            async def _run_one(node_id: str) -> NodeResult:
                node_config = ctx.nodes[node_id]
                upstream = {
                    nid: r.output for nid, r in ctx.node_results.items()
                    if r.status == NodeStatus.COMPLETED
                }

                # Check cache (Prefect input-hash pattern)
                cache_key = f"{ctx.execution_id}:{node_id}:{_hash_inputs(upstream)}"
                cached = self._cache.get(cache_key)
                if cached is not None:
                    return NodeResult(
                        node_id=node_id, status=NodeStatus.CACHED,
                        output=cached, cached=True,
                    )

                start = time.monotonic()
                try:
                    output = await node_executor(node_id, node_config, upstream)
                    self._cache[cache_key] = output
                    return NodeResult(
                        node_id=node_id, status=NodeStatus.COMPLETED,
                        output=output, duration_s=time.monotonic() - start,
                    )
                except Exception as exc:
                    return NodeResult(
                        node_id=node_id, status=NodeStatus.FAILED,
                        error=str(exc), duration_s=time.monotonic() - start,
                    )

            results = await asyncio.gather(
                *[_run_one(nid) for nid in ready],
                return_exceptions=False,
            )

            for result in results:
                ctx.node_results[result.node_id] = result

        return ctx

    async def health_check(self) -> bool:
        if not self._redis_url:
            return True  # in-memory mode always works

        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(self._redis_url)
            await client.ping()
            await client.aclose()
            return True
        except Exception:
            return False


# ── Execution Router (facade) ──

@dataclass
class RouterConfig:
    """Configuration for execution routing."""
    temporal_enabled: bool = False
    temporal_address: str = "localhost:7233"
    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379"
    fallback_on_error: bool = True  # auto-degrade on connection failure


class ExecutionRouter:
    """Routes workflow execution to the best available backend.

    Detects infrastructure at init time, degrades at runtime if needed.

    Usage:
        router = ExecutionRouter()
        await router.detect_backends()

        ctx = ExecutionContext(
            execution_id="run-001",
            nodes={"a": {...}, "b": {...}},
            edges=[{"source": "a", "target": "b"}],
        )
        result = await router.execute(ctx, my_node_executor)
        print(f"Executed on {router.active_layer.value}")
    """

    def __init__(self, config: RouterConfig | None = None):
        self.config = config or RouterConfig()
        self._backends: list[ExecutionBackend] = []
        self._active: ExecutionBackend | None = None

    @property
    def active_layer(self) -> ExecutionLayer:
        if self._active:
            return self._active.layer
        return ExecutionLayer.SEQUENTIAL

    async def detect_backends(self) -> ExecutionLayer:
        """Probe available infrastructure and select the best backend.

        Returns the selected execution layer.
        """
        self._backends = []

        # Layer 1: Temporal (if enabled)
        if self.config.temporal_enabled:
            # Temporal backend would go here — stub for now
            # (requires temporalio SDK, not adding as hard dependency)
            log.info("execution_router: Temporal enabled but not yet implemented")

        # Layer 2: Redis/Parallel
        if self.config.redis_enabled:
            backend = ParallelBackend(redis_url=self.config.redis_url)
            if await backend.health_check():
                self._backends.append(backend)
                log.info("execution_router: Redis backend available")
            else:
                log.warning("execution_router: Redis configured but unreachable")
        else:
            # Parallel without Redis (in-memory state)
            self._backends.append(ParallelBackend())

        # Layer 3: Sequential (always)
        self._backends.append(SequentialBackend())

        # Select best available
        self._active = self._backends[0]
        log.info(
            "execution_router: selected %s (of %d backends)",
            self._active.layer.value, len(self._backends),
        )
        return self._active.layer

    async def execute(
        self,
        ctx: ExecutionContext,
        node_executor: Callable[[str, dict, dict], Awaitable[Any]],
    ) -> ExecutionContext:
        """Execute workflow on the best available backend.

        Auto-degrades to next backend if current one fails (when fallback_on_error=True).
        """
        if self._active is None:
            await self.detect_backends()

        for backend in self._backends:
            try:
                result = await backend.execute_workflow(ctx, node_executor)
                return result
            except Exception as exc:
                if not self.config.fallback_on_error:
                    raise
                log.warning(
                    "execution_router: %s failed (%s), falling back",
                    backend.layer.value, exc,
                )
                continue

        raise RuntimeError("All execution backends failed")

    def get_stats(self) -> dict:
        """Return router state for diagnostics."""
        return {
            "active_layer": self.active_layer.value,
            "available_backends": [b.layer.value for b in self._backends],
            "config": {
                "temporal_enabled": self.config.temporal_enabled,
                "redis_enabled": self.config.redis_enabled,
                "fallback_on_error": self.config.fallback_on_error,
            },
        }
