# src/governance/condenser/amortized_forgetting.py
"""Drop middle events, keep head (instructions) and tail (recent context)."""
from .base import Condenser, View


class AmortizedForgettingCondenser(Condenser):
    def __init__(self, max_events: int = 100, keep_head: int = 10, keep_tail: int = 30):
        self.max_events = max_events
        self.keep_head = keep_head
        self.keep_tail = keep_tail

    def condense(self, view: View) -> View:
        if len(view) <= self.max_events:
            return view
        events = view.events
        head = events[:self.keep_head]
        tail = events[-self.keep_tail:]
        # Mark gap
        from .base import Event
        gap = Event(
            id=-1, event_type="system", source="condenser",
            content=f"[{len(events) - self.keep_head - self.keep_tail} events condensed]",
            condensed=True,
        )
        return View(head + [gap] + tail)
