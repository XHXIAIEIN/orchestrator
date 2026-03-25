import io
import pytest
from PIL import Image
from src.desktop_use.perception import (
    PerceptionLayer, PerceptionResult,
    Win32Layer, CVLayer, OCRLayer,
)
from src.desktop_use.types import UIElement, UIZone, OCRWord
from src.desktop_use.ocr import OCREngine


class TestPerceptionLayerInterface:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            PerceptionLayer()


class TestWin32Layer:
    def test_implements_interface(self):
        layer = Win32Layer()
        assert isinstance(layer, PerceptionLayer)

    def test_analyze_rich_app(self):
        layer = Win32Layer()
        children = [
            {"hwnd": 100, "class": "SysTreeView32", "title": "导航窗格",
             "rect": (0, 0, 200, 600), "visible": True},
            {"hwnd": 101, "class": "SHELLDLL_DefView", "title": "ShellView",
             "rect": (200, 0, 800, 600), "visible": True},
            {"hwnd": 102, "class": "ScrollBar", "title": "",
             "rect": (780, 0, 800, 600), "visible": True},
        ]
        result = layer._children_to_elements(children, parent_rect=(0, 0, 800, 600))
        assert len(result.elements) == 3
        assert result.elements[0].source == "win32"
        assert result.elements[0].name == "导航窗格"

    def test_analyze_empty_app(self):
        layer = Win32Layer()
        children = [
            {"hwnd": 200, "class": "MMUIRenderSubWindowHW", "title": "MMUIRenderSubWindowHW",
             "rect": (0, 0, 1000, 1500), "visible": True},
        ]
        result = layer._children_to_elements(children, parent_rect=(0, 0, 1000, 1500))
        assert len(result.elements) <= 1
        assert result.needs_fallback is True

    def test_classify_control_types(self):
        layer = Win32Layer()
        assert layer._classify_control("Edit") == "input"
        assert layer._classify_control("RichEdit20W") == "input"
        assert layer._classify_control("Button") == "button"
        assert layer._classify_control("ScrollBar") == "scrollbar"
        assert layer._classify_control("SysTreeView32") == "list"
        assert layer._classify_control("ToolbarWindow32") == "toolbar"
        assert layer._classify_control("Static") == "label"
        assert layer._classify_control("SomethingElse") == "panel"


class TestCVLayer:
    def _make_ui_image(self, w=800, h=600):
        import numpy as np
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:] = (40, 40, 40)
        img[:, :200] = (50, 50, 50)
        img[:, 199:201] = (80, 80, 80)
        img[:50, :] = (60, 60, 60)
        img[49:51, :] = (80, 80, 80)
        pil = Image.fromarray(img)
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()

    def test_implements_interface(self):
        layer = CVLayer()
        assert isinstance(layer, PerceptionLayer)

    def test_detects_dividers(self):
        layer = CVLayer()
        png = self._make_ui_image()
        result = layer.analyze_image(png, (800, 600))
        assert len(result.zones) >= 2

    def test_zones_have_positive_dimensions(self):
        layer = CVLayer()
        png = self._make_ui_image()
        result = layer.analyze_image(png, (800, 600))
        for z in result.zones:
            assert z.width > 0
            assert z.height > 0

    def test_merge_positions(self):
        assert CVLayer._merge_positions([10, 12, 15, 100, 102], threshold=10) == [10, 100]
        assert CVLayer._merge_positions([], threshold=10) == []
        assert CVLayer._merge_positions([50], threshold=10) == [50]


class FakeOCR(OCREngine):
    def __init__(self, words):
        self._words = words
    def extract_words(self, img, lang):
        return self._words


class TestOCRLayer:
    def test_implements_interface(self):
        layer = OCRLayer(engine=FakeOCR([]))
        assert isinstance(layer, PerceptionLayer)

    def test_words_become_elements(self):
        words = [
            OCRWord("搜索", 100, 20, 60, 25, 95, 0, 0),
            OCRWord("设置", 100, 600, 60, 25, 90, 1, 0),
        ]
        layer = OCRLayer(engine=FakeOCR(words))
        result = layer.analyze_words(words, (800, 600))
        assert len(result.elements) == 2
        assert result.elements[0].text == "搜索"
        assert result.elements[0].source == "ocr"

    def test_partial_ocr_with_offset(self):
        words = [OCRWord("消息1", 10, 10, 50, 20, 95, 0, 0)]
        layer = OCRLayer(engine=FakeOCR(words))
        result = layer.analyze_words(words, (560, 1400), offset=(460, 100))
        assert result.elements[0].rect[0] == 460 + 10
        assert result.elements[0].rect[1] == 100 + 10

    def test_confidence_conversion(self):
        words = [OCRWord("test", 0, 0, 50, 20, 80, 0, 0)]
        layer = OCRLayer(engine=FakeOCR(words))
        result = layer.analyze_words(words, (100, 100))
        assert result.elements[0].confidence == 0.8
