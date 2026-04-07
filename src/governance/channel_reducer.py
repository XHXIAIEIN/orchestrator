"""Channel-Reducer protocol — deterministic parallel state aggregation.

Stolen from: LangGraph's Channel abstraction (Round 43).
LangGraph models state as typed channels with explicit reducers,
enabling deterministic aggregation of parallel node outputs.
This replaces naive string concatenation in GroupOrchestrationSupervisor.aggregate().

Four channel types:
  - LastValueChannel: keeps the most recent value (like LangGraph's LastValue)
  - ReducerChannel: applies a binary reducer fn (like BinaryOperatorAggregate)
  - AppendChannel: accumulates into a list (like Topic)
  - MergeChannel: composite — each field has its own channel type
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Optional, Protocol, TypeVar

T = TypeVar("T")


class EmptyChannelError(Exception):
    """Raised when reading from a channel that has no value."""


class ChannelProtocol(Protocol):
    """ABC for typed state channels."""

    def update(self, values: list[Any]) -> bool:
        """Apply one or more values. Returns True if state changed."""
        ...

    def get(self) -> Any:
        """Return current value. Raises EmptyChannelError if unset."""
        ...

    def consume(self) -> bool:
        """Read and reset. Returns True if there was a value to consume."""
        ...

    def finish(self) -> bool:
        """Signal end of superstep. Returns True if channel is in valid state."""
        ...


@dataclass
class LastValueChannel(Generic[T]):
    """Stores the most recent value. Multiple updates → last one wins."""

    value_type: type
    _value: Optional[T] = field(default=None, init=False, repr=False)
    _has_value: bool = field(default=False, init=False, repr=False)

    def update(self, values: list[T]) -> bool:
        if not values:
            return False
        self._value = values[-1]
        self._has_value = True
        return True

    def get(self) -> T:
        if not self._has_value:
            raise EmptyChannelError(f"LastValueChannel({self.value_type.__name__}) has no value")
        return self._value

    def consume(self) -> bool:
        had = self._has_value
        self._value = None
        self._has_value = False
        return had

    def finish(self) -> bool:
        return True


@dataclass
class ReducerChannel(Generic[T]):
    """Applies a binary reducer to accumulate values.

    Example: ReducerChannel(operator.add, int, 0) → sums all updates.
    """

    reducer: Callable[[T, T], T]
    value_type: type
    initial: T
    _value: Optional[T] = field(default=None, init=False, repr=False)
    _initialized: bool = field(default=False, init=False, repr=False)

    def __post_init__(self):
        self._value = self.initial
        self._initialized = True

    def update(self, values: list[T]) -> bool:
        if not values:
            return False
        for v in values:
            self._value = self.reducer(self._value, v)
        return True

    def get(self) -> T:
        if not self._initialized:
            raise EmptyChannelError(f"ReducerChannel({self.value_type.__name__}) not initialized")
        return self._value

    def consume(self) -> bool:
        had = self._initialized
        self._value = self.initial
        return had

    def finish(self) -> bool:
        return True


@dataclass
class AppendChannel(Generic[T]):
    """Accumulates values into a list. consume() clears."""

    value_type: type
    _values: list[T] = field(default_factory=list, init=False, repr=False)

    def update(self, values: list[T]) -> bool:
        if not values:
            return False
        self._values.extend(values)
        return True

    def get(self) -> list[T]:
        if not self._values:
            raise EmptyChannelError(f"AppendChannel({self.value_type.__name__}) is empty")
        return list(self._values)

    def consume(self) -> bool:
        had = bool(self._values)
        self._values.clear()
        return had

    def finish(self) -> bool:
        return True


@dataclass
class MergeChannel:
    """Composite channel — each field has its own channel type.

    Usage:
        mc = MergeChannel({
            "messages": AppendChannel(str),
            "status": LastValueChannel(str),
            "artifacts": ReducerChannel(operator.or_, dict, {}),
        })
        mc.update({"messages": ["hello"], "status": ["done"]})
        mc.get()  # {"messages": [...], "status": "done", "artifacts": {...}}
    """

    fields: dict[str, Any]  # str -> ChannelProtocol instance

    def update(self, values: dict[str, list]) -> bool:
        """Update individual field channels.

        Args:
            values: mapping of field_name -> list of values for that channel
        """
        changed = False
        for field_name, field_values in values.items():
            if field_name in self.fields:
                if self.fields[field_name].update(field_values):
                    changed = True
        return changed

    def get(self) -> dict[str, Any]:
        """Return dict of all field values. Skips empty channels."""
        result = {}
        for field_name, channel in self.fields.items():
            try:
                result[field_name] = channel.get()
            except EmptyChannelError:
                pass
        return result

    def consume(self) -> bool:
        consumed = False
        for channel in self.fields.values():
            if channel.consume():
                consumed = True
        return consumed

    def finish(self) -> bool:
        return all(ch.finish() for ch in self.fields.values())
