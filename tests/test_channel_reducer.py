"""Tests for Channel-Reducer protocol (R43 — LangGraph steal)."""

import operator

import pytest

from src.governance.channel_reducer import (
    AppendChannel,
    EmptyChannelError,
    LastValueChannel,
    MergeChannel,
    ReducerChannel,
)


# ── LastValueChannel ──────────────────────────────────────────


class TestLastValueChannel:
    def test_keeps_last_value(self):
        ch = LastValueChannel(str)
        ch.update(["a", "b", "c"])
        assert ch.get() == "c"

    def test_multiple_updates_overwrites(self):
        ch = LastValueChannel(int)
        ch.update([1])
        ch.update([2])
        ch.update([3])
        assert ch.get() == 3

    def test_empty_update_no_change(self):
        ch = LastValueChannel(int)
        ch.update([42])
        assert ch.update([]) is False
        assert ch.get() == 42

    def test_get_before_update_raises(self):
        ch = LastValueChannel(str)
        with pytest.raises(EmptyChannelError):
            ch.get()

    def test_consume_resets(self):
        ch = LastValueChannel(str)
        ch.update(["hello"])
        assert ch.consume() is True
        with pytest.raises(EmptyChannelError):
            ch.get()

    def test_consume_empty_returns_false(self):
        ch = LastValueChannel(str)
        assert ch.consume() is False

    def test_finish_always_true(self):
        ch = LastValueChannel(str)
        assert ch.finish() is True


# ── ReducerChannel ────────────────────────────────────────────


class TestReducerChannel:
    def test_add_reducer(self):
        ch = ReducerChannel(operator.add, int, 0)
        ch.update([1])
        ch.update([2])
        assert ch.get() == 3

    def test_batch_update(self):
        ch = ReducerChannel(operator.add, int, 0)
        ch.update([1, 2, 3])
        assert ch.get() == 6

    def test_dict_merge_reducer(self):
        ch = ReducerChannel(lambda a, b: {**a, **b}, dict, {})
        ch.update([{"a": 1}])
        ch.update([{"b": 2}])
        assert ch.get() == {"a": 1, "b": 2}

    def test_or_reducer_for_sets(self):
        ch = ReducerChannel(operator.or_, set, set())
        ch.update([{1, 2}])
        ch.update([{3}])
        assert ch.get() == {1, 2, 3}

    def test_consume_resets_to_initial(self):
        ch = ReducerChannel(operator.add, int, 0)
        ch.update([10])
        ch.consume()
        assert ch.get() == 0

    def test_empty_update_no_change(self):
        ch = ReducerChannel(operator.add, int, 0)
        assert ch.update([]) is False
        assert ch.get() == 0

    def test_initial_value_accessible(self):
        ch = ReducerChannel(operator.add, int, 100)
        assert ch.get() == 100


# ── AppendChannel ─────────────────────────────────────────────


class TestAppendChannel:
    def test_accumulates(self):
        ch = AppendChannel(str)
        ch.update(["a"])
        ch.update(["b", "c"])
        assert ch.get() == ["a", "b", "c"]

    def test_consume_clears(self):
        ch = AppendChannel(str)
        ch.update(["x"])
        assert ch.consume() is True
        with pytest.raises(EmptyChannelError):
            ch.get()

    def test_consume_empty_returns_false(self):
        ch = AppendChannel(int)
        assert ch.consume() is False

    def test_get_empty_raises(self):
        ch = AppendChannel(int)
        with pytest.raises(EmptyChannelError):
            ch.get()

    def test_get_returns_copy(self):
        ch = AppendChannel(int)
        ch.update([1, 2])
        result = ch.get()
        result.append(99)
        assert ch.get() == [1, 2]  # original unmodified

    def test_empty_update_no_change(self):
        ch = AppendChannel(str)
        assert ch.update([]) is False


# ── MergeChannel ──────────────────────────────────────────────


class TestMergeChannel:
    def test_field_level_reduction(self):
        mc = MergeChannel({
            "messages": AppendChannel(str),
            "status": LastValueChannel(str),
            "count": ReducerChannel(operator.add, int, 0),
        })
        mc.update({
            "messages": ["hello"],
            "status": ["running"],
            "count": [1],
        })
        mc.update({
            "messages": ["world"],
            "status": ["done"],
            "count": [2],
        })
        result = mc.get()
        assert result["messages"] == ["hello", "world"]
        assert result["status"] == "done"
        assert result["count"] == 3

    def test_partial_update(self):
        mc = MergeChannel({
            "a": LastValueChannel(str),
            "b": LastValueChannel(str),
        })
        mc.update({"a": ["only-a"]})
        result = mc.get()
        assert result == {"a": "only-a"}  # b omitted (empty)

    def test_unknown_field_ignored(self):
        mc = MergeChannel({"x": LastValueChannel(int)})
        mc.update({"x": [1], "unknown": [99]})
        assert mc.get() == {"x": 1}

    def test_consume_all(self):
        mc = MergeChannel({
            "a": AppendChannel(str),
            "b": LastValueChannel(int),
        })
        mc.update({"a": ["hi"], "b": [42]})
        assert mc.consume() is True
        assert mc.get() == {}  # all consumed

    def test_finish(self):
        mc = MergeChannel({
            "a": AppendChannel(str),
            "b": ReducerChannel(operator.add, int, 0),
        })
        assert mc.finish() is True
