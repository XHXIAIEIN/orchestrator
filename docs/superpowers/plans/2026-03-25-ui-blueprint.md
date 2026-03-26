# UI Blueprint 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 desktop_use 模块增加 UI 蓝图系统 — 多层感知自适应分析窗口结构，生成可缓存的 UIBlueprint，后续操作查表走 RPA 而不是每步都 OCR + LLM。

**Architecture:** 四层感知逐级降级（Win32 API → CV 边缘检测 → WinRT OCR → OmniParser），每层是可插拔接口。BlueprintBuilder 编排感知层生成蓝图，DesktopEngine 集成蓝图驱动的快速操作。

**Tech Stack:** ctypes (Win32 API)、uiautomation (UI Automation)、opencv-python-headless (CV)、winocr (WinRT OCR)、PIL

**Spec:** `docs/superpowers/specs/2026-03-25-ui-blueprint-design.md`

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `src/desktop_use/types.py` | 修改 | 加入 UIElement, UIZone, UIBlueprint 数据模型 |
| `src/desktop_use/perception.py` | 新建 | PerceptionLayer(ABC) + Win32Layer, CVLayer, OCRLayer, OmniParserLayer |
| `src/desktop_use/blueprint.py` | 新建 | BlueprintBuilder — 编排感知层、构建蓝图、缓存管理 |
| `src/desktop_use/engine.py` | 修改 | DesktopEngine 加入 analyze() 和 read_zone() |
| `src/desktop_use/__init__.py` | 修改 | 导出新的公共 API |
| `tests/test_desktop_use_perception.py` | 新建 | 感知层测试 |
| `tests/test_desktop_use_blueprint.py` | 新建 | 蓝图构建器测试 |
| `requirements-gui.txt` | 修改 | 加入 opencv-python-headless |

---

### Task 1: 数据模型 — UIElement, UIZone, UIBlueprint

**Files:**
- Modify: `src/desktop_use/types.py`
- Test: `tests/test_desktop_use_blueprint.py`

- [ ] **Step 1: 写失败测试 — UIElement 数据模型**

```python
# tests/test_desktop_use_blueprint.py
from src.desktop_use.types import UIElement, UIZone, UIBlueprint

class TestUIElement:
    def test_fields(self):
        e = UIElement(name="search", rect=(10, 20, 100, 50),
                      element_type="input", action="click+type",
                      text="搜索", source="win32", confidence=1.0)
        assert e.name == "search"
        assert e.rect == (10, 20, 100, 50)
        assert e.source == "win32"

    def test_center(self):
        e = UIElement(name="btn", rect=(100, 200, 160, 230),
                      element_type="button", action="click",
                      text="OK", source="ocr", confidence=0.95)
        cx = (100 + 160) // 2
        cy = (200 + 230) // 2
        assert e.center == (cx, cy)

    def test_width_height(self):
        e = UIElement(name="x", rect=(10, 20, 110, 70),
                      element_type="label", action="display",
                      text="", source="cv", confidence=0.8)
        assert e.width == 100
        assert e.height == 50


class TestUIZone:
    def test_fields(self):
        z = UIZone(name="chat", rect=(460, 100, 1020, 1500),
                   zone_type="messages", dynamic=True)
        assert z.dynamic is True
        assert z.width == 560


class TestUIBlueprint:
    def test_find_element(self):
        e1 = UIElement("search", (10, 20, 100, 50), "input", "click+type", "搜索", "ocr", 0.9)
        e2 = UIElement("send", (800, 900, 850, 930), "button", "click", "发送", "ocr", 0.95)
        bp = UIBlueprint(window_class="TestClass", window_size=(1024, 768),
                         elements=[e1, e2], zones=[],
                         perception_layers=["ocr"], created_at=0.0)
        assert bp.find("搜索") == e1
        assert bp.find("发送") == e2
        assert bp.find("不存在") is None

    def test_find_zone(self):
        z = UIZone("chat", (460, 100, 1020, 1500), "messages", True)
        bp = UIBlueprint("Test", (1024, 768), [], [z], ["cv"], 0.0)
        assert bp.zone("chat") == z
        assert bp.zone("nope") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_desktop_use_blueprint.py -x -v`
