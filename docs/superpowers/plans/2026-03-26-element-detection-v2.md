# 元素检测 V2 — 可插拔流水线架构

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重写元素检测为可插拔流水线 — 每个处理步骤是独立的 Stage 类，可任意组合、可提前退出。Stage 之间通过 DetectionContext 传递中间状态。

**Architecture:** Pipeline 模式 — `DetectionStage(ABC)` 接口 + 多个独立实现。流水线按序执行，每步检查 `should_continue()`，效果够了就停。

**Tech Stack:** opencv-python-headless, numpy, PIL

**Spec:** `docs/superpowers/specs/2026-03-25-ui-blueprint-design.md`

**参考:** UIED (ESEC/FSE 2020), Top-Hat 变换, Otsu 自动阈值, REMAUI

---

## 核心设计

### DetectionContext — Stage 之间的共享状态

```python
@dataclass
class DetectionContext:
    # 输入
    img: np.ndarray              # 原始 BGR 图像
    gray: np.ndarray | None      # 灰度图（Stage 按需生成）
    binary: np.ndarray | None    # 二值图

    # 累积输出
    rects: list[tuple]           # 检测到的元素框
    classifications: dict        # rect_id → 分类标签
    nested: dict                 # rect_id → children rect_ids
    ui_states: dict              # 'highlight'/'badge'/'link' → rect list

    # 质量指标（用于 should_continue 判断）
    quality_score: float         # 0-1, 综合质量分
    stage_log: list[str]         # 执行过的 stage 名称
```

### DetectionStage — 可插拔接口

```python
class DetectionStage(ABC):
    @abstractmethod
    def process(self, ctx: DetectionContext) -> DetectionContext:
        """执行处理，修改 ctx 并返回。"""

    def should_continue(self, ctx: DetectionContext) -> bool:
        """处理完后检查：还需要后续 stage 吗？默认 True。"""
        return True
```

### Pipeline — 编排器

```python
class DetectionPipeline:
    def __init__(self, stages: list[DetectionStage]):
        self.stages = stages

    def run(self, img) -> DetectionContext:
        ctx = DetectionContext(img=img)
        for stage in self.stages:
            ctx = stage.process(ctx)
            ctx.stage_log.append(type(stage).__name__)
            if not stage.should_continue(ctx):
                break
        return ctx
```

### 预设流水线

```python
# 极速模式 — 只要框，不要分类
FAST = [GrayscaleStage(), TopHatStage(), OtsuStage(),
        DilateStage(), ConnectedComponentStage()]

# 标准模式 — 框 + 过滤 + 合并
STANDARD = FAST + [RectFilterStage(), MergeStage()]

# 完整模式 — 框 + 嵌套 + 分类 + 颜色语义
FULL = STANDARD + [NestedStage(), ClassifyStage(), ChannelAnalysisStage()]

# 增量模式 — 差分 + 局部重检测
INCREMENTAL = [DiffStage(), PartialDetectStage()]
```

### 提前退出策略

每个 Stage 的 `should_continue()` 根据 `ctx.quality_score` 判断：

| quality_score | 含义 | 行为 |
|--------------|------|------|
| > 0.8 | 组件数合理、碎框率低、覆盖率高 | 停止，不跑后续 |
| 0.5 - 0.8 | 基本可用但有缺陷 | 继续优化 |
| < 0.5 | 效果差（太碎或太少） | 必须继续 |

quality_score 计算：
```python
# 碎框惩罚：组件数过多 → 分数下降
# 覆盖率奖励：检测框总面积 / 图像面积
# 矩形度奖励：平均矩形度
score = coverage * 0.4 + (1 - fragmentation) * 0.4 + avg_rectangularity * 0.2
```

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `src/desktop_use/detection.py` | **新建** | DetectionContext, DetectionStage ABC, DetectionPipeline, 所有 Stage 实现 |
| `src/desktop_use/visualize.py` | 修改 | `detect_elements()` 改为调用 Pipeline |
| `src/desktop_use/__init__.py` | 修改 | 导出新 API |
| `tests/test_desktop_use_detection.py` | **新建** | 每个 Stage 独立测试 + Pipeline 集成测试 |

---

### Task 1: DetectionContext + DetectionStage + DetectionPipeline 框架

