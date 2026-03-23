# src/governance/condenser/base.py
"""Condenser base classes. Inspired by OpenHands condenser architecture."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Event:
    """Minimal typed event for condenser processing."""
    id: int
    event_type: str  # "action" | "observation" | "system"
    source: str      # "agent" | "user" | "environment"
    content: str
    metadata: dict = field(default_factory=dict)
    condensed: bool = False


class View:
    """Immutable view over an event list. Condensers produce new Views."""

    def __init__(self, events: list[Event]):
        self._events = list(events)

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def token_estimate(self) -> int:
        """Rough token estimate (~1.3 tokens per word)."""
        total_chars = sum(len(e.content) for e in self._events)
        return int(total_chars / 3.5)


class Condenser(ABC):
    """Abstract condenser. Takes a View, returns a compressed View."""

    @abstractmethod
    def condense(self, view: View) -> View:
        ...
