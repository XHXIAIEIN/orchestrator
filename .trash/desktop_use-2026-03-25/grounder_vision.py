"""Vision-based element grounding using UI-TARS-7B.
Phase 2 implementation — this is a stub for now."""
import logging
from src.desktop_use.grounder_ocr import LocateResult

log = logging.getLogger(__name__)


class VisionGrounder:
    """Stub — will be implemented in Phase 2 with UI-TARS-7B via vLLM."""

    def __init__(self, **kwargs):
        log.info("VisionGrounder: Phase 2 stub — not yet implemented")

    def locate(self, target_text: str, screenshot_png: bytes,
               monitor_id: int = 1) -> LocateResult | None:
        raise NotImplementedError(
            "VisionGrounder is a Phase 2 feature. "
            "Install UI-TARS-7B via vLLM and implement grounder_vision.py."
        )