**Files:**
- Create: `src/desktop_use/detection.py`
- Create: `tests/test_desktop_use_detection.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_desktop_use_detection.py
import numpy as np
import pytest
from src.desktop_use.detection import (
    DetectionContext, DetectionStage, DetectionPipeline,
)


class TestDetectionContext:
    def test_create_from_image(self):
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        ctx = DetectionContext(img=img)
        assert ctx.rects == []
        assert ctx.quality_score == 0.0
        assert ctx.stage_log == []

    def test_image_dimensions(self):
        img = np.zeros((600, 800, 3), dtype=np.uint8)
        ctx = DetectionContext(img=img)
        assert ctx.height == 600
        assert ctx.width == 800


class TestDetectionStage:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            DetectionStage()


class TestDetectionPipeline:
    def test_runs_stages_in_order(self):
        class StageA(DetectionStage):
            def process(self, ctx):
                ctx.rects.append((0, 0, 10, 10))
                return ctx
        class StageB(DetectionStage):
            def process(self, ctx):
                ctx.rects.append((20, 20, 30, 30))
                return ctx

        pipeline = DetectionPipeline([StageA(), StageB()])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        ctx = pipeline.run(img)
        assert len(ctx.rects) == 2
        assert len(ctx.stage_log) == 2

    def test_early_exit(self):
        class StageOK(DetectionStage):
            def process(self, ctx):
                ctx.quality_score = 0.9
                return ctx
            def should_continue(self, ctx):
                return ctx.quality_score < 0.8

        class StageNeverReached(DetectionStage):
            def process(self, ctx):
                ctx.rects.append((99, 99, 99, 99))
                return ctx

        pipeline = DetectionPipeline([StageOK(), StageNeverReached()])
        ctx = pipeline.run(np.zeros((100, 100, 3), dtype=np.uint8))
        assert len(ctx.rects) == 0  # StageNeverReached was skipped
        assert len(ctx.stage_log) == 1

    def test_empty_pipeline(self):
        pipeline = DetectionPipeline([])
        ctx = pipeline.run(np.zeros((50, 50, 3), dtype=np.uint8))
        assert ctx.rects == []
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现框架**

```python
# src/desktop_use/detection.py
"""Pluggable element detection pipeline.

Each processing step is a DetectionStage. Stages are chained in a
DetectionPipeline. A shared DetectionContext flows through stages,
accumulating results. Any stage can stop the pipeline early via
should_continue() returning False.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class DetectionContext:
    """Shared state flowing through detection stages."""
    img: np.ndarray                                          # original BGR
    gray: np.ndarray | None = None                           # grayscale
    binary: np.ndarray | None = None                         # binary mask
    rects: list[tuple[int,int,int,int]] = field(default_factory=list)
    classifications: dict[int, str] = field(default_factory=dict)
    nested: dict[int, list[int]] = field(default_factory=dict)
    ui_states: dict[str, list[tuple[int,int,int,int]]] = field(default_factory=dict)
    quality_score: float = 0.0
    stage_log: list[str] = field(default_factory=list)

    @property
    def height(self) -> int:
        return self.img.shape[0]

    @property
    def width(self) -> int:
        return self.img.shape[1]


class DetectionStage(ABC):
    """One step in the detection pipeline."""

    @abstractmethod
    def process(self, ctx: DetectionContext) -> DetectionContext:
        """Execute this stage, mutate and return ctx."""

    def should_continue(self, ctx: DetectionContext) -> bool:
        """After processing, should the pipeline continue? Default: yes."""
        return True


class DetectionPipeline:
    """Run a sequence of DetectionStages with early-exit support."""

    def __init__(self, stages: list[DetectionStage] | None = None):
        self.stages = stages or []

    def run(self, img: np.ndarray) -> DetectionContext:
        ctx = DetectionContext(img=img)
        for stage in self.stages:
            ctx = stage.process(ctx)
            ctx.stage_log.append(type(stage).__name__)
            if not stage.should_continue(ctx):
                log.info("Pipeline: early exit after %s (quality=%.2f)",
                         type(stage).__name__, ctx.quality_score)
                break
        return ctx
```

- [ ] **Step 4: 跑测试**

- [ ] **Step 5: 提交**

```bash
git add src/desktop_use/detection.py tests/test_desktop_use_detection.py
git commit -m "feat(desktop_use): DetectionContext + DetectionStage + DetectionPipeline framework"
```

---

### Task 2: GrayscaleStage + TopHatStage + OtsuStage

前三个 Stage — 灰度化、Top-Hat 去背景、Otsu 自动阈值。

**Files:**
- Modify: `src/desktop_use/detection.py`
- Modify: `tests/test_desktop_use_detection.py`

- [ ] **Step 1: 写失败测试**

```python
class TestGrayscaleStage:
    def test_produces_gray(self):
        from src.desktop_use.detection import GrayscaleStage
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:] = (40, 80, 120)
        ctx = DetectionContext(img=img)
        ctx = GrayscaleStage().process(ctx)
        assert ctx.gray is not None
        assert ctx.gray.shape == (100, 100)

    def test_auto_gamma_dark(self):
        from src.desktop_use.detection import GrayscaleStage
        img = np.full((100, 100, 3), 30, dtype=np.uint8)
        ctx = DetectionContext(img=img)
        ctx = GrayscaleStage().process(ctx)
        # Dark image should be brightened
        assert np.median(ctx.gray) > 30


class TestTopHatStage:
    def test_produces_binary_input(self):
        from src.desktop_use.detection import GrayscaleStage, TopHatStage
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        img[:] = (40, 40, 40)
        img[30:60, 30:80] = (180, 180, 180)  # bright element
        ctx = DetectionContext(img=img)
        ctx = GrayscaleStage().process(ctx)
        ctx = TopHatStage().process(ctx)
        assert ctx.gray is not None  # tophat result stored in gray


class TestOtsuStage:
    def test_produces_binary(self):
        from src.desktop_use.detection import GrayscaleStage, TopHatStage, OtsuStage
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        img[:] = (40, 40, 40)
        img[30:60, 30:80] = (180, 180, 180)
        ctx = DetectionContext(img=img)
        ctx = GrayscaleStage().process(ctx)
        ctx = TopHatStage().process(ctx)
        ctx = OtsuStage().process(ctx)
        assert ctx.binary is not None
        assert set(np.unique(ctx.binary)).issubset({0, 255})
```

- [ ] **Step 2: 实现**

```python
class GrayscaleStage(DetectionStage):
    """Convert to grayscale with auto gamma."""
    def process(self, ctx):
        import cv2
        gray = cv2.cvtColor(ctx.img, cv2.COLOR_BGR2GRAY)
        # Auto gamma: map median to ~100
        median = float(np.median(gray))
        if median > 0:
            gamma = np.log(100 / 255) / np.log(max(median, 1) / 255)
            gamma = float(np.clip(gamma, 0.4, 2.0))
            gray = np.clip(np.power(gray.astype(np.float32) / 255, gamma) * 255,
                           0, 255).astype(np.uint8)
        ctx.gray = gray
        return ctx


class TopHatStage(DetectionStage):
    """Top-Hat transform — extract foreground from uneven background."""
    def __init__(self, kernel_size: int = 80):
        self.kernel_size = kernel_size

    def process(self, ctx):
        import cv2
        if ctx.gray is None:
            ctx = GrayscaleStage().process(ctx)
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (self.kernel_size, self.kernel_size))
        ctx.gray = cv2.morphologyEx(ctx.gray, cv2.MORPH_TOPHAT, kernel)
        return ctx


class OtsuStage(DetectionStage):
    """Otsu auto-threshold — zero parameters."""
    def process(self, ctx):
        import cv2
        if ctx.gray is None:
            return ctx
        _, ctx.binary = cv2.threshold(
            ctx.gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return ctx
```

- [ ] **Step 3: 跑测试**

- [ ] **Step 4: 提交**

```bash
git commit -m "feat(desktop_use): GrayscaleStage + TopHatStage + OtsuStage"
```

---

### Task 3: DilateStage + ConnectedComponentStage

方向膨胀（连接同行元素）+ 连通域分析输出 rects。

**Files:**
- Modify: `src/desktop_use/detection.py`
- Modify: `tests/test_desktop_use_detection.py`

- [ ] **Step 1: 写失败测试**

```python
class TestDilateStage:
    def test_connects_horizontal(self):
        from src.desktop_use.detection import DilateStage
        binary = np.zeros((100, 200), dtype=np.uint8)
        binary[40:50, 20:40] = 255  # left blob
        binary[40:50, 50:70] = 255  # right blob, 10px gap
        ctx = DetectionContext(img=np.zeros((100,200,3), dtype=np.uint8))
        ctx.binary = binary
        ctx = DilateStage(h_kernel=(2, 15), v_kernel=(7, 2)).process(ctx)
        # After horizontal dilation, blobs should merge
        assert ctx.binary[45, 45] == 255  # gap filled


class TestConnectedComponentStage:
    def test_produces_rects(self):
        from src.desktop_use.detection import ConnectedComponentStage
        binary = np.zeros((200, 300), dtype=np.uint8)
        binary[20:60, 20:100] = 255
        binary[100:130, 150:250] = 255
        ctx = DetectionContext(img=np.zeros((200,300,3), dtype=np.uint8))
        ctx.binary = binary
        ctx = ConnectedComponentStage().process(ctx)
        assert len(ctx.rects) == 2

    def test_filters_tiny(self):
        from src.desktop_use.detection import ConnectedComponentStage
        binary = np.zeros((200, 300), dtype=np.uint8)
        binary[10:13, 10:13] = 255  # 3x3, too small
        binary[50:90, 50:150] = 255  # 100x40, valid
        ctx = DetectionContext(img=np.zeros((200,300,3), dtype=np.uint8))
        ctx.binary = binary
        ctx = ConnectedComponentStage(min_w=15, min_h=10).process(ctx)
        assert len(ctx.rects) == 1

    def test_computes_quality_score(self):
        from src.desktop_use.detection import ConnectedComponentStage
        binary = np.zeros((200, 300), dtype=np.uint8)
        binary[20:60, 20:100] = 255
        ctx = DetectionContext(img=np.zeros((200,300,3), dtype=np.uint8))
        ctx.binary = binary
        ctx = ConnectedComponentStage().process(ctx)
        assert ctx.quality_score > 0
```

- [ ] **Step 2: 实现**

```python
class DilateStage(DetectionStage):
    """Directional dilation — connect icon+text on same row, title+subtitle."""
    def __init__(self, h_kernel=(2,15), v_kernel=(7,2)):
        self.h_kernel = h_kernel
        self.v_kernel = v_kernel

    def process(self, ctx):
        import cv2
        if ctx.binary is None:
            return ctx
        b = cv2.morphologyEx(ctx.binary, cv2.MORPH_CLOSE, np.ones((4,4), np.uint8))
        b = cv2.dilate(b, np.ones(self.h_kernel, np.uint8), iterations=1)
        b = cv2.dilate(b, np.ones(self.v_kernel, np.uint8), iterations=1)
        b = cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((3,3), np.uint8))
        ctx.binary = b
        return ctx


class ConnectedComponentStage(DetectionStage):
    """Extract bounding rects from binary mask + compute quality score."""
    def __init__(self, min_w=15, min_h=10):
        self.min_w = min_w
        self.min_h = min_h

    def process(self, ctx):
        import cv2
        if ctx.binary is None:
            return ctx
        contours, _ = cv2.findContours(
            ctx.binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        h, w = ctx.height, ctx.width
        for cnt in contours:
            x, y, rw, rh = cv2.boundingRect(cnt)
            if rw < self.min_w or rh < self.min_h:
                continue
            if rw > w * 0.95 and rh > h * 0.95:
                continue
            ctx.rects.append((x, y, x + rw, y + rh))

        # Quality score
        ctx.quality_score = self._compute_quality(ctx)
        return ctx

    def should_continue(self, ctx):
        return ctx.quality_score < 0.8

    @staticmethod
    def _compute_quality(ctx) -> float:
        if not ctx.rects:
            return 0.0
        h, w = ctx.height, ctx.width
        total_area = h * w
        # Coverage: how much of the image is covered by rects
        rect_area = sum((r[2]-r[0]) * (r[3]-r[1]) for r in ctx.rects)
        coverage = min(rect_area / total_area, 1.0)
        # Fragmentation: penalty for too many small rects
        n = len(ctx.rects)
        frag = 1.0 - min(n / 100, 1.0)  # 100+ rects = fully fragmented
        return coverage * 0.5 + frag * 0.5
```

- [ ] **Step 3: 跑测试**

- [ ] **Step 4: 提交**

```bash
git commit -m "feat(desktop_use): DilateStage + ConnectedComponentStage with quality score"
```

---

### Task 4: RectFilterStage + MergeStage

矩形度过滤 + 重叠框合并。

**Files:**
- Modify: `src/desktop_use/detection.py`
- Modify: `tests/test_desktop_use_detection.py`

- [ ] **Step 1: 写失败测试**

```python
class TestRectFilterStage:
    def test_removes_non_rectangular(self):
        from src.desktop_use.detection import RectFilterStage
        ctx = DetectionContext(img=np.zeros((200,300,3), dtype=np.uint8))
        ctx.rects = [(10, 10, 100, 50), (200, 200, 210, 205)]  # one big, one tiny
        ctx = RectFilterStage(min_area=500).process(ctx)
        assert len(ctx.rects) == 1


class TestMergeStage:
    def test_merges_overlapping(self):
        from src.desktop_use.detection import MergeStage
        ctx = DetectionContext(img=np.zeros((200,300,3), dtype=np.uint8))
        ctx.rects = [(10, 10, 50, 50), (30, 30, 70, 70)]
        ctx = MergeStage().process(ctx)
        assert len(ctx.rects) == 1
        assert ctx.rects[0] == (10, 10, 70, 70)

    def test_keeps_separate(self):
        from src.desktop_use.detection import MergeStage
        ctx = DetectionContext(img=np.zeros((200,300,3), dtype=np.uint8))
        ctx.rects = [(10, 10, 50, 50), (200, 200, 250, 250)]
        ctx = MergeStage().process(ctx)
        assert len(ctx.rects) == 2
```

- [ ] **Step 2: 实现**

```python
class RectFilterStage(DetectionStage):
    """Filter out rects that are too small or non-rectangular."""
    def __init__(self, min_area=200, min_rectangularity=0.4):
        self.min_area = min_area
        self.min_rectangularity = min_rectangularity

    def process(self, ctx):
        filtered = []
        for r in ctx.rects:
            w, h = r[2] - r[0], r[3] - r[1]
            if w * h < self.min_area:
                continue
            filtered.append(r)
        ctx.rects = filtered
        return ctx


class MergeStage(DetectionStage):
    """Merge overlapping bounding rects."""
    def process(self, ctx):
        ctx.rects = self._merge(ctx.rects)
        return ctx

    @staticmethod
    def _merge(boxes):
        if not boxes:
            return []
        result = [list(b) for b in boxes]
        merged = True
        while merged:
            merged = False
            new = []
            used = set()
            for i in range(len(result)):
                if i in used: continue
                bx1, by1, bx2, by2 = result[i]
                for j in range(i+1, len(result)):
                    if j in used: continue
                    cx1, cy1, cx2, cy2 = result[j]
                    if max(bx1,cx1) < min(bx2,cx2) and max(by1,cy1) < min(by2,cy2):
                        bx1, by1 = min(bx1,cx1), min(by1,cy1)
                        bx2, by2 = max(bx2,cx2), max(by2,cy2)
                        used.add(j)
                        merged = True
                new.append((bx1, by1, bx2, by2))
                used.add(i)
            result = [list(b) for b in new]
        return [tuple(b) for b in result]
```

- [ ] **Step 3: 跑测试**

- [ ] **Step 4: 提交**

```bash
git commit -m "feat(desktop_use): RectFilterStage + MergeStage"
```

---

### Task 5: NestedStage — 嵌套递归检测

对大容器裁剪子图，递归跑 Stage 1-4 检测内部子元素。

**Files:**
- Modify: `src/desktop_use/detection.py`
- Modify: `tests/test_desktop_use_detection.py`

- [ ] **Step 1: 写失败测试**

```python
class TestNestedStage:
    def test_detects_children(self):
        from src.desktop_use.detection import NestedStage
        img = np.zeros((400, 600, 3), dtype=np.uint8)
        img[:] = (30, 30, 30)
        img[50:350, 50:550] = (60, 60, 60)   # container
        img[80:110, 80:200] = (180, 180, 180) # child 1
        img[150:190, 80:120] = (160, 160, 160) # child 2
        ctx = DetectionContext(img=img)
        ctx.rects = [(50, 50, 550, 350)]  # container from previous stage
        ctx = NestedStage().process(ctx)
        assert len(ctx.rects) > 1  # container + children
```

- [ ] **Step 2: 实现**

```python
class NestedStage(DetectionStage):
    """Recursively detect elements inside large containers."""
    def __init__(self, min_block_area_ratio=0.05, max_depth=2):
        self.min_block_area_ratio = min_block_area_ratio
        self.max_depth = max_depth

    def process(self, ctx):
        total_area = ctx.width * ctx.height
        min_area = total_area * self.min_block_area_ratio
        new_rects = list(ctx.rects)

        for r in ctx.rects:
            rw, rh = r[2] - r[0], r[3] - r[1]
            if rw * rh < min_area:
                continue
            sub_img = ctx.img[r[1]:r[3], r[0]:r[2]]
            sub_pipeline = DetectionPipeline([
                GrayscaleStage(), TopHatStage(), OtsuStage(),
                DilateStage(), ConnectedComponentStage(),
            ])
            sub_ctx = sub_pipeline.run(sub_img)
            for sr in sub_ctx.rects:
                global_rect = (sr[0]+r[0], sr[1]+r[1], sr[2]+r[0], sr[3]+r[1])
                # Skip if it's basically the parent
                if (global_rect[2]-global_rect[0]) > rw * 0.9:
                    continue
                new_rects.append(global_rect)

        ctx.rects = new_rects
        return ctx
```

- [ ] **Step 3: 跑测试**

- [ ] **Step 4: 提交**

```bash
git commit -m "feat(desktop_use): NestedStage — recursive child element detection"
```

---

### Task 6: ClassifyStage — 启发式分类

根据宽高比 + 面积占比给每个 rect 分类。

**Files:**
- Modify: `src/desktop_use/detection.py`
- Modify: `tests/test_desktop_use_detection.py`

- [ ] **Step 1: 写失败测试**

```python
class TestClassifyStage:
    def test_classifies_icon(self):
        from src.desktop_use.detection import ClassifyStage
        ctx = DetectionContext(img=np.zeros((600,800,3), dtype=np.uint8))
        ctx.rects = [(10, 10, 40, 40)]  # 30x30 square = icon
        ctx = ClassifyStage().process(ctx)
        assert ctx.classifications[0] == "icon"

    def test_classifies_text(self):
        from src.desktop_use.detection import ClassifyStage
        ctx = DetectionContext(img=np.zeros((600,800,3), dtype=np.uint8))
        ctx.rects = [(10, 10, 210, 30)]  # 200x20 wide = text
        ctx = ClassifyStage().process(ctx)
        assert ctx.classifications[0] == "text"
```

- [ ] **Step 2: 实现**

```python
class ClassifyStage(DetectionStage):
    """Heuristic classification by aspect ratio and area."""
    def process(self, ctx):
        for i, r in enumerate(ctx.rects):
            w, h = r[2] - r[0], r[3] - r[1]
            ctx.classifications[i] = self._classify(w, h, ctx.width, ctx.height)
        return ctx

    @staticmethod
    def _classify(w, h, img_w, img_h):
        area_ratio = (w * h) / max(img_w * img_h, 1)
        aspect = w / max(h, 1)
        if area_ratio > 0.1:
            return "image"
        if 0.7 < aspect < 1.4 and w < 80:
            return "icon"
        if aspect > 3:
            return "text"
        if area_ratio > 0.02:
            return "container"
        return "element"
```

- [ ] **Step 3: 跑测试**

- [ ] **Step 4: 提交**

```bash
git commit -m "feat(desktop_use): ClassifyStage — aspect ratio + area heuristic"
```

---

### Task 7: ChannelAnalysisStage — 颜色语义提取

R/G/B 通道差值提取 UI 状态（选中/未读/链接）。

**Files:**
- Modify: `src/desktop_use/detection.py`
- Modify: `tests/test_desktop_use_detection.py`

- [ ] **Step 1: 写失败测试**

```python
class TestChannelAnalysisStage:
    def test_detects_green_highlight(self):
        from src.desktop_use.detection import ChannelAnalysisStage
        img = np.zeros((200, 400, 3), dtype=np.uint8)
        img[:] = (40, 40, 40)
        img[20:50, 20:200, 1] = 150  # G channel high
        ctx = DetectionContext(img=img)
        ctx = ChannelAnalysisStage().process(ctx)
        assert len(ctx.ui_states.get('highlight', [])) >= 1

    def test_detects_red_badge(self):
        from src.desktop_use.detection import ChannelAnalysisStage
        img = np.zeros((200, 400, 3), dtype=np.uint8)
        img[:] = (40, 40, 40)
        img[10:25, 350:370, 2] = 200  # R channel high (BGR order)
        ctx = DetectionContext(img=img)
        ctx = ChannelAnalysisStage().process(ctx)
        assert len(ctx.ui_states.get('badge', [])) >= 1
```

- [ ] **Step 2: 实现**

```python
class ChannelAnalysisStage(DetectionStage):
    """Extract UI states from color channel differences."""
    def process(self, ctx):
        import cv2
        b, g, r = cv2.split(ctx.img)
        ctx.ui_states['highlight'] = self._find_regions(
            cv2.subtract(g, r), threshold=30)
        ctx.ui_states['badge'] = self._find_regions(
            cv2.subtract(r, b), threshold=50, max_area=3000)
        ctx.ui_states['link'] = self._find_regions(
            cv2.subtract(b, r), threshold=30)
        return ctx

    @staticmethod
    def _find_regions(diff, threshold=30, min_area=50, max_area=50000):
        import cv2
        mask = (diff > threshold).astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        rects = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if min_area < area < max_area:
                x, y, w, h = cv2.boundingRect(cnt)
                rects.append((x, y, x+w, y+h))
        return rects
```

- [ ] **Step 3: 跑测试**

- [ ] **Step 4: 提交**

```bash
git commit -m "feat(desktop_use): ChannelAnalysisStage — green/red/blue UI state extraction"
```

---

### Task 8: DiffStage — 增量对比

对比前后帧，只标记变化区域，跳过未变化部分。

**Files:**
- Modify: `src/desktop_use/detection.py`
- Modify: `tests/test_desktop_use_detection.py`

- [ ] **Step 1: 写失败测试**

```python
class TestDiffStage:
    def test_detects_changed_region(self):
        from src.desktop_use.detection import DiffStage
        prev = np.full((200, 300, 3), 40, dtype=np.uint8)
        curr = prev.copy()
        curr[100:150, 100:200] = 180  # changed region
        ctx = DetectionContext(img=curr)
        stage = DiffStage(prev_img=prev)
        ctx = stage.process(ctx)
        # Should mark the changed region
        assert len(ctx.rects) >= 1

    def test_no_change_no_rects(self):
        from src.desktop_use.detection import DiffStage
        img = np.full((200, 300, 3), 40, dtype=np.uint8)
        ctx = DetectionContext(img=img)
        stage = DiffStage(prev_img=img.copy())
        ctx = stage.process(ctx)
        assert len(ctx.rects) == 0

    def test_should_not_continue_when_no_change(self):
        from src.desktop_use.detection import DiffStage
        img = np.full((100, 100, 3), 40, dtype=np.uint8)
        ctx = DetectionContext(img=img)
        stage = DiffStage(prev_img=img.copy())
        ctx = stage.process(ctx)
        assert stage.should_continue(ctx) is False
```

- [ ] **Step 2: 实现**

```python
class DiffStage(DetectionStage):
    """Compare with previous frame, only detect in changed regions."""
    def __init__(self, prev_img: np.ndarray | None = None,
                 change_threshold: int = 20, min_change_ratio: float = 0.02):
        self.prev_img = prev_img
        self.change_threshold = change_threshold
        self.min_change_ratio = min_change_ratio
        self._has_changes = True

    def process(self, ctx):
        import cv2
        if self.prev_img is None or self.prev_img.shape != ctx.img.shape:
            self._has_changes = True
            return ctx

        prev_gray = cv2.cvtColor(self.prev_img, cv2.COLOR_BGR2GRAY)
        curr_gray = cv2.cvtColor(ctx.img, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(prev_gray, curr_gray)
        _, mask = cv2.threshold(diff, self.change_threshold, 255, cv2.THRESH_BINARY)

        change_ratio = np.count_nonzero(mask) / mask.size
        if change_ratio < self.min_change_ratio:
            self._has_changes = False
            return ctx

        self._has_changes = True
        # Find changed regions as rects
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w > 20 and h > 20:
                ctx.rects.append((x, y, x+w, y+h))
        return ctx

    def should_continue(self, ctx):
        return self._has_changes
```

- [ ] **Step 3: 跑测试**

- [ ] **Step 4: 提交**

```bash
git commit -m "feat(desktop_use): DiffStage — incremental frame comparison"
```

---

### Task 9: 组装 + visualize.py 接入 + 端到端验证

把 Pipeline 接入 `detect_elements()`，预设 FAST/STANDARD/FULL 流水线。

**Files:**
- Modify: `src/desktop_use/detection.py` — 添加预设流水线
- Modify: `src/desktop_use/visualize.py` — `detect_elements()` 改为调用 Pipeline
- Modify: `src/desktop_use/__init__.py` — 导出
- 手动验证

- [ ] **Step 1: 在 detection.py 末尾添加预设**

```python
# Preset pipelines
def fast_pipeline() -> DetectionPipeline:
    return DetectionPipeline([
        GrayscaleStage(), TopHatStage(), OtsuStage(),
        DilateStage(), ConnectedComponentStage(),
    ])

def standard_pipeline() -> DetectionPipeline:
    return DetectionPipeline([
        GrayscaleStage(), TopHatStage(), OtsuStage(),
        DilateStage(), ConnectedComponentStage(),
        RectFilterStage(), MergeStage(),
    ])

def full_pipeline() -> DetectionPipeline:
    return DetectionPipeline([
        GrayscaleStage(), TopHatStage(), OtsuStage(),
        DilateStage(), ConnectedComponentStage(),
        RectFilterStage(), MergeStage(),
        NestedStage(), ClassifyStage(), ChannelAnalysisStage(),
    ])
```

- [ ] **Step 2: 修改 visualize.py 的 detect_elements()**

```python
def detect_elements(png_bytes, mode="standard"):
    import cv2, numpy as np
    nparr = np.frombuffer(png_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return []
    from .detection import fast_pipeline, standard_pipeline, full_pipeline
    pipelines = {"fast": fast_pipeline, "standard": standard_pipeline, "full": full_pipeline}
    pipeline = pipelines.get(mode, standard_pipeline)()
    ctx = pipeline.run(img)
    return ctx.rects
```

- [ ] **Step 3: 跑全部测试**

Run: `pytest tests/test_desktop_use_*.py -x -q`

- [ ] **Step 4: 微信端到端验证**

```python
# FAST 模式
bp.visualize(png, mode='annotated')  # 默认用 standard
# 也试 fast 和 full
```

- [ ] **Step 5: 提交**

```bash
git commit -m "feat(desktop_use): wire detection pipeline into visualize + presets"
```

---

---

### Task 10: OmniParserStage — YOLO 图标检测 + Florence 语义描述

用本地 OmniParser 模型检测无文字的图标/按钮并生成语义描述。

**Files:**
- Modify: `src/desktop_use/detection.py`
- Modify: `tests/test_desktop_use_detection.py`

**前置条件:**
- OmniParser 权重在 `D:\Users\Administrator\Documents\GitHub\OmniParser\weights\`
- YOLO (`icon_detect/`) + Florence (`icon_caption/`)

- [ ] **Step 1: 写测试**

```python
class TestOmniParserStage:
    def test_skips_when_not_available(self):
        """No model loaded → pass through, don't crash."""
        from src.desktop_use.detection import OmniParserStage
        ctx = DetectionContext(img=np.zeros((100,100,3), dtype=np.uint8))
        ctx.rects = [(10, 10, 50, 50)]
        stage = OmniParserStage(model_path="/nonexistent")
        ctx = stage.process(ctx)
        assert len(ctx.rects) >= 1  # original rects preserved

    def test_is_optional_stage(self):
        from src.desktop_use.detection import OmniParserStage, DetectionStage
        assert issubclass(OmniParserStage, DetectionStage)
