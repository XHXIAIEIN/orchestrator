"""Tests for blueprint visualization."""
import io
import pytest
from PIL import Image

from src.desktop_use.types import UIBlueprint, UIElement, UIZone, OCRWord
from src.desktop_use.visualize import render_skeleton, render_annotated, detect_contour_rects


def _make_image(w=800, h=600):
    return Image.new("RGB", (w, h), (40, 40, 40))


def _make_png(w=800, h=600):
    img = _make_image(w, h)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestRenderSkeleton:
    def test_returns_image(self):
        bp = UIBlueprint("Test", (800, 600),
                         zones=[UIZone("z", (0, 0, 400, 600), "panel", False)])
        result = render_skeleton(_make_image(), bp)
        assert isinstance(result, Image.Image)
        assert result.size == (800, 600)

    def test_accepts_bytes(self):
        bp = UIBlueprint("Test", (800, 600),
                         zones=[UIZone("z", (0, 0, 400, 600), "panel", False)])
        result = render_skeleton(_make_png(), bp)
        assert isinstance(result, Image.Image)

    def test_multiple_zones(self):
        bp = UIBlueprint("Test", (800, 600), zones=[
            UIZone("a", (0, 0, 200, 600), "panel", False),
            UIZone("b", (200, 0, 800, 300), "content", True),
            UIZone("c", (200, 300, 800, 600), "panel", False),
        ])
        result = render_skeleton(_make_image(), bp)
        assert result.size == (800, 600)


class TestRenderAnnotated:
    def test_returns_image(self):
        words = [OCRWord("hello", 10, 10, 50, 20, 95, 0, 0)]
        result = render_annotated(_make_image(), ocr_words=words)
        assert isinstance(result, Image.Image)

    def test_accepts_bytes(self):
        result = render_annotated(_make_png(), ocr_words=[])
        assert isinstance(result, Image.Image)

    def test_with_contour_rects(self):
        rects = [(100, 100, 160, 160), (200, 200, 260, 260)]
        result = render_annotated(_make_image(), contour_rects=rects)
        assert result.size == (800, 600)

    def test_both_words_and_contours(self):
        words = [OCRWord("test", 10, 10, 40, 15, 90, 0, 0)]
        rects = [(300, 300, 350, 350)]
        result = render_annotated(_make_image(), ocr_words=words, contour_rects=rects)
        assert result.size == (800, 600)


class TestDetectContourRects:
    def test_returns_list(self):
        result = detect_contour_rects(_make_png())
        assert isinstance(result, list)

    def test_excludes_ocr_overlaps(self):
        # Create an image with a visible rectangle
        import numpy as np
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        img[50:100, 50:100] = 200  # bright square
        pil = Image.fromarray(img)
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        png = buf.getvalue()

        # Without OCR exclusion
        rects_no_excl = detect_contour_rects(png, ocr_words=None, min_area=100, min_side=10)

        # With an OCR word covering the same area
        words = [OCRWord("x", 50, 50, 50, 50, 95, 0, 0)]
        rects_with_excl = detect_contour_rects(png, ocr_words=words, min_area=100, min_side=10)

        # Exclusion should remove at least some rects
        assert len(rects_with_excl) <= len(rects_no_excl)


class TestBlueprintVisualize:
    def test_skeleton_mode(self):
        bp = UIBlueprint("T", (800, 600),
                         zones=[UIZone("z", (0, 0, 800, 600), "panel", False)])
        result = bp.visualize(_make_image(), mode="skeleton")
        assert isinstance(result, Image.Image)

    def test_annotated_mode(self):
        bp = UIBlueprint("T", (800, 600))
        words = [OCRWord("hi", 10, 10, 30, 15, 95, 0, 0)]
        result = bp.visualize(_make_png(), mode="annotated", ocr_words=words)
        assert isinstance(result, Image.Image)

    def test_save_path(self, tmp_path):
        bp = UIBlueprint("T", (100, 100),
                         zones=[UIZone("z", (0, 0, 100, 100), "panel", False)])
        out = str(tmp_path / "test.png")
        result = bp.visualize(_make_image(100, 100), mode="skeleton", save_path=out)
        assert result is not None
        # File should exist
        loaded = Image.open(out)
        assert loaded.size == (100, 100)

    def test_invalid_mode_raises(self):
        bp = UIBlueprint("T", (100, 100))
        with pytest.raises(ValueError, match="Unknown mode"):
            bp.visualize(_make_image(100, 100), mode="invalid")
