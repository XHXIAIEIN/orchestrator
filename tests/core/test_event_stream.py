"""Tests for EventStream — stolen from ChatDev 2.0's ArtifactEventQueue."""
import time
import threading
import pytest
from src.core.event_stream import EventStream, StreamEvent


def test_append_and_get():
    s = EventStream(max_events=100)
    s.append(StreamEvent(event_type="test", data={"msg": "hello"}))
    events, cursor = s.get_after(0)
    assert len(events) == 1
    assert events[0].event_type == "test"
    assert events[0].sequence == 1
    assert cursor == 1


def test_cursor_based_incremental():
    s = EventStream(max_events=100)
    s.append(StreamEvent(event_type="a", data={}))
    s.append(StreamEvent(event_type="b", data={}))
    s.append(StreamEvent(event_type="c", data={}))
    events, cursor = s.get_after(0)
    assert len(events) == 3
    assert cursor == 3
    s.append(StreamEvent(event_type="d", data={}))
    events, cursor = s.get_after(3)
    assert len(events) == 1
    assert events[0].event_type == "d"
    assert cursor == 4


def test_bounded_eviction():
    s = EventStream(max_events=3)
    for i in range(5):
        s.append(StreamEvent(event_type=f"e{i}", data={}))
    events, cursor = s.get_after(0)
    assert len(events) == 3
    assert events[0].event_type == "e2"
    assert events[-1].event_type == "e4"
    assert cursor == 5


def test_stale_cursor_returns_available():
    s = EventStream(max_events=3)
    for i in range(5):
        s.append(StreamEvent(event_type=f"e{i}", data={}))
    events, cursor = s.get_after(1)
    assert len(events) == 3
    assert events[0].sequence == 3


def test_filter_by_type():
    s = EventStream(max_events=100)
    s.append(StreamEvent(event_type="log", data={"msg": "info"}))
    s.append(StreamEvent(event_type="artifact", data={"file": "a.py"}))
    s.append(StreamEvent(event_type="log", data={"msg": "warn"}))
    events, _ = s.get_after(0, event_types={"log"})
    assert len(events) == 2
    assert all(e.event_type == "log" for e in events)


def test_wait_for_events_blocking():
    s = EventStream(max_events=100)
    result = {}
    def consumer():
        events, cursor, timed_out = s.wait_for_events(after=0, timeout=5.0)
        result["events"] = events
        result["timed_out"] = timed_out
    t = threading.Thread(target=consumer, daemon=True)
    t.start()
    time.sleep(0.1)
    s.append(StreamEvent(event_type="wakeup", data={}))
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert len(result["events"]) == 1
    assert not result["timed_out"]


def test_wait_for_events_timeout():
    s = EventStream(max_events=100)
    events, cursor, timed_out = s.wait_for_events(after=0, timeout=0.2)
    assert len(events) == 0
    assert timed_out


def test_stats():
    s = EventStream(max_events=100)
    s.append(StreamEvent(event_type="a", data={}))
    s.append(StreamEvent(event_type="b", data={}))
    stats = s.stats()
    assert stats["total_appended"] == 2
    assert stats["current_size"] == 2
    assert stats["last_sequence"] == 2