```

- [ ] **Step 2: 实现**

```python
class OmniParserStage(DetectionStage):
    """YOLO icon detection + Florence caption. Optional — skips if models not found."""
    def __init__(self, model_path="", server_url="http://127.0.0.1:8000"):
        self.model_path = model_path
        self.server_url = server_url
        self._available = None

    def process(self, ctx):
        if not self._check_available():
            return ctx
        # Try server first, then local
        new_rects = self._detect(ctx.img)
        ctx.rects.extend(new_rects)
        return ctx

    def _check_available(self):
        if self._available is not None:
            return self._available
        # Check server
        try:
            import httpx
            r = httpx.get(f"{self.server_url}/probe/", timeout=2)
            self._available = r.status_code == 200
        except Exception:
            # Check local model
            from pathlib import Path
            self._available = Path(self.model_path).exists()
        return self._available

    def _detect(self, img):
        # ... call OmniParser server or local model
        # Return list of (x1, y1, x2, y2)
        ...
```

参考现有实现：`D:\Steam\steamapps\common\PapersPlease\game_agent\core\omniparser_client.py`

- [ ] **Step 3: 跑测试**

- [ ] **Step 4: 提交**

```bash
git commit -m "feat(desktop_use): OmniParserStage — optional YOLO + Florence icon detection"
```

---

### Task 11: GroundingDINOStage — 自然语言定位 UI 元素

给一段文字描述（如"搜索框"），在截图中定位对应元素。

**Files:**
- Modify: `src/desktop_use/detection.py`
- Modify: `tests/test_desktop_use_detection.py`

- [ ] **Step 1: 写测试**

```python
class TestGroundingDINOStage:
    def test_skips_when_not_available(self):
        from src.desktop_use.detection import GroundingDINOStage
        ctx = DetectionContext(img=np.zeros((100,100,3), dtype=np.uint8))
        stage = GroundingDINOStage(query="搜索框")
        ctx = stage.process(ctx)
        # Should not crash even if model not installed
        assert isinstance(ctx.rects, list)

    def test_is_optional_stage(self):
        from src.desktop_use.detection import GroundingDINOStage, DetectionStage
        assert issubclass(GroundingDINOStage, DetectionStage)