Expected: ImportError — UIElement 未定义

- [ ] **Step 3: 实现数据模型**

在 `src/desktop_use/types.py` 末尾添加：

```python
@dataclass
class UIElement:
    """A UI element in a blueprint — button, input, label, icon, etc."""
    name: str
    rect: tuple[int, int, int, int]  # (left, top, right, bottom)
    element_type: str                # "button" | "input" | "icon" | "label" | "text"
    action: str                      # "click" | "click+type" | "display"
    text: str                        # visible text (may be empty)
    source: str                      # "win32" | "uia" | "cv" | "ocr" | "omniparser"
    confidence: float                # 0.0 - 1.0

    @property
    def center(self) -> tuple[int, int]:
        return (self.rect[0] + self.rect[2]) // 2, (self.rect[1] + self.rect[3]) // 2

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


@dataclass
class UIZone:
    """A rectangular region in the UI — may be static (skeleton) or dynamic."""
    name: str
    rect: tuple[int, int, int, int]
    zone_type: str                   # "list" | "messages" | "input" | "toolbar"
    dynamic: bool

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


@dataclass
class UIBlueprint:
    """Cached structural analysis of a window."""
    window_class: str
    window_size: tuple[int, int]
    elements: list[UIElement] = field(default_factory=list)
    zones: list[UIZone] = field(default_factory=list)
    perception_layers: list[str] = field(default_factory=list)
    created_at: float = 0.0

    def find(self, text: str) -> UIElement | None:
        """Find skeleton element by text (exact or substring)."""
        for e in self.elements:
            if e.text == text:
                return e
        for e in self.elements:
            if text in e.text or e.text in text:
                return e
        return None

    def zone(self, name: str) -> UIZone | None:
        """Find zone by name."""
        for z in self.zones:
            if z.name == name:
                return z
        return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_desktop_use_blueprint.py -x -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/desktop_use/types.py tests/test_desktop_use_blueprint.py
git commit -m "feat(desktop_use): add UIElement, UIZone, UIBlueprint data models"
```

---

### Task 2: 感知层接口 + Win32Layer

**Files:**
- Create: `src/desktop_use/perception.py`
- Create: `tests/test_desktop_use_perception.py`

- [ ] **Step 1: 写失败测试 — PerceptionLayer ABC + Win32Layer**

```python
# tests/test_desktop_use_perception.py
import pytest
from unittest.mock import patch, MagicMock
from src.desktop_use.perception import PerceptionLayer, Win32Layer
from src.desktop_use.types import UIElement, UIZone, WindowInfo


class TestPerceptionLayerInterface:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            PerceptionLayer()


class TestWin32Layer:
    def test_implements_interface(self):
        layer = Win32Layer()
        assert isinstance(layer, PerceptionLayer)

    def test_analyze_rich_app(self):
        """Simulate an app with many child windows (like Explorer)."""
        layer = Win32Layer()
        # Mock: 3 child windows with rects and class names
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
        """Simulate a self-drawing app like WeChat (few children)."""
        layer = Win32Layer()
        children = [
            {"hwnd": 200, "class": "MMUIRenderSubWindowHW", "title": "MMUIRenderSubWindowHW",
             "rect": (0, 0, 1000, 1500), "visible": True},
        ]
        result = layer._children_to_elements(children, parent_rect=(0, 0, 1000, 1500))
        # Only 1 element, should signal that CV/OCR fallback is needed
        assert len(result.elements) <= 1
        assert result.needs_fallback is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_desktop_use_perception.py -x -v`
Expected: ImportError

- [ ] **Step 3: 实现 PerceptionLayer ABC + Win32Layer**

