# src/governance/condenser/recent_events.py
"""Keep only the most recent N events."""
from .base import Condenser, View


class RecentEventsCondenser(Condenser):
    def __init__(self, max_events: int = 50):
        self.max_events = max_events

    def condense(self, view: View) -> View:
        if len(view) <= self.max_events:
            return view
        return View(view.events[-self.max_events:])