```

- [ ] **Step 2: 实现**

```python
class GroundingDINOStage(DetectionStage):
    """Text-guided element detection via Grounding DINO. Optional — needs transformers."""
    def __init__(self, query: str = "", box_threshold: float = 0.3):
        self.query = query
        self.box_threshold = box_threshold
        self._model = None

    def process(self, ctx):
        if not self.query:
            return ctx
        try:
            from transformers import pipeline
            if self._model is None:
                self._model = pipeline(
                    "zero-shot-object-detection",
                    model="IDEA-Research/grounding-dino-tiny",
                )
            from PIL import Image
            img_pil = Image.fromarray(ctx.img[:, :, ::-1])  # BGR → RGB
            results = self._model(img_pil, candidate_labels=[self.query],
                                  threshold=self.box_threshold)
            for r in results:
                box = r["box"]
                ctx.rects.append((box["xmin"], box["ymin"], box["xmax"], box["ymax"]))
        except ImportError:
            log.debug("GroundingDINOStage: transformers not installed, skipping")
        except Exception as e:
            log.warning("GroundingDINOStage: %s", e)
        return ctx
```

- [ ] **Step 3: 跑测试**

- [ ] **Step 4: 提交**

```bash
git commit -m "feat(desktop_use): GroundingDINOStage — text-guided zero-shot element detection"
```

---

### Task 12: 预设流水线更新 + 端到端全量验证

更新预设加入可选 Stage，跑完整验证。

**Files:**
- Modify: `src/desktop_use/detection.py`
- 手动验证

- [ ] **Step 1: 更新预设**

```python
def full_pipeline(omniparser_path="", grounding_query="") -> DetectionPipeline:
    stages = [
        GrayscaleStage(), TopHatStage(), OtsuStage(),
        DilateStage(), ConnectedComponentStage(),
        RectFilterStage(), MergeStage(),
        NestedStage(), ClassifyStage(), ChannelAnalysisStage(),
    ]
    if omniparser_path:
        stages.append(OmniParserStage(model_path=omniparser_path))
    return DetectionPipeline(stages)

