"""Tests for R73 EventWaiter unified trigger system."""
import asyncio
import pytest
from src.core.event_waiter import (
    MemoryEventWaiter, EventFilter, TRIGGER_REGISTRY,
    wait_for_trigger,
)


@pytest.fixture
def waiter():
    return MemoryEventWaiter()


class TestTriggerRegistry:
    def test_known_triggers_exist(self):
        assert "webhookTrigger" in TRIGGER_REGISTRY
        assert "chatTrigger" in TRIGGER_REGISTRY
        assert "telegramReceive" in TRIGGER_REGISTRY

    def test_trigger_config_fields(self):
        cfg = TRIGGER_REGISTRY["webhookTrigger"]
        assert cfg.trigger_type == "webhookTrigger"
        assert cfg.event_name == "webhook_received"
        assert cfg.timeout_s > 0


class TestEventFilter:
    def test_matches_event_name(self):
        f = EventFilter(event_name="webhook_received")
        assert f.matches({"event_name": "webhook_received"})
        assert not f.matches({"event_name": "chat_message_received"})

    def test_matches_with_fields(self):
        f = EventFilter(event_name="task_completed", match_fields={"task_id": 42})
        assert f.matches({"event_name": "task_completed", "task_id": 42})
        assert not f.matches({"event_name": "task_completed", "task_id": 99})


class TestMemoryEventWaiter:
    @pytest.mark.asyncio
    async def test_register_and_dispatch(self, waiter):
        wid = await waiter.register("webhookTrigger")

        event = {"event_name": "webhook_received", "payload": "test"}
        satisfied = await waiter.dispatch(event)
        assert wid in satisfied

    @pytest.mark.asyncio
    async def test_wait_receives_event(self, waiter):
        wid = await waiter.register("chatTrigger", timeout_s=5.0)

        async def send_later():
            await asyncio.sleep(0.1)
            await waiter.dispatch({"event_name": "chat_message_received", "text": "hello"})

        asyncio.create_task(send_later())
        result = await waiter.wait_for_event(wid)
        assert result["text"] == "hello"

    @pytest.mark.asyncio
    async def test_timeout_raises(self, waiter):
        wid = await waiter.register("webhookTrigger", timeout_s=0.1)
        with pytest.raises(asyncio.TimeoutError):
            await waiter.wait_for_event(wid)

    @pytest.mark.asyncio
    async def test_cancel_waiter(self, waiter):
        wid = await waiter.register("chatTrigger")
        result = await waiter.cancel(wid)
        assert result is True

    @pytest.mark.asyncio
    async def test_unknown_trigger_raises(self, waiter):
        with pytest.raises(ValueError, match="Unknown trigger"):
            await waiter.register("nonexistentTrigger")

    @pytest.mark.asyncio
    async def test_dispatch_no_match(self, waiter):
        await waiter.register("webhookTrigger")
        # Dispatch a non-matching event
        satisfied = await waiter.dispatch({"event_name": "unrelated_event"})
        assert len(satisfied) == 0

    @pytest.mark.asyncio
    async def test_stats(self, waiter):
        await waiter.register("webhookTrigger")
        stats = waiter.get_stats()
        assert stats["pending_waiters"] == 1
        assert "registered_triggers" in stats


class TestWaitForTrigger:
    @pytest.mark.asyncio
    async def test_one_shot_convenience(self):
        waiter = MemoryEventWaiter()

        async def send_event():
            await asyncio.sleep(0.1)
            await waiter.dispatch({"event_name": "webhook_received", "data": 123})

        asyncio.create_task(send_event())
        result = await wait_for_trigger(waiter, "webhookTrigger", timeout_s=5.0)
        assert result["data"] == 123