```python
# src/desktop_use/perception.py
"""Pluggable perception layers for UI blueprint analysis.

Each layer extracts structural information from a window using a different
technique. Layers are tried in order by BlueprintBuilder — fast/free first,
expensive last.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .types import UIElement, UIZone

log = logging.getLogger(__name__)

user32 = ctypes.windll.user32


@dataclass
class PerceptionResult:
    """Output of a single perception layer."""
    elements: list[UIElement] = field(default_factory=list)
    zones: list[UIZone] = field(default_factory=list)
    needs_fallback: bool = False  # True = this layer didn't get enough info
    layer_name: str = ""


class PerceptionLayer(ABC):
    """Interface for a perception layer."""

    @abstractmethod
    def analyze(self, hwnd: int, rect: tuple[int, int, int, int]) -> PerceptionResult:
        """Analyze a window and return detected elements/zones."""


class Win32Layer(PerceptionLayer):
    """Layer 0: Win32 EnumChildWindows + window properties.

    Free (0ms), works on standard Win32/WPF/WinForms apps.
    Returns needs_fallback=True for self-drawing apps (Qt, Electron, etc.)
    where the child window count is too low to be useful.
    """

    MIN_CHILDREN_FOR_COMPLETE = 5  # below this, we need CV/OCR fallback

    def analyze(self, hwnd: int, rect: tuple[int, int, int, int]) -> PerceptionResult:
        children = self._enum_children(hwnd)
        visible = [c for c in children if c["visible"]]
        return self._children_to_elements(visible, parent_rect=rect)

    def _children_to_elements(
        self, children: list[dict], parent_rect: tuple[int, int, int, int]
    ) -> PerceptionResult:
        elements = []
        px, py = parent_rect[0], parent_rect[1]

        for c in children:
            r = c["rect"]
            # Convert to parent-relative coords
            local_rect = (r[0] - px, r[1] - py, r[2] - px, r[3] - py)
            w, h = local_rect[2] - local_rect[0], local_rect[3] - local_rect[1]
            if w <= 0 or h <= 0:
                continue

            name = c.get("title", "") or c.get("class", "")
            el_type = self._classify_control(c["class"])
            action = "click+type" if el_type == "input" else "click" if el_type != "label" else "display"

            elements.append(UIElement(
                name=name,
                rect=local_rect,
                element_type=el_type,
                action=action,
                text=c.get("title", ""),
                source="win32",
                confidence=1.0,
            ))

        needs_fallback = len(elements) < self.MIN_CHILDREN_FOR_COMPLETE
        return PerceptionResult(
            elements=elements,
            needs_fallback=needs_fallback,
            layer_name="win32",
        )

    @staticmethod
    def _classify_control(class_name: str) -> str:
        cls = class_name.lower()
        if any(k in cls for k in ("edit", "richedit", "textbox", "scintilla")):
            return "input"
        if any(k in cls for k in ("button", "btn")):
            return "button"
        if any(k in cls for k in ("scrollbar",)):
            return "scrollbar"
        if any(k in cls for k in ("listview", "syslistview", "treeview", "systreeview")):
            return "list"
        if any(k in cls for k in ("toolbar", "toolbarwindow")):
            return "toolbar"
        if any(k in cls for k in ("static", "label")):
            return "label"
        return "panel"

    @staticmethod
    def _enum_children(hwnd: int) -> list[dict]:
        results = []

        def callback(child_hwnd, _):
            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(child_hwnd, cls_buf, 256)
            title_buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(child_hwnd, title_buf, 512)
            r = ctypes.wintypes.RECT()
            user32.GetWindowRect(child_hwnd, ctypes.byref(r))
            vis = bool(user32.IsWindowVisible(child_hwnd))
            results.append({
                "hwnd": child_hwnd,
                "class": cls_buf.value,
                "title": title_buf.value,
                "rect": (r.left, r.top, r.right, r.bottom),
                "visible": vis,
            })
            return True

        PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong, ctypes.c_ulong)
        user32.EnumChildWindows(hwnd, PROC(callback), 0)
        return results
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_desktop_use_perception.py -x -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/desktop_use/perception.py tests/test_desktop_use_perception.py
git commit -m "feat(desktop_use): add PerceptionLayer ABC + Win32Layer"
```