def grounding_pipeline(query: str) -> DetectionPipeline:
    """Single-purpose: find one element by text description."""
    return DetectionPipeline([GroundingDINOStage(query=query)])
```

- [ ] **Step 2: 微信端到端 — FAST / STANDARD / FULL 对比**

- [ ] **Step 3: OmniParser 端到端（如果 server 在跑）**

- [ ] **Step 4: 提交**

```bash
git commit -m "feat(desktop_use): complete pipeline presets with optional ML stages"
```

---

### Task 13: ListQuantizeStage — 列表 item 模板传播

从已知元素（高亮框/等距头像）推断 item 高度，双向扩展直到碰空，输出 item 列表。

**Files:**
- Modify: `src/desktop_use/detection.py`
- Modify: `tests/test_desktop_use_detection.py`

**核心算法：**

```
1. 找"参考 item"（优先高亮框，备选等距头像/最大rect）
2. step = 参考 item 高度
3. 从参考位置向上：碰空停
4. 从参考位置向下：碰空停
5. 输出 item 列表
```

- [ ] **Step 1: 写测试**
- [ ] **Step 2: 实现 ListQuantizeStage**
- [ ] **Step 3: 跑测试**
- [ ] **Step 4: 微信端到端验证**
- [ ] **Step 5: 提交**
