"""BlueprintBuilder — orchestrates perception layers to build UIBlueprint.

Runs layers in order. If a layer sets needs_fallback=True, the next layer
runs. Elements and zones accumulate across layers.
"""
from __future__ import annotations

import logging
import time

from .types import UIBlueprint
from .perception import PerceptionLayer

log = logging.getLogger(__name__)


class BlueprintBuilder:
    """Build UIBlueprint by running perception layers in fallback order.

    Args:
        layers: ordered list of PerceptionLayer instances (fast -> slow)
    """

    def __init__(self, layers: list[PerceptionLayer] | None = None):
        self.layers = layers or []
        self._cache: dict[tuple[str, int, int], UIBlueprint] = {}

    def build(
        self,
        hwnd: int,
        window_class: str,
        rect: tuple[int, int, int, int],
        force: bool = False,
    ) -> UIBlueprint:
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        cache_key = (window_class, w, h)

        if not force and cache_key in self._cache:
            return self._cache[cache_key]

        all_elements = []
        all_zones = []
        used_layers = []

        for layer in self.layers:
            result = layer.analyze(hwnd, rect)
            all_elements.extend(result.elements)
            all_zones.extend(result.zones)
            if result.layer_name:
                used_layers.append(result.layer_name)

            if not result.needs_fallback:
                break

        bp = UIBlueprint(
            window_class=window_class,
            window_size=(w, h),
            elements=all_elements,
            zones=all_zones,
            perception_layers=used_layers,
            created_at=time.time(),
        )

        self._cache[cache_key] = bp
        log.info("BlueprintBuilder: built %d elements, %d zones via %s",
                 len(all_elements), len(all_zones), used_layers)
        return bp

    def invalidate(self, window_class: str = "") -> None:
        if window_class:
            self._cache = {k: v for k, v in self._cache.items() if k[0] != window_class}
        else:
            self._cache.clear()