---

### Task 3: CVLayer — 边缘检测感知层

**Files:**
- Modify: `src/desktop_use/perception.py`
- Modify: `tests/test_desktop_use_perception.py`
- Modify: `requirements-gui.txt`

- [ ] **Step 1: 写失败测试 — CVLayer**

```python
# 追加到 tests/test_desktop_use_perception.py
from src.desktop_use.perception import CVLayer
from PIL import Image
import io

class TestCVLayer:
    def _make_ui_image(self, w=800, h=600):
        """Create a synthetic UI image with clear panel boundaries."""
        import numpy as np
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:] = (40, 40, 40)  # dark background
        # Left sidebar
        img[:, :200] = (50, 50, 50)
        # Divider line
        img[:, 199:201] = (80, 80, 80)
        # Top bar
        img[:50, :] = (60, 60, 60)
        img[49:51, :] = (80, 80, 80)
        # Convert to PNG bytes
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
        # Should detect at least the vertical divider at x~200 and horizontal at y~50
        assert len(result.zones) >= 2

    def test_zones_are_non_overlapping(self):
        layer = CVLayer()
        png = self._make_ui_image()
        result = layer.analyze_image(png, (800, 600))
        # Basic sanity: zones should have positive dimensions
        for z in result.zones:
            assert z.width > 0
            assert z.height > 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_desktop_use_perception.py::TestCVLayer -x -v`
Expected: ImportError — CVLayer 未定义

- [ ] **Step 3: 实现 CVLayer**

追加到 `src/desktop_use/perception.py`：

```python
class CVLayer(PerceptionLayer):
    """Layer 0.5: CV edge detection for self-drawing apps.

    Uses Canny + HoughLinesP to find structural dividers (long horizontal/
    vertical lines), then builds zones from the resulting grid.

    ~12ms, no GPU, no model weights.
    """

    def __init__(self, min_line_ratio: float = 0.15):
        self.min_line_ratio = min_line_ratio  # minimum line length as fraction of dimension

    def analyze(self, hwnd: int, rect: tuple[int, int, int, int]) -> PerceptionResult:
        """Not directly usable — use analyze_image() with screenshot bytes."""
        return PerceptionResult(layer_name="cv", needs_fallback=True)

    def analyze_image(
        self, png_bytes: bytes, window_size: tuple[int, int]
    ) -> PerceptionResult:
        try:
            import cv2
            import numpy as np
        except ImportError:
            log.warning("CVLayer: opencv not installed")
            return PerceptionResult(layer_name="cv", needs_fallback=True)

        nparr = np.frombuffer(png_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return PerceptionResult(layer_name="cv", needs_fallback=True)

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 30, 120)

        # Detect line segments
        raw_lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180,
            threshold=60, minLineLength=80, maxLineGap=10,
        )

        h_lines, v_lines = [], []
        if raw_lines is not None:
            for line in raw_lines:
                x1, y1, x2, y2 = line[0]
                dx, dy = abs(x2 - x1), abs(y2 - y1)
                length = (dx * dx + dy * dy) ** 0.5
                if dy < 5 and length > w * self.min_line_ratio:
                    h_lines.append(y1)
                elif dx < 5 and length > h * self.min_line_ratio:
                    v_lines.append(x1)

        # Merge nearby positions (within 10px)
        x_cuts = self._merge_positions(v_lines, threshold=10)
        y_cuts = self._merge_positions(h_lines, threshold=10)

        # Build zones from grid
        x_edges = sorted(set([0] + x_cuts + [w]))
        y_edges = sorted(set([0] + y_cuts + [h]))

        zones = []
        for yi in range(len(y_edges) - 1):
            for xi in range(len(x_edges) - 1):
                zx1, zy1 = x_edges[xi], y_edges[yi]
                zx2, zy2 = x_edges[xi + 1], y_edges[yi + 1]
                if zx2 - zx1 < 30 or zy2 - zy1 < 30:
                    continue

                # Determine if dynamic by color variance
                cell = img[zy1:zy2, zx1:zx2]
                variance = float(np.var(cell))
                is_dynamic = variance > 2000

                zones.append(UIZone(
                    name=f"zone_{xi}_{yi}",
                    rect=(zx1, zy1, zx2, zy2),
                    zone_type="content" if is_dynamic else "panel",
                    dynamic=is_dynamic,
                ))

        return PerceptionResult(
            zones=zones,
            needs_fallback=len(zones) < 2,
            layer_name="cv",
        )

    @staticmethod
    def _merge_positions(positions: list[int], threshold: int = 10) -> list[int]:
        if not positions:
            return []
        positions = sorted(positions)
        merged = [positions[0]]
        for p in positions[1:]:
            if p - merged[-1] > threshold:
                merged.append(p)
        return merged
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_desktop_use_perception.py::TestCVLayer -x -v`
Expected: PASS

