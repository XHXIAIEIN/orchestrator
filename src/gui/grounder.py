"""GroundingRouter — dispatches locate requests OCR-first, Vision fallback."""
from __future__ import annotations

import logging
from typing import Optional

from src.gui.grounder_ocr import OCRGrounder, LocateResult

log = logging.getLogger(__name__)


class GroundingRouter:
    """Routes element-location requests: OCR first, Vision as fallback.

    Args:
        screen_manager: Optional object with ``to_logical_coords(x, y, monitor_id)``
            for DPI / multi-monitor coordinate conversion.
        enable_vision: If True, instantiate VisionGrounder for fallback.
    """

    def __init__(self, screen_manager=None, enable_vision: bool = False):
        self.screen_manager = screen_manager
        self.ocr = OCRGrounder()

        self.vision = None
        if enable_vision:
            from src.gui.grounder_vision import VisionGrounder
            self.vision = VisionGrounder()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def locate(
        self,
        target_text: str,
        screenshot_png: bytes,
        monitor_id: int = 1,
    ) -> Optional[LocateResult]:
        # Pass 1 — OCR
        result = self.ocr.locate(target_text, screenshot_png, monitor_id)
        if result is not None:
            return self._apply_coord_transform(result, monitor_id)

        # Pass 2 — Vision fallback
        if self.vision is not None:
            try:
                result = self.vision.locate(target_text, screenshot_png, monitor_id)
                if result is not None:
                    return self._apply_coord_transform(result, monitor_id)
            except NotImplementedError:
                log.debug("VisionGrounder raised NotImplementedError — skipping")

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_coord_transform(
        self, result: LocateResult, monitor_id: int
    ) -> LocateResult:
        if self.screen_manager is None:
            return result
        lx, ly = self.screen_manager.to_logical_coords(result.x, result.y, monitor_id)
        return LocateResult(
            x=lx,
            y=ly,
            confidence=result.confidence,
            monitor_id=result.monitor_id,
            method=result.method,
        )
