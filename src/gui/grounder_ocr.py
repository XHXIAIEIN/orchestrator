"""OCR-based element grounding using Tesseract.

Shared LocateResult dataclass is defined here and re-exported for use
by other grounders (vision, etc.).
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional

import pytesseract
from PIL import Image
from rapidfuzz import fuzz


@dataclass
class LocateResult:
    """Unified result returned by all grounders."""

    x: int                  # logical pixels (DPI-adjusted)
    y: int
    confidence: Optional[float]   # 0-100 for OCR, None for vision
    monitor_id: int
    method: str             # "ocr" | "vision"


class OCRGrounder:
    """Locate UI elements by text using Tesseract OCR.

    Three-pass strategy:
    1. Exact single-word match (conf >= min_confidence)
    2. Merged adjacent words match (2..5 word sliding window per line)
    3. Fuzzy match via rapidfuzz.fuzz.ratio (>= fuzzy_threshold)
    """

    def __init__(self, min_confidence: float = 70, fuzzy_threshold: float = 80):
        self.min_confidence = min_confidence
        self.fuzzy_threshold = fuzzy_threshold

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
        words = self._extract_words(img)

        # Pass 1 — exact single-word match
        for w in words:
            if w["conf"] < self.min_confidence:
                continue
            if w["text"] == target_text:
                return self._word_to_result(w, monitor_id)

        # Pass 2 — merged adjacent words
        merged = self._merge_adjacent_words(words)
        for m in merged:
            if m["conf"] < self.min_confidence:
                continue
            if m["text"] == target_text:
                return self._word_to_result(m, monitor_id)

        # Pass 3 — fuzzy match across single words + merged groups
        candidates = [w for w in words if w["conf"] >= self.min_confidence]
        candidates += [m for m in merged if m["conf"] >= self.min_confidence]

        best_score = 0.0
        best_candidate = None
        for c in candidates:
            score = fuzz.ratio(c["text"], target_text)
            if score > best_score:
                best_score = score
                best_candidate = c

        if best_candidate is not None and best_score >= self.fuzzy_threshold:
            return self._word_to_result(best_candidate, monitor_id)

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_words(self, img: Image.Image) -> list[dict]:
        """Run Tesseract and parse TSV output into a list of word dicts."""
        tsv_output = pytesseract.image_to_data(img, lang="chi_sim+eng")
        lines = tsv_output.strip().splitlines()
        if not lines:
            return []

        header = lines[0].split("\t")
        results: list[dict] = []

        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) != len(header):
                continue
            row = dict(zip(header, parts))
            text = row.get("text", "").strip()
            if not text:
                continue
            try:
                conf = float(row["conf"])
            except (ValueError, KeyError):
                continue
            if conf < 0:
                continue
            try:
                results.append(
                    {
                        "text": text,
                        "left": int(row["left"]),
                        "top": int(row["top"]),
                        "width": int(row["width"]),
                        "height": int(row["height"]),
                        "conf": conf,
                        "line_num": int(row["line_num"]),
                        "word_num": int(row["word_num"]),
                    }
                )
            except (ValueError, KeyError):
                continue

        return results

    def _merge_adjacent_words(self, words: list[dict]) -> list[dict]:
        """Group words by line_num and produce 2..5-word merged candidates."""
        # Group by line_num
        by_line: dict[int, list[dict]] = {}
        for w in words:
            by_line.setdefault(w["line_num"], []).append(w)

        merged: list[dict] = []
        for line_words in by_line.values():
            # Sort by horizontal position
            sorted_words = sorted(line_words, key=lambda w: w["left"])
            n = len(sorted_words)
            # Sliding window: window sizes 2..5
            for size in range(2, 6):
                for start in range(n - size + 1):
                    group = sorted_words[start : start + size]
                    text = "".join(w["text"] for w in group)
                    left = min(w["left"] for w in group)
                    top = min(w["top"] for w in group)
                    right = max(w["left"] + w["width"] for w in group)
                    bottom = max(w["top"] + w["height"] for w in group)
                    avg_conf = sum(w["conf"] for w in group) / len(group)
                    merged.append(
                        {
                            "text": text,
                            "left": left,
                            "top": top,
                            "width": right - left,
                            "height": bottom - top,
                            "conf": avg_conf,
                            "line_num": group[0]["line_num"],
                            "word_num": group[0]["word_num"],
                        }
                    )

        return merged

    @staticmethod
    def _word_to_result(word: dict, monitor_id: int) -> LocateResult:
        cx = word["left"] + word["width"] // 2
        cy = word["top"] + word["height"] // 2
        return LocateResult(
            x=cx,
            y=cy,
            confidence=float(word["conf"]),
            monitor_id=monitor_id,
            method="ocr",
        )