- [ ] **Step 5: 加 opencv 到 requirements**

在 `requirements-gui.txt` 添加：
```
opencv-python-headless>=4.8.0  # CV edge detection for blueprint analysis
```

- [ ] **Step 6: 提交**

```bash
git add src/desktop_use/perception.py tests/test_desktop_use_perception.py requirements-gui.txt
git commit -m "feat(desktop_use): add CVLayer — edge detection perception"
```

---

### Task 4: OCRLayer — 局部 OCR 感知层

**Files:**
- Modify: `src/desktop_use/perception.py`
- Modify: `tests/test_desktop_use_perception.py`

- [ ] **Step 1: 写失败测试 — OCRLayer**

```python
# 追加到 tests/test_desktop_use_perception.py
from src.desktop_use.perception import OCRLayer
from src.desktop_use.ocr import OCREngine
from src.desktop_use.types import OCRWord

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

    def test_partial_ocr_on_zone(self):
        """OCRLayer should support analyzing a cropped zone."""
        words = [OCRWord("消息1", 10, 10, 50, 20, 95, 0, 0)]
        layer = OCRLayer(engine=FakeOCR(words))
        zone_rect = (460, 100, 1020, 1500)
        result = layer.analyze_words(words, (560, 1400), offset=zone_rect[:2])
        # Coords should be offset to global
        assert result.elements[0].rect[0] == 460 + 10
        assert result.elements[0].rect[1] == 100 + 10
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_desktop_use_perception.py::TestOCRLayer -x -v`
Expected: ImportError

- [ ] **Step 3: 实现 OCRLayer**

追加到 `src/desktop_use/perception.py`：

```python
class OCRLayer(PerceptionLayer):
    """Layer 1: WinRT OCR text extraction.

    Converts OCR words to UIElements with bounding boxes.
    Supports partial (zone-cropped) analysis with coordinate offset.

    ~100ms full window, ~30ms per zone crop.
    """

    def __init__(self, engine: object = None, lang: str = "zh-Hans-CN"):
        self.engine = engine  # OCREngine instance
        self.lang = lang

    def analyze(self, hwnd: int, rect: tuple[int, int, int, int]) -> PerceptionResult:
        return PerceptionResult(layer_name="ocr", needs_fallback=True)

    def analyze_words(
        self,
        words: list,  # list[OCRWord]
        image_size: tuple[int, int],
        offset: tuple[int, int] = (0, 0),
    ) -> PerceptionResult:
        elements = []
        ox, oy = offset

        for w in words:
            elements.append(UIElement(
                name=w.text,
                rect=(ox + w.left, oy + w.top,
                      ox + w.left + w.width, oy + w.top + w.height),
                element_type="text",
                action="display",
                text=w.text,
                source="ocr",
                confidence=w.conf / 100.0,
            ))

        return PerceptionResult(
            elements=elements,
            needs_fallback=False,
            layer_name="ocr",
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_desktop_use_perception.py::TestOCRLayer -x -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/desktop_use/perception.py tests/test_desktop_use_perception.py
git commit -m "feat(desktop_use): add OCRLayer — text extraction perception"
```

