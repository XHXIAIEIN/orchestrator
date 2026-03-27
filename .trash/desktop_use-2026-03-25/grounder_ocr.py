"""OCR-based element grounding with pluggable OCR engine and match strategy.

Components:
- OCREngine: pluggable backend (default: WinOCREngine)
- MatchStrategy: pluggable text matching (default: FuzzyMatchStrategy)
- OCRGrounder: wires engine + strategy together

Shared LocateResult / OCRWord dataclasses re-exported for other grounders.
"""
from __future__ import annotations

import asyncio
import io
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from PIL import Image

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class LocateResult:
    """Unified result returned by all grounders."""
    x: int
    y: int
    confidence: Optional[float]
    monitor_id: int
    method: str             # "ocr" | "vision"


@dataclass
class OCRWord:
    """A single word/line detected by OCR with bounding box."""
    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float             # 0-100
    line_num: int
    word_num: int


# ===========================================================================
# OCR Engine interface + built-in implementation
# ===========================================================================

class OCREngine(ABC):
    """Pluggable OCR backend. Implement extract_words to add a new engine."""

    @abstractmethod
    def extract_words(self, img: Image.Image, lang: str) -> list[OCRWord]:
        """Extract words with bounding boxes from an image."""


_WINOCR_AVAILABLE = False
try:
    import winocr as _winocr
    _WINOCR_AVAILABLE = True
except ImportError:
    _winocr = None  # type: ignore[assignment]


class WinOCREngine(OCREngine):
    """Windows-native OCR via WinRT (winocr). ~0.1s, good CJK support."""

    def extract_words(self, img: Image.Image, lang: str) -> list[OCRWord]:
        if not _WINOCR_AVAILABLE:
            log.error("WinOCREngine: winocr not installed (pip install winocr)")
            return []

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self._recognize, img, lang)
                return future.result(timeout=10)
        else:
            return self._recognize(img, lang)

    def _recognize(self, img: Image.Image, lang: str) -> list[OCRWord]:
        async def _run():
            return await _winocr.recognize_pil(img, lang=lang)

        result = asyncio.run(_run())
        words: list[OCRWord] = []

        for line_idx, line in enumerate(result.lines):
            for word_idx, word in enumerate(line.words):
                text = word.text.strip()
                if not text:
                    continue
                br = word.bounding_rect
                words.append(OCRWord(
                    text=text,
                    left=int(br.x),
                    top=int(br.y),
                    width=int(br.width),
                    height=int(br.height),
                    conf=95.0,
                    line_num=line_idx,
                    word_num=word_idx,
                ))

        return words


# ===========================================================================
# Match Strategy interface + built-in implementation
# ===========================================================================

class MatchStrategy(ABC):
    """Pluggable text matching strategy for element location."""

    @abstractmethod
    def match(self, target_text: str, words: list[OCRWord]) -> OCRWord | None:
        """Find the best matching word/group for target_text. None if no match."""


class FuzzyMatchStrategy(MatchStrategy):
    """Three-pass matching: exact → merged adjacent → fuzzy.

    Args:
        min_confidence: minimum OCR confidence to consider a word (0-100)
        fuzzy_threshold: minimum rapidfuzz ratio to accept a fuzzy match (0-100)
    """

    def __init__(self, min_confidence: float = 70, fuzzy_threshold: float = 80):
        self.min_confidence = min_confidence
        self.fuzzy_threshold = fuzzy_threshold

    def match(self, target_text: str, words: list[OCRWord]) -> OCRWord | None:
        from rapidfuzz import fuzz

        confident = [w for w in words if w.conf >= self.min_confidence]

        # Pass 1 — exact single-word match
        for w in confident:
            if w.text == target_text:
                return w

        # Pass 2 — merged adjacent words
        merged = self._merge_adjacent(confident)
        for m in merged:
            if m.text == target_text:
                return m

        # Pass 3 — fuzzy match
        candidates = confident + merged
        best_score = 0.0
        best_candidate = None
        for c in candidates:
            score = fuzz.ratio(c.text, target_text)
            if score > best_score:
                best_score = score
                best_candidate = c

        if best_candidate is not None and best_score >= self.fuzzy_threshold:
            return best_candidate

        return None

    @staticmethod
    def _merge_adjacent(words: list[OCRWord]) -> list[OCRWord]:
        """Group words by line_num → sliding window 2..5 → merged candidates."""
        by_line: dict[int, list[OCRWord]] = {}
        for w in words:
            by_line.setdefault(w.line_num, []).append(w)

        merged: list[OCRWord] = []
        for line_words in by_line.values():
            sorted_words = sorted(line_words, key=lambda w: w.left)
            n = len(sorted_words)
            for size in range(2, 6):
                for start in range(n - size + 1):
                    group = sorted_words[start: start + size]
                    text = "".join(w.text for w in group)
                    left = min(w.left for w in group)
                    top = min(w.top for w in group)
                    right = max(w.left + w.width for w in group)
                    bottom = max(w.top + w.height for w in group)
                    avg_conf = sum(w.conf for w in group) / len(group)
                    merged.append(OCRWord(
                        text=text, left=left, top=top,
                        width=right - left, height=bottom - top,
                        conf=avg_conf,
                        line_num=group[0].line_num,
                        word_num=group[0].word_num,
                    ))
        return merged


# ===========================================================================
# OCRGrounder — wires engine + strategy
# ===========================================================================

class OCRGrounder:
    """Locate UI elements by text. Pluggable engine and strategy.

    Args:
        engine: OCR backend (default: WinOCREngine)
        strategy: match algorithm (default: FuzzyMatchStrategy)
        lang: OCR language code
    """

    def __init__(self, engine: OCREngine | None = None,
                 strategy: MatchStrategy | None = None,
                 lang: str = "zh-Hans-CN",
                 # legacy kwargs for backward compat with tests
                 min_confidence: float = 70, fuzzy_threshold: float = 80):
        self.engine = engine or WinOCREngine()
        self.strategy = strategy or FuzzyMatchStrategy(min_confidence, fuzzy_threshold)
        self.lang = lang
        log.info("OCRGrounder: engine=%s strategy=%s",
                 type(self.engine).__name__, type(self.strategy).__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def locate(
        self,
        target_text: str,
        screenshot_png: bytes,
        monitor_id: int = 1,
    ) -> Optional[LocateResult]:
        img = Image.open(io.BytesIO(screenshot_png))
        words = self.engine.extract_words(img, self.lang)
        hit = self.strategy.match(target_text, words)
        if hit is None:
            return None
        return self._word_to_result(hit, monitor_id)

    def extract_text(self, screenshot_png: bytes) -> list[str]:
        """Extract all text lines from a screenshot."""
        img = Image.open(io.BytesIO(screenshot_png))
        words = self.engine.extract_words(img, self.lang)
        if not words:
            return []

        by_line: dict[int, list[OCRWord]] = {}
        for w in words:
            by_line.setdefault(w.line_num, []).append(w)

        lines = []
        for line_num in sorted(by_line.keys()):
            line_words = sorted(by_line[line_num], key=lambda w: w.left)
            lines.append("".join(w.text for w in line_words))
        return lines

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _word_to_result(word: OCRWord, monitor_id: int) -> LocateResult:
        cx = word.left + word.width // 2
        cy = word.top + word.height // 2
        return LocateResult(
            x=cx, y=cy,
            confidence=word.conf,
            monitor_id=monitor_id,
            method="ocr",
        )
