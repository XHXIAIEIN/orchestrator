"""Tests for src/desktop_use/ocr.py -- OCREngine interface with FakeEngine."""

import io

import pytest
from PIL import Image

from src.desktop_use.ocr import OCREngine
from src.desktop_use.types import OCRWord


# ---------------------------------------------------------------------------
# Fake engine for testing
# ---------------------------------------------------------------------------

class FakeOCREngine(OCREngine):
    """Returns pre-built words regardless of input."""

    def __init__(self, words: list[OCRWord]):
        self._words = words

    def extract_words(self, img, lang):
        return self._words


def _words(*specs) -> list[OCRWord]:
    """Build OCRWord list from tuples: (line_num, word_num, left, top, w, h, conf, text)."""
    return [OCRWord(text=t, left=l, top=tp, width=w, height=h,
                    conf=c, line_num=ln, word_num=wn)
            for ln, wn, l, tp, w, h, c, t in specs]


def _dummy_img():
    return Image.new("RGB", (800, 600), color=(255, 255, 255))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOCREngineInterface:
    def test_fake_engine_implements_interface(self):
        engine = FakeOCREngine([])
        assert isinstance(engine, OCREngine)

    def test_fake_engine_returns_words(self):
        words = _words((0, 0, 10, 10, 50, 20, 95, "hello"))
        engine = FakeOCREngine(words)
        result = engine.extract_words(_dummy_img(), "en")
        assert len(result) == 1
        assert result[0].text == "hello"

    def test_fake_engine_empty(self):
        engine = FakeOCREngine([])
        result = engine.extract_words(_dummy_img(), "en")
        assert result == []

    def test_multiple_words(self):
        words = _words(
            (0, 0, 10, 10, 50, 20, 95, "hello"),
            (0, 1, 70, 10, 60, 20, 90, "world"),
            (1, 0, 10, 40, 80, 20, 88, "second"),
        )
        engine = FakeOCREngine(words)
        result = engine.extract_words(_dummy_img(), "en")
        assert len(result) == 3
        assert [w.text for w in result] == ["hello", "world", "second"]

    def test_ocr_word_fields(self):
        w = OCRWord(text="test", left=10, top=20, width=30, height=15,
                    conf=95.0, line_num=0, word_num=0)
        assert w.text == "test"
        assert w.left == 10
        assert w.top == 20
        assert w.width == 30
        assert w.height == 15
        assert w.conf == 95.0