---

### Task 5: BlueprintBuilder — 编排感知层 + 缓存

**Files:**
- Create: `src/desktop_use/blueprint.py`
- Modify: `tests/test_desktop_use_blueprint.py`

- [ ] **Step 1: 写失败测试 — BlueprintBuilder**

```python
# 追加到 tests/test_desktop_use_blueprint.py
from src.desktop_use.blueprint import BlueprintBuilder
from src.desktop_use.perception import PerceptionLayer, PerceptionResult
from src.desktop_use.types import UIElement, UIZone, UIBlueprint


class FakeLayer(PerceptionLayer):
    def __init__(self, result):
        self._result = result
    def analyze(self, hwnd, rect):
        return self._result


class TestBlueprintBuilder:
    def test_builds_from_single_layer(self):
        layer = FakeLayer(PerceptionResult(
            elements=[UIElement("btn", (10, 20, 60, 40), "button", "click", "OK", "test", 1.0)],
            zones=[UIZone("main", (0, 0, 800, 600), "panel", False)],
            needs_fallback=False,
            layer_name="test",
        ))
        builder = BlueprintBuilder(layers=[layer])
        bp = builder.build(hwnd=0, window_class="Test", rect=(0, 0, 800, 600))
        assert isinstance(bp, UIBlueprint)
        assert len(bp.elements) == 1
        assert len(bp.zones) == 1

    def test_fallback_chain(self):
        """Layer 1 returns needs_fallback=True → Layer 2 runs."""
        layer1 = FakeLayer(PerceptionResult(
            elements=[], needs_fallback=True, layer_name="layer1",
        ))
        layer2 = FakeLayer(PerceptionResult(
            elements=[UIElement("x", (0,0,10,10), "text", "display", "X", "l2", 1.0)],
            zones=[UIZone("z", (0,0,100,100), "panel", False)],
            needs_fallback=False, layer_name="layer2",
        ))
        builder = BlueprintBuilder(layers=[layer1, layer2])
        bp = builder.build(hwnd=0, window_class="Test", rect=(0, 0, 100, 100))
        assert len(bp.elements) == 1
        assert "layer1" in bp.perception_layers
        assert "layer2" in bp.perception_layers

    def test_cache_hit(self):
        call_count = [0]
        class CountingLayer(PerceptionLayer):
            def analyze(self, hwnd, rect):
                call_count[0] += 1
                return PerceptionResult(
                    elements=[UIElement("a", (0,0,1,1), "label", "display", "A", "t", 1.0)],
                    needs_fallback=False, layer_name="counting",
                )
        builder = BlueprintBuilder(layers=[CountingLayer()])
        bp1 = builder.build(hwnd=0, window_class="C", rect=(0, 0, 800, 600))
        bp2 = builder.build(hwnd=0, window_class="C", rect=(0, 0, 800, 600))
        assert call_count[0] == 1  # second call hits cache
        assert bp1 is bp2

    def test_cache_invalidate_on_resize(self):
        call_count = [0]
        class CountingLayer(PerceptionLayer):
            def analyze(self, hwnd, rect):
                call_count[0] += 1
                return PerceptionResult(
                    elements=[], needs_fallback=False, layer_name="counting",
                )
        builder = BlueprintBuilder(layers=[CountingLayer()])
        builder.build(hwnd=0, window_class="C", rect=(0, 0, 800, 600))
        builder.build(hwnd=0, window_class="C", rect=(0, 0, 1024, 768))  # resized
        assert call_count[0] == 2  # cache miss on resize
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_desktop_use_blueprint.py::TestBlueprintBuilder -x -v`
Expected: ImportError

- [ ] **Step 3: 实现 BlueprintBuilder**

