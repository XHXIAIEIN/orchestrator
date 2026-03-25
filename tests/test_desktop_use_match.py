"""Tests for src/desktop_use/match.py -- FuzzyMatchStrategy with constructed OCRWord lists."""

import pytest

from src.desktop_use.match import MatchStrategy, FuzzyMatchStrategy
from src.desktop_use.types import OCRWord


def _words(*specs) -> list[OCRWord]:
    """Build OCRWord list from tuples: (line_num, word_num, left, top, w, h, conf, text)."""
    return [OCRWord(text=t, left=l, top=tp, width=w, height=h,
                    conf=c, line_num=ln, word_num=wn)
            for ln, wn, l, tp, w, h, c, t in specs]


# ---------------------------------------------------------------------------
# Exact match
# ---------------------------------------------------------------------------

class TestExactMatch:
    def test_exact_single_word(self):
        words = _words((1, 1, 100, 200, 60, 30, 95, "Settings"))
        strategy = FuzzyMatchStrategy()
        result = strategy.match("Settings", words)
        assert result is not None
        assert result.text == "Settings"

    def test_exact_cjk(self):
        words = _words((1, 1, 100, 200, 60, 30, 95, "我喜欢"))
        strategy = FuzzyMatchStrategy()
        result = strategy.match("我喜欢", words)
        assert result is not None
        assert result.text == "我喜欢"


# ---------------------------------------------------------------------------
# Merged adjacent
# ---------------------------------------------------------------------------

class TestMergedAdjacent:
    def test_merged_two_words(self):
        words = _words(
            (1, 1, 100, 200, 30, 30, 90, "我"),
            (1, 2, 140, 200, 60, 30, 85, "喜欢"),
        )
        strategy = FuzzyMatchStrategy()
        result = strategy.match("我喜欢", words)
        assert result is not None
        assert result.text == "我喜欢"

    def test_merged_three_words(self):
        words = _words(
            (0, 0, 10, 10, 30, 20, 95, "Hello"),
            (0, 1, 50, 10, 10, 20, 95, " "),
            (0, 2, 70, 10, 50, 20, 95, "World"),
        )
        strategy = FuzzyMatchStrategy()
        result = strategy.match("Hello World", words)
        assert result is not None
        assert result.text == "Hello World"


# ---------------------------------------------------------------------------
# Fuzzy match
# ---------------------------------------------------------------------------

class TestFuzzyMatch:
    def test_fuzzy_close_match(self):
        words = _words((1, 1, 200, 100, 80, 20, 85, "Settings"))
        strategy = FuzzyMatchStrategy()
        result = strategy.match("Setting", words)
        assert result is not None
        assert result.text == "Settings"

    def test_fuzzy_too_different(self):
        words = _words((1, 1, 50, 50, 40, 20, 88, "Settings"))
        strategy = FuzzyMatchStrategy()
        result = strategy.match("Completely Different", words)
        assert result is None


# ---------------------------------------------------------------------------
# Confidence filtering
# ---------------------------------------------------------------------------

class TestConfidenceFiltering:
    def test_low_confidence_rejected(self):
        words = _words((1, 1, 100, 200, 60, 30, 30, "我喜欢"))
        strategy = FuzzyMatchStrategy(min_confidence=70)
        result = strategy.match("我喜欢", words)
        assert result is None

    def test_custom_threshold(self):
        words = _words((1, 1, 100, 200, 60, 30, 50, "hello"))
        strategy = FuzzyMatchStrategy(min_confidence=40)
        result = strategy.match("hello", words)
        assert result is not None


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------

class TestNotFound:
    def test_no_match(self):
        words = _words((1, 1, 50, 50, 40, 20, 88, "设置"))
        strategy = FuzzyMatchStrategy()
        assert strategy.match("退出程序", words) is None

    def test_empty_words(self):
        strategy = FuzzyMatchStrategy()
        assert strategy.match("anything", []) is None


# ---------------------------------------------------------------------------
# Custom strategy
# ---------------------------------------------------------------------------

class TestCustomStrategy:
    def test_custom_strategy_interface(self):
        class AlwaysFirst(MatchStrategy):
            def match(self, target_text, words):
                return words[0] if words else None

        words = _words((1, 1, 10, 20, 30, 30, 50, "低置信度"))
        strategy = AlwaysFirst()
        result = strategy.match("任意文本", words)
        assert result is not None
        assert result.text == "低置信度"
