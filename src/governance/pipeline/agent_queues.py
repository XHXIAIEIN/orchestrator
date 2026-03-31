"""Agent Queues — per-agent output isolation for parallel dispatch.

Stolen from: microsoft/VibeVoice (Round 17)
Pattern: Per-Sample Streaming with Queue Isolation (AudioStreamer)

VibeVoice gives each batch sample its own Queue + finished_flag so one
sample completing doesn't block others. For Orchestrator: each parallel
sub-agent gets an independent output queue.

Key features:
  - Independent queues per agent (no cross-contamination)
  - Per-agent finished flags (partial completion)
  - Async-safe: results pushed from worker threads via call_soon_threadsafe
  - Stream results as they arrive (iterator interface)
  - Timeout-aware get() to prevent infinite blocking

Usage:
    streamer = AgentStreamer(agent_ids=["agent-1", "agent-2", "agent-3"])

    # Worker thread pushes results
    streamer.put("agent-1", {"turn": 1, "output": "..."})
    streamer.put("agent-2", {"turn": 1, "output": "..."})
    streamer.end("agent-1")  # agent-1 is done

    # Consumer reads results
    for result in streamer.get_stream("agent-1"):
        process(result)

    # Check completion
    streamer.all_finished()  # False (agent-2, agent-3 still running)
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from queue import Queue, Empty
from typing import Any, Iterator

log = logging.getLogger(__name__)

# Sentinel value to signal end of stream
_STREAM_END = object()


@dataclass
class AgentOutput:
    """Single output chunk from an agent."""
    agent_id: str
    data: Any
    turn: int = 0
    is_final: bool = False


class AgentStreamer:
    """Synchronous per-agent output queue manager.

    Each agent gets its own Queue and finished flag.
    Thread-safe: worker threads can push, main thread can read.
    """

    def __init__(self, agent_ids: list[str]):
        self._queues: dict[str, Queue] = {
            aid: Queue() for aid in agent_ids
        }
        self._finished: dict[str, bool] = {
            aid: False for aid in agent_ids
        }
        self._lock = threading.Lock()

    @property
    def agent_ids(self) -> list[str]:
        return list(self._queues.keys())

    def put(self, agent_id: str, data: Any, turn: int = 0) -> None:
        """Push a result chunk to an agent's queue.

        Thread-safe. Can be called from any thread.
        """
        q = self._queues.get(agent_id)
        if q is None:
            log.warning(f"AgentStreamer: unknown agent_id={agent_id}")
            return

        with self._lock:
            if self._finished.get(agent_id, False):
                log.debug(f"AgentStreamer: ignoring put for finished agent {agent_id}")
                return

        q.put(AgentOutput(agent_id=agent_id, data=data, turn=turn))

    def end(self, agent_ids: list[str] | str | None = None) -> None:
        """Mark agent(s) as finished.

        Like VibeVoice's AudioStreamer.end(sample_indices): can end
        specific agents or all of them.
        """
        if agent_ids is None:
            targets = list(self._queues.keys())
        elif isinstance(agent_ids, str):
            targets = [agent_ids]
        else:
            targets = agent_ids

        with self._lock:
            for aid in targets:
                if aid in self._finished and not self._finished[aid]:
                    self._finished[aid] = True
                    # Push sentinel to unblock waiting consumers
                    if aid in self._queues:
                        self._queues[aid].put(_STREAM_END)

    def is_finished(self, agent_id: str) -> bool:
        """Check if a specific agent has finished."""
        with self._lock:
            return self._finished.get(agent_id, False)

    def all_finished(self) -> bool:
        """Check if all agents have finished."""
        with self._lock:
            return all(self._finished.values())

    def get_stream(self, agent_id: str, timeout: float = 1.0) -> Iterator[AgentOutput]:
        """Iterate output chunks from a specific agent.

        Blocks up to `timeout` seconds waiting for each chunk.
        Stops when the agent is marked as finished.
        """
        q = self._queues.get(agent_id)
        if q is None:
            return

        while True:
            try:
                item = q.get(timeout=timeout)
                if item is _STREAM_END:
                    return
                yield item
            except Empty:
                # Check if agent finished while we were waiting
                if self.is_finished(agent_id):
                    # Drain remaining items
                    while not q.empty():
                        item = q.get_nowait()
                        if item is _STREAM_END:
                            return
                        yield item
                    return
                # Not finished, keep waiting
                continue

    def get_latest(self, agent_id: str) -> AgentOutput | None:
        """Non-blocking: get the most recent output chunk, or None."""
        q = self._queues.get(agent_id)
        if q is None:
            return None
        latest = None
        while not q.empty():
            try:
                item = q.get_nowait()
                if item is _STREAM_END:
                    break
                latest = item
            except Empty:
                break
        return latest

    def collect_all(self, agent_id: str) -> list[AgentOutput]:
        """Collect all available outputs for an agent (non-blocking drain)."""
        q = self._queues.get(agent_id)
        if q is None:
            return []
        results = []
        while not q.empty():
            try:
                item = q.get_nowait()
                if item is _STREAM_END:
                    break
                results.append(item)
            except Empty:
                break
        return results

    def stats(self) -> dict:
        """Queue statistics for monitoring."""
        with self._lock:
            return {
                "agents": len(self._queues),
                "finished": sum(1 for v in self._finished.values() if v),
                "pending": sum(1 for v in self._finished.values() if not v),
                "queue_sizes": {
                    aid: q.qsize() for aid, q in self._queues.items()
                },
            }


class AsyncAgentStreamer:
    """Async-aware per-agent output queue manager.

    Like VibeVoice's AsyncAudioStreamer: uses asyncio.Queue and
    loop.call_soon_threadsafe for safe cross-thread pushing.
    """

    def __init__(self, agent_ids: list[str], loop: asyncio.AbstractEventLoop | None = None):
        self._loop = loop or asyncio.get_event_loop()
        self._queues: dict[str, asyncio.Queue] = {
            aid: asyncio.Queue() for aid in agent_ids
        }
        self._finished: dict[str, bool] = {
            aid: False for aid in agent_ids
        }

    def put_threadsafe(self, agent_id: str, data: Any, turn: int = 0) -> None:
        """Push result from a worker thread into the async queue.

        Uses call_soon_threadsafe to safely cross the thread boundary,
        matching VibeVoice's AsyncAudioStreamer pattern.
        """
        q = self._queues.get(agent_id)
        if q is None or self._finished.get(agent_id, False):
            return

        output = AgentOutput(agent_id=agent_id, data=data, turn=turn)
        self._loop.call_soon_threadsafe(q.put_nowait, output)

    def end_threadsafe(self, agent_ids: list[str] | str | None = None) -> None:
        """Mark agent(s) as finished from a worker thread."""
        if agent_ids is None:
            targets = list(self._queues.keys())
        elif isinstance(agent_ids, str):
            targets = [agent_ids]
        else:
            targets = agent_ids

        for aid in targets:
            if aid in self._finished and not self._finished[aid]:
                self._finished[aid] = True
                if aid in self._queues:
                    self._loop.call_soon_threadsafe(
                        self._queues[aid].put_nowait, _STREAM_END
                    )

    async def get_stream(self, agent_id: str) -> AsyncIterator:
        """Async iterate output chunks from a specific agent."""
        q = self._queues.get(agent_id)
        if q is None:
            return

        while True:
            item = await q.get()
            if item is _STREAM_END:
                return
            yield item

    def all_finished(self) -> bool:
        return all(self._finished.values())
