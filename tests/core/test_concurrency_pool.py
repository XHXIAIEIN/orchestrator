"""Tests for Unified Concurrency Pool."""
import time
from src.core.concurrency_pool import ConcurrencyPool, Slot


def test_acquire_and_release():
    pool = ConcurrencyPool(max_concurrent=3)
    slot = pool.acquire("test_owner")
    assert slot is not None
    assert pool.active_count == 1
    pool.release(slot)
    assert pool.active_count == 0


def test_pool_full_rejects():
    pool = ConcurrencyPool(max_concurrent=2)
    s1 = pool.acquire("a")
    s2 = pool.acquire("b")
    s3 = pool.acquire("c")
    assert s1 is not None
    assert s2 is not None
    assert s3 is None  # rejected
    assert pool.active_count == 2


def test_release_frees_slot():
    pool = ConcurrencyPool(max_concurrent=1)
    s1 = pool.acquire("a")
    assert pool.acquire("b") is None  # full
    pool.release(s1)
    s2 = pool.acquire("b")
    assert s2 is not None


def test_ttl_expiry():
    pool = ConcurrencyPool(max_concurrent=1)
    slot = pool.acquire("a", ttl=0)  # instant expiry
    time.sleep(0.01)
    # Expired slot should be cleaned up, freeing the pool
    assert pool.active_count == 0
    s2 = pool.acquire("b")
    assert s2 is not None


def test_release_by_owner():
    pool = ConcurrencyPool(max_concurrent=5)
    pool.acquire("collector:git")
    pool.acquire("collector:git")
    pool.acquire("agent:task_1")
    released = pool.release_by_owner("collector:git")
    assert released == 2
    assert pool.active_count == 1


def test_available():
    pool = ConcurrencyPool(max_concurrent=3)
    assert pool.available == 3
    pool.acquire("a")
    assert pool.available == 2


def test_list_active():
    pool = ConcurrencyPool(max_concurrent=3)
    pool.acquire("collector:git", ttl=60)
    pool.acquire("agent:42", ttl=120)
    active = pool.list_active()
    assert len(active) == 2
    owners = {a["owner"] for a in active}
    assert "collector:git" in owners
    assert "agent:42" in owners


def test_stats():
    pool = ConcurrencyPool(max_concurrent=2)
    s1 = pool.acquire("a")
    pool.acquire("b")
    pool.acquire("c")  # rejected
    pool.release(s1)
    stats = pool.get_stats()
    assert stats["acquired"] == 2
    assert stats["released"] == 1
    assert stats["rejected"] == 1


def test_metadata():
    pool = ConcurrencyPool(max_concurrent=5)
    slot = pool.acquire("test", metadata={"task_id": 42})
    assert slot.metadata == {"task_id": 42}