```python
# src/desktop_use/blueprint.py
"""BlueprintBuilder — orchestrates perception layers to build UIBlueprint.

Runs layers in order. If a layer sets needs_fallback=True, the next layer
runs. Elements and zones accumulate across layers.
"""
from __future__ import annotations

import logging
import time

from .types import UIBlueprint
from .perception import PerceptionLayer

log = logging.getLogger(__name__)


class BlueprintBuilder:
    """Build UIBlueprint by running perception layers in fallback order.

    Args:
        layers: ordered list of PerceptionLayer instances (fast → slow)
    """

    def __init__(self, layers: list[PerceptionLayer] | None = None):
        self.layers = layers or []
        self._cache: dict[tuple[str, int, int], UIBlueprint] = {}

    def build(
        self,
        hwnd: int,
        window_class: str,
        rect: tuple[int, int, int, int],
        force: bool = False,
    ) -> UIBlueprint:
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        cache_key = (window_class, w, h)

        if not force and cache_key in self._cache:
            return self._cache[cache_key]

        all_elements = []
        all_zones = []
        used_layers = []

        for layer in self.layers:
            result = layer.analyze(hwnd, rect)
            all_elements.extend(result.elements)
            all_zones.extend(result.zones)
            if result.layer_name:
                used_layers.append(result.layer_name)

            if not result.needs_fallback:
                break

        bp = UIBlueprint(
            window_class=window_class,
            window_size=(w, h),
            elements=all_elements,
            zones=all_zones,
            perception_layers=used_layers,
            created_at=time.time(),
        )

        self._cache[cache_key] = bp
        log.info("BlueprintBuilder: built %d elements, %d zones via %s",
                 len(all_elements), len(all_zones), used_layers)
        return bp

    def invalidate(self, window_class: str = "") -> None:
        if window_class:
            self._cache = {k: v for k, v in self._cache.items() if k[0] != window_class}
        else:
            self._cache.clear()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_desktop_use_blueprint.py -x -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/desktop_use/blueprint.py tests/test_desktop_use_blueprint.py
git commit -m "feat(desktop_use): add BlueprintBuilder — perception orchestration + cache"
```

---

### Task 6: DesktopEngine 集成 + __init__ 导出

**Files:**
- Modify: `src/desktop_use/engine.py`
- Modify: `src/desktop_use/__init__.py`
- Modify: `tests/test_desktop_use_engine.py`

- [ ] **Step 1: 写失败测试 — analyze() 和 read_zone()**

```python
# 追加到 tests/test_desktop_use_engine.py
from src.desktop_use.types import UIBlueprint, UIElement, UIZone

class TestDesktopEngineBlueprint:
    def test_engine_has_analyze(self):
        from src.desktop_use.engine import DesktopEngine
        engine = DesktopEngine()
        assert hasattr(engine, 'analyze')
        assert callable(engine.analyze)

    def test_engine_has_read_zone(self):
        from src.desktop_use.engine import DesktopEngine
        engine = DesktopEngine()
        assert hasattr(engine, 'read_zone')
        assert callable(engine.read_zone)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_desktop_use_engine.py::TestDesktopEngineBlueprint -x -v`
Expected: AttributeError — no attribute 'analyze'

- [ ] **Step 3: 给 DesktopEngine 加 analyze() 和 read_zone()**

在 `src/desktop_use/engine.py` 的 DesktopEngine 类中追加方法：

