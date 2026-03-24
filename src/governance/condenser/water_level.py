# src/governance/condenser/water_level.py
"""Water-level trigger — auto-compress when context approaches capacity.

Inspired by claude-code-tips: stop hook at 85% context window.
Instead of stopping, we trigger the condenser pipeline to reclaim space.
"""
from __future__ import annotations

import logging

from .base import Condenser, View

log = logging.getLogger(__name__)

# Default context window budget (tokens)
DEFAULT_MAX_TOKENS = 128_000
# Trigger compression when usage exceeds this ratio
DEFAULT_HIGH_WATER = 0.85
# Compress down to this ratio
DEFAULT_LOW_WATER = 0.60


class WaterLevelCondenser(Condenser):
    """Conditional condenser that only activates when token usage is high.

    Wraps an inner condenser (or pipeline) and only triggers it when
    the estimated token usage exceeds the high water mark.
    """

    def __init__(
        self,
        inner: Condenser,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        high_water: float = DEFAULT_HIGH_WATER,
        low_water: float = DEFAULT_LOW_WATER,
    ):
        self.inner = inner
        self.max_tokens = max_tokens
        self.high_water = high_water
        self.low_water = low_water
        self._compress_count = 0

    def condense(self, view: View) -> View:
        current_tokens = view.token_estimate()
        threshold = int(self.max_tokens * self.high_water)

        if current_tokens <= threshold:
            return view

        log.info(
            f"WaterLevel: {current_tokens}/{self.max_tokens} tokens "
            f"({current_tokens / self.max_tokens:.0%}) exceeds {self.high_water:.0%} — compressing"
        )

        result = self.inner.condense(view)
        self._compress_count += 1

        new_tokens = result.token_estimate()
        log.info(
            f"WaterLevel: compressed {current_tokens} → {new_tokens} tokens "
            f"(saved {current_tokens - new_tokens}, total compressions: {self._compress_count})"
        )

        return result

    @property
    def compress_count(self) -> int:
        return self._compress_count
