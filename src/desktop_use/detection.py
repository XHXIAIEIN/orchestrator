"""Pluggable element detection pipeline.

Each processing step is a DetectionStage. Stages are chained in a
DetectionPipeline. A shared DetectionContext flows through stages,
accumulating results. Any stage can stop the pipeline early via
should_continue() returning False.

Preset pipelines:
- fast_pipeline(): Grayscale → TopHat → Otsu → Dilate → ConnectedComponent
- standard_pipeline(): fast + RectFilter + Merge
- full_pipeline(): standard + Nested + Classify + ChannelAnalysis
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

@dataclass
class DetectionContext:
    """Shared state flowing through detection stages."""
    img: np.ndarray
    gray: np.ndarray | None = None
    binary: np.ndarray | None = None
    rects: list[tuple[int, int, int, int]] = field(default_factory=list)
    classifications: dict[int, str] = field(default_factory=dict)
    nested: dict[int, list[int]] = field(default_factory=dict)
    ui_states: dict[str, list[tuple[int, int, int, int]]] = field(default_factory=dict)
    quality_score: float = 0.0
    stage_log: list[str] = field(default_factory=list)

    @property
    def height(self) -> int:
        return self.img.shape[0]

    @property
    def width(self) -> int:
        return self.img.shape[1]


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------

class DetectionStage(ABC):
    """One step in the detection pipeline."""

    @abstractmethod
    def process(self, ctx: DetectionContext) -> DetectionContext:
        """Execute this stage, mutate and return ctx."""

    def should_continue(self, ctx: DetectionContext) -> bool:
        """After processing, should the pipeline continue? Default: yes."""
        return True


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------

class GrayscaleStage(DetectionStage):
    """Convert to grayscale with auto gamma from median brightness."""

    def process(self, ctx):
        import cv2
        gray = cv2.cvtColor(ctx.img, cv2.COLOR_BGR2GRAY)
        median = float(np.median(gray))
        if median > 0:
            gamma = np.log(100.0 / 255.0) / np.log(max(median, 1.0) / 255.0)
            gamma = float(np.clip(gamma, 0.4, 2.0))
            gray = np.clip(
                np.power(gray.astype(np.float32) / 255.0, gamma) * 255.0,
                0, 255,
            ).astype(np.uint8)
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


class DilateStage(DetectionStage):
    """Directional dilation — connect icon+text on same row, title+subtitle."""

    def __init__(self, h_kernel: tuple[int, int] = (2, 15),
                 v_kernel: tuple[int, int] = (7, 2)):
        self.h_kernel = h_kernel
        self.v_kernel = v_kernel

    def process(self, ctx):
        import cv2
        if ctx.binary is None:
            return ctx
        b = cv2.morphologyEx(ctx.binary, cv2.MORPH_CLOSE, np.ones((4, 4), np.uint8))
        b = cv2.dilate(b, np.ones(self.h_kernel, np.uint8), iterations=1)
        b = cv2.dilate(b, np.ones(self.v_kernel, np.uint8), iterations=1)
        b = cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        ctx.binary = b
        return ctx


class ConnectedComponentStage(DetectionStage):
    """Extract bounding rects from binary mask + compute quality score."""

    def __init__(self, min_w: int = 15, min_h: int = 10):
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
        ctx.quality_score = self._compute_quality(ctx)
        return ctx

    def should_continue(self, ctx):
        return ctx.quality_score < 0.8

    @staticmethod
    def _compute_quality(ctx) -> float:
        if not ctx.rects:
            return 0.0
        total_area = ctx.height * ctx.width
        rect_area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in ctx.rects)
        coverage = min(rect_area / max(total_area, 1), 1.0)
        n = len(ctx.rects)
        frag = 1.0 - min(n / 100.0, 1.0)
        return coverage * 0.5 + frag * 0.5


class RectFilterStage(DetectionStage):
    """Filter out rects that are too small."""

    def __init__(self, min_area: int = 200):
        self.min_area = min_area

    def process(self, ctx):
        ctx.rects = [
            r for r in ctx.rects
            if (r[2] - r[0]) * (r[3] - r[1]) >= self.min_area
        ]
        return ctx


class MergeStage(DetectionStage):
    """Merge overlapping bounding rects."""

    def process(self, ctx):
        ctx.rects = self._merge(ctx.rects)
        return ctx

    @staticmethod
    def _merge(boxes: list[tuple]) -> list[tuple]:
        if not boxes:
            return []
        result = [list(b) for b in boxes]
        merged = True
        while merged:
            merged = False
            new = []
            used = set()
            for i in range(len(result)):
                if i in used:
                    continue
                bx1, by1, bx2, by2 = result[i]
                for j in range(i + 1, len(result)):
                    if j in used:
                        continue
                    cx1, cy1, cx2, cy2 = result[j]
                    if max(bx1, cx1) < min(bx2, cx2) and max(by1, cy1) < min(by2, cy2):
                        bx1, by1 = min(bx1, cx1), min(by1, cy1)
                        bx2, by2 = max(bx2, cx2), max(by2, cy2)
                        used.add(j)
                        merged = True
                new.append((bx1, by1, bx2, by2))
                used.add(i)
            result = [list(b) for b in new]
        return [tuple(b) for b in result]
