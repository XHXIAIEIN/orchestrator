"""Text matching strategy interface + fuzzy default implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import OCRWord


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class MatchStrategy(ABC):
    """Pluggable text matching strategy for element location."""

    @abstractmethod
    def match(self, target_text: str, words: list[OCRWord]) -> OCRWord | None:
        """Find the best matching word/group for target_text. None if no match."""


# ---------------------------------------------------------------------------
# Default implementation: three-pass fuzzy matching
# ---------------------------------------------------------------------------

class FuzzyMatchStrategy(MatchStrategy):
    """Three-pass matching: exact -> merged adjacent -> fuzzy.

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

        # Pass 1 -- exact single-word match
        for w in confident:
            if w.text == target_text:
                return w

        # Pass 2 -- merged adjacent words
        merged = self._merge_adjacent(confident)
        for m in merged:
            if m.text == target_text:
                return m

        # Pass 3 -- fuzzy match
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
        """Group words by line_num -> sliding window 2..5 -> merged candidates."""
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
