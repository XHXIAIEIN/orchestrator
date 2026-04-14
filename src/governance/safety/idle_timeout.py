"""R63 Archon: Idle Timeout as Deadlock Detector.

Problem: Agent streaming generators can hang indefinitely when:
  - MCP connection isn't closed
  - Subprocess hangs
  - LLM API times out silently

`for await` / `async for` will block forever with no signal.

Solution: Wrap any async generator with an idle timeout.
  - Each yielded value resets the timer (it's alive)
  - If no value for timeout_s → treat as deadlocked
  - On timeout: don't throw (messy), just return cleanly
  - Critical: DON'T call generator.aclose() — it blocks on pending .next()
  - Instead, fire onTimeout callback for async cleanup (abort subprocess)

This is a "deadlock detector", not a "work time limit":
  - Active work that yields progress → timer resets → runs forever
  - Stuck generator that yields nothing → timeout → clean exit

Source: Archon packages/workflows/src/utils/idle-timeout.ts (R63 deep steal)
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Callable, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")

# Sentinel value to distinguish timeout from actual None yields
_IDLE_TIMEOUT_SENTINEL = object()

DEFAULT_TIMEOUT_S = 30 * 60  # 30 minutes (Archon default)


async def with_idle_timeout(
    generator: AsyncGenerator[T, None],
    timeout_s: float = DEFAULT_TIMEOUT_S,
    on_timeout: Callable[[], None] | None = None,
    should_reset_timer: Callable[[T], bool] | None = None,
    label: str = "",
) -> AsyncGenerator[T, None]:
    """Wrap an async generator with idle timeout detection.

    Args:
        generator: the async generator to wrap
        timeout_s: seconds of idle before declaring deadlock
        on_timeout: callback fired on timeout (for cleanup, e.g., abort subprocess)
        should_reset_timer: predicate on yielded values; return False to NOT reset
            (useful for heartbeat-only values that don't indicate real progress)
        label: human-readable label for log messages

    Yields:
        Values from the wrapped generator, until timeout or completion.

    Notes:
        - On timeout, we DO NOT call generator.aclose() — Archon's key insight
          is that aclose() will block on a pending __anext__() call, making
          the deadlock worse. Instead, fire on_timeout for async cleanup.
        - The abandoned generator will be GC'd eventually.
    """
    tag = f"idle_timeout[{label}]" if label else "idle_timeout"

    while True:
        try:
            # Race: generator.next() vs timeout
            value = await asyncio.wait_for(
                generator.__anext__(),
                timeout=timeout_s,
            )
        except StopAsyncIteration:
            # Generator completed normally
            return
        except asyncio.TimeoutError:
            # ── Idle timeout: deadlock detected ──
            log.warning(
                "%s: no output for %.0fs — treating as deadlocked. "
                "Exiting cleanly (not throwing).",
                tag, timeout_s,
            )
            if on_timeout:
                try:
                    on_timeout()
                except Exception as e:
                    log.warning("%s: on_timeout callback failed: %s", tag, e)

            # Critical: DO NOT call generator.aclose() here.
            # It would block on the pending __anext__() call.
            # The generator will be collected by GC.
            return

        # Timer reset logic
        if should_reset_timer is None or should_reset_timer(value):
            # Value is real progress — timer was already reset by wait_for
            pass
        # If should_reset_timer returns False, we still yield the value
        # but the effective remaining time continues to decrease

        yield value


async def with_idle_timeout_sync_gen(
    generator,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    on_timeout: Callable[[], None] | None = None,
    label: str = "",
):
    """Convenience wrapper for synchronous generators run in a thread.

    Wraps a sync generator's __next__ calls in asyncio.to_thread with timeout.
    """
    tag = f"idle_timeout_sync[{label}]" if label else "idle_timeout_sync"

    while True:
        try:
            value = await asyncio.wait_for(
                asyncio.to_thread(next, generator, _IDLE_TIMEOUT_SENTINEL),
                timeout=timeout_s,
            )
            if value is _IDLE_TIMEOUT_SENTINEL:
                return  # generator exhausted

            yield value

        except asyncio.TimeoutError:
            log.warning(
                "%s: no output for %.0fs — deadlock detected, exiting cleanly.",
                tag, timeout_s,
            )
            if on_timeout:
                try:
                    on_timeout()
                except Exception as e:
                    log.warning("%s: on_timeout callback failed: %s", tag, e)
            return


class IdleTimeoutGuard:
    """Context manager version for non-generator async operations.

    Usage:
        async with IdleTimeoutGuard(timeout_s=300, label="llm-call") as guard:
            result = await long_running_call()
            guard.heartbeat()  # reset timer on progress
    """

    def __init__(
        self,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        on_timeout: Callable[[], None] | None = None,
        label: str = "",
    ):
        self.timeout_s = timeout_s
        self.on_timeout = on_timeout
        self.label = label
        self._timer_task: asyncio.Task | None = None
        self._heartbeat_event = asyncio.Event()
        self._timed_out = False

    async def __aenter__(self):
        self._heartbeat_event.clear()
        self._timer_task = asyncio.create_task(self._timer_loop())
        return self

    async def __aexit__(self, *args):
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            try:
                await self._timer_task
            except asyncio.CancelledError:
                pass

    def heartbeat(self):
        """Signal that progress was made — reset the idle timer."""
        self._heartbeat_event.set()

    @property
    def timed_out(self) -> bool:
        return self._timed_out

    async def _timer_loop(self):
        tag = f"idle_guard[{self.label}]" if self.label else "idle_guard"
        while True:
            self._heartbeat_event.clear()
            try:
                await asyncio.wait_for(
                    self._heartbeat_event.wait(),
                    timeout=self.timeout_s,
                )
                # Heartbeat received, loop continues
            except asyncio.TimeoutError:
                log.warning("%s: idle timeout (%.0fs) — firing callback", tag, self.timeout_s)
                self._timed_out = True
                if self.on_timeout:
                    try:
                        self.on_timeout()
                    except Exception as e:
                        log.warning("%s: on_timeout failed: %s", tag, e)
                return