```python
def analyze(self, window_title: str = "", process_name: str = "",
            force: bool = False) -> UIBlueprint:
    """Analyze a window and return its UIBlueprint.

    Uses multi-layer perception: Win32 API → CV edge detection → OCR.
    Results are cached by window_class + size.
    """
    from .blueprint import BlueprintBuilder
    from .perception import Win32Layer, CVLayer, OCRLayer

    # Lock onto window
    info = self.window.lock(title_contains=window_title, process_name=process_name)
    if not info:
        from .types import UIBlueprint
        return UIBlueprint("unknown", (0, 0))

    # Build perception layers
    if not hasattr(self, '_blueprint_builder'):
        layers = [Win32Layer(), CVLayer(), OCRLayer(engine=self.ocr_engine)]
        self._blueprint_builder = BlueprintBuilder(layers=layers)

    rect = info.rect
    bp = self._blueprint_builder.build(
        hwnd=info.hwnd,
        window_class=info.class_name,
        rect=rect,
        force=force,
    )
    return bp

def read_zone(self, blueprint: UIBlueprint, zone_name: str) -> list[str]:
    """Read text from a dynamic zone using cropped OCR."""
    zone = blueprint.zone(zone_name)
    if not zone:
        return []

    # Capture window
    png = self.window.capture_window()
    if not png:
        return []

    # Crop to zone
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(png))
    zx1, zy1, zx2, zy2 = zone.rect
    cropped = img.crop((zx1, zy1, zx2, zy2))

    # OCR the crop
    words = self.ocr_engine.extract_words(cropped, "zh-Hans-CN")
    by_line = {}
    for w in words:
        by_line.setdefault(w.line_num, []).append(w)
    lines = []
    for ln in sorted(by_line):
        line_words = sorted(by_line[ln], key=lambda w: w.left)
        lines.append("".join(w.text for w in line_words))
    return lines
```

- [ ] **Step 4: 更新 __init__.py 导出**

在 `src/desktop_use/__init__.py` 中追加：

```python
from .types import UIElement, UIZone, UIBlueprint
from .perception import PerceptionLayer, Win32Layer, CVLayer, OCRLayer, PerceptionResult
from .blueprint import BlueprintBuilder
```

并更新 `__all__`。

- [ ] **Step 5: 跑全部测试确认通过**

Run: `pytest tests/test_desktop_use_*.py -x -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add src/desktop_use/engine.py src/desktop_use/__init__.py tests/test_desktop_use_engine.py
git commit -m "feat(desktop_use): integrate blueprint into DesktopEngine — analyze() + read_zone()"
```

---

### Task 7: 端到端验证

**Files:**
- 无新文件，手动验证

- [ ] **Step 1: 对文件资源管理器测试 — Win32 层应该够用**

```python
# 手动运行
from src.desktop_use import DesktopEngine
engine = DesktopEngine()
bp = engine.analyze(window_title="文件资源管理器")
print(f"Layers: {bp.perception_layers}")
print(f"Elements: {len(bp.elements)}")
for e in bp.elements[:10]:
    print(f"  [{e.source}] {e.element_type}: '{e.text}' at {e.rect}")
```

Expected: perception_layers=["win32"]，大量元素

- [ ] **Step 2: 对微信测试 — 应该降级到 CV + OCR**

```python
from src.desktop_use import DesktopEngine
engine = DesktopEngine()
bp = engine.analyze(window_title="微信")
print(f"Layers: {bp.perception_layers}")
print(f"Elements: {len(bp.elements)}, Zones: {len(bp.zones)}")
for z in bp.zones:
    print(f"  Zone '{z.name}': {z.rect} dynamic={z.dynamic}")
# Read chat zone
lines = engine.read_zone(bp, "zone_1_3")  # or whichever is the chat area
print(f"Chat text ({len(lines)} lines):")
for l in lines[:5]:
    print(f"  {l}")
```

Expected: perception_layers=["win32", "cv", "ocr"]，zones 有骨架区和动态区

- [ ] **Step 3: 性能验证**

```python
import time
engine = DesktopEngine()
# First call (cold)
t0 = time.perf_counter()
bp = engine.analyze(window_title="微信")
print(f"Cold: {(time.perf_counter()-t0)*1000:.0f}ms")
# Second call (cached)
t0 = time.perf_counter()
bp = engine.analyze(window_title="微信")
print(f"Cached: {(time.perf_counter()-t0)*1000:.0f}ms")
```

Expected: Cold ~120ms, Cached ~0ms

- [ ] **Step 4: 提交文档更新**

更新 spec 状态为"已实现"。

```bash
git add docs/superpowers/specs/2026-03-25-ui-blueprint-design.md
git commit -m "docs: mark UI blueprint spec as implemented"
```
