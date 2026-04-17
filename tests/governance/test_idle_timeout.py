"""Tests for R63 idle timeout deadlock detection."""
import asyncio
import pytest
from src.governance.safety.idle_timeout import with_idle_timeout, IdleTimeoutGuard


async def _producing_gen():
    for i in range(3):
        await asyncio.sleep(0.01)
        yield i


async def _hanging_gen():
    yield 0
    await asyncio.sleep(10)  # 模拟死锁


@pytest.mark.asyncio
async def test_with_idle_timeout_passes_through_values():
    results = []
    async for v in with_idle_timeout(_producing_gen(), timeout_s=1.0, label="ok"):
        results.append(v)
    assert results == [0, 1, 2]


@pytest.mark.asyncio
async def test_with_idle_timeout_exits_cleanly_on_deadlock():
    fired = []
    async for v in with_idle_timeout(
        _hanging_gen(),
        timeout_s=0.1,
        on_timeout=lambda: fired.append(True),
        label="deadlock",
    ):
        pass
    assert fired == [True]


@pytest.mark.asyncio
async def test_idle_timeout_guard_heartbeat_prevents_timeout():
    async with IdleTimeoutGuard(timeout_s=0.2, label="hb") as g:
        for _ in range(3):
            await asyncio.sleep(0.1)
            g.heartbeat()
    assert g.timed_out is False
