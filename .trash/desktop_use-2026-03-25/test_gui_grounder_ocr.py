"""Tests for OCRGrounder — pluggable engine + strategy."""
import io

import pytest
from PIL import Image

from src.desktop_use.grounder_ocr import (
    LocateResult, OCREngine, OCRGrounder, OCRWord, FuzzyMatchStrategy,
)

# ---------------------------------------------------------------------------
# Fake engine that returns pre-built words
# ---------------------------------------------------------------------------

class FakeOCREngine(OCREngine):
    def __init__(self, words: list[OCRWord]):
        self._words = words

    def extract_words(self, img, lang):
        return self._words


def _words(*specs) -> list[OCRWord]:
    return [OCRWord(text=t, left=l, top=tp, width=w, height=h,
                    conf=c, line_num=ln, word_num=wn)
            for ln, wn, l, tp, w, h, c, t in specs]


def _dummy_png() -> bytes:
    img = Image.new("RGB", (800, 600), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def dummy_png():
    return _dummy_png()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_exact_match(dummy_png):
    engine = FakeOCREngine(_words((1, 1, 100, 200, 60, 30, 95, "我喜欢")))
    g = OCRGrounder(engine=engine)
    result = g.locate("我喜欢", dummy_png, monitor_id=1)

    assert result is not None
    assert result.x == 130
    assert result.y == 215
    assert result.confidence == 95.0
    assert result.method == "ocr"


def test_merged_adjacent(dummy_png):
    engine = FakeOCREngine(_words(
        (1, 1, 100, 200, 30, 30, 90, "我"),
        (1, 2, 140, 200, 60, 30, 85, "喜欢"),
    ))
    g = OCRGrounder(engine=engine)
    result = g.locate("我喜欢", dummy_png, monitor_id=2)

    assert result is not None
    assert result.x == 150
    assert result.y == 215
    assert result.monitor_id == 2


def test_not_found(dummy_png):
    engine = FakeOCREngine(_words((1, 1, 50, 50, 40, 20, 88, "设置")))
    g = OCRGrounder(engine=engine)
    assert g.locate("退出程序", dummy_png) is None


def test_low_confidence_rejected(dummy_png):
    engine = FakeOCREngine(_words((1, 1, 100, 200, 60, 30, 30, "我喜欢")))
    g = OCRGrounder(engine=engine)
    assert g.locate("我喜欢", dummy_png) is None


def test_fuzzy_match(dummy_png):
    engine = FakeOCREngine(_words((1, 1, 200, 100, 80, 20, 85, "Settings")))
    g = OCRGrounder(engine=engine)
    result = g.locate("Setting", dummy_png, monitor_id=3)

    assert result is not None
    assert result.x == 240
    assert result.y == 110
    assert result.monitor_id == 3


def test_extract_text(dummy_png):
    engine = FakeOCREngine(_words(
        (0, 0, 10, 10, 50, 20, 95, "你好"),
        (0, 1, 70, 10, 50, 20, 95, "世界"),
        (1, 0, 10, 40, 80, 20, 95, "第二行"),
    ))
    g = OCRGrounder(engine=engine)
    lines = g.extract_text(dummy_png)

    assert lines == ["你好世界", "第二行"]


def test_custom_strategy(dummy_png):
    """Verify that a custom strategy is actually used."""
    from src.desktop_use.grounder_ocr import MatchStrategy

    class AlwaysFirst(MatchStrategy):
        def match(self, target_text, words):
            return words[0] if words else None

    engine = FakeOCREngine(_words(
        (1, 1, 10, 20, 30, 30, 50, "低置信度"),  # conf=50 < default threshold
    ))
    # Default strategy would reject conf=50, custom strategy returns it anyway
    g = OCRGrounder(engine=engine, strategy=AlwaysFirst())
    result = g.locate("任意文本", dummy_png)
    assert result is not None
    assert result.x == 25  # 10 + 30//2
