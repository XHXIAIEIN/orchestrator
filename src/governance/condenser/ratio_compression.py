# src/governance/condenser/ratio_compression.py
"""Adapter: wraps governance.compression.ContextCompressor as a Condenser.

This bridges the Hermes ratio-based compression module into the existing
OpenHands-style CondenserPipeline. Events are fed into ContextCompressor;
when the threshold is hit, older events are summarized/compressed.
"""
import logging
from .base import Condenser, View, Event

log = logging.getLogger(__name__)

try:
    from src.governance.compression import ContextCompressor
except ImportError:
    ContextCompressor = None


class RatioCompressionCondenser(Condenser):
    """Condenser that uses ratio-based compression from Hermes.

    Usage in a pipeline:
        pipeline = CondenserPipeline([
            RecentEventsCondenser(max_events=50),
            RatioCompressionCondenser(target_ratio=0.6),
        ])
    """

    def __init__(self, target_ratio: float = 0.6, threshold: float = 0.8,
                 max_context_tokens: int = 200_000, protect_last_n: int = 5):
        self._target_ratio = target_ratio
        self._threshold = threshold
        self._max_context_tokens = max_context_tokens
        self._protect_last_n = protect_last_n

    def condense(self, view: View) -> View:
        """Apply ratio-based compression to the event view."""
        if not ContextCompressor:
            return view

        events = view.events
        if not events:
            return view

        compressor = ContextCompressor(
            max_context_tokens=self._max_context_tokens,
            target_ratio=self._target_ratio,
            protect_last_n=self._protect_last_n,
            threshold=self._threshold,
        )

        # Feed events as turns
        for evt in events:
            compressor.add_turn(
                role=evt.source,
                content=evt.content,
                tokens=max(len(evt.content) // 3, 1),
            )

        if not compressor.should_compress():
            return view

        result = compressor.compress()
        if not result.get("compressed"):
            return view

        # Build new event list: compressed summary + protected recent events
        protected_count = min(self._protect_last_n, len(events))
        protected_events = events[-protected_count:] if protected_count > 0 else []

        # Create a summary event for the compressed portion
        compressed_count = len(events) - protected_count
        summary_text = f"[COMPRESSED: {compressed_count} events, {result.get('tokens_saved', 0)} tokens saved]"
        summary_event = Event(
            id=-1,
            event_type="system",
            source="condenser",
            content=summary_text,
            metadata={"compression": result},
            condensed=True,
        )

        new_events = [summary_event] + protected_events
        log.info(
            f"ratio_compression: {len(events)} → {len(new_events)} events "
            f"({result.get('tokens_saved', 0)} tokens saved)"
        )
        return View(new_events)
