"""R52 (VoxCPM): Generator cleanup utilities — next_and_close pattern.

Prevents resource leaks from partially-consumed generators/async generators.
When a generator wraps torch.inference_mode() or holds file handles, relying
on GC to call __del__ / GeneratorExit is fragile and timing-dependent.

Stolen from: VoxCPM model/utils.py — next_and_close()
Adapted for: async generators from claude_agent_sdk.query()
"""
from typing import AsyncGenerator, Generator, TypeVar

T = TypeVar("T")


def next_and_close(gen: Generator[T, None, None]) -> T:
    """Get first value from a generator, then forcefully close it.

    Ensures GeneratorExit is sent immediately rather than waiting for GC.
    Use when you only need one result from a generator that holds resources.
    """
    try:
        return next(gen)
    finally:
        gen.close()


async def anext_and_close(gen: AsyncGenerator[T, None]) -> T:
    """Async version of next_and_close for async generators.

    Use when you only need the first yielded value from an async generator
    (e.g., getting the first result from an Agent SDK query).
    """
    try:
        return await gen.__anext__()
    finally:
        await gen.aclose()


async def acollect_and_close(gen: AsyncGenerator[T, None]) -> list[T]:
    """Consume all items from an async generator with guaranteed cleanup.

    Wraps `async for` in try/finally to ensure .aclose() is called
    even if the consumer breaks early or an exception occurs mid-iteration.
    """
    items: list[T] = []
    try:
        async for item in gen:
            items.append(item)
    finally:
        await gen.aclose()
    return items
