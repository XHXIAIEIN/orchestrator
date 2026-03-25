"""Tests for pluggable detection pipeline."""
import numpy as np
import pytest

from src.desktop_use.detection import (
    DetectionContext,
    DetectionStage,
    DetectionPipeline,
    GrayscaleStage,
    TopHatStage,
    OtsuStage,
    DilateStage,
    ConnectedComponentStage,
    RectFilterStage,
    MergeStage,
)


# ---------------------------------------------------------------------------
# Framework tests
# ---------------------------------------------------------------------------

class TestDetectionContext:
    def test_create_from_image(self):
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        ctx = DetectionContext(img=img)
        assert ctx.rects == []
        assert ctx.quality_score == 0.0
        assert ctx.stage_log == []

    def test_dimensions(self):
        ctx = DetectionContext(img=np.zeros((600, 800, 3), dtype=np.uint8))
        assert ctx.height == 600
        assert ctx.width == 800


class TestDetectionStage:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            DetectionStage()


class TestDetectionPipeline:
    def test_runs_in_order(self):
        class A(DetectionStage):
            def process(self, ctx):
                ctx.rects.append((0, 0, 10, 10))
                return ctx

        class B(DetectionStage):
            def process(self, ctx):
                ctx.rects.append((20, 20, 30, 30))
                return ctx

        ctx = DetectionPipeline([A(), B()]).run(np.zeros((100, 100, 3), dtype=np.uint8))
        assert len(ctx.rects) == 2
        assert len(ctx.stage_log) == 2

    def test_early_exit(self):
        class StopEarly(DetectionStage):
            def process(self, ctx):
                ctx.quality_score = 0.9
                return ctx
            def should_continue(self, ctx):
                return ctx.quality_score < 0.8

        class NeverReached(DetectionStage):
            def process(self, ctx):
                ctx.rects.append((99, 99, 99, 99))
                return ctx

        ctx = DetectionPipeline([StopEarly(), NeverReached()]).run(
            np.zeros((100, 100, 3), dtype=np.uint8))
        assert len(ctx.rects) == 0
        assert len(ctx.stage_log) == 1

    def test_empty_pipeline(self):
        ctx = DetectionPipeline([]).run(np.zeros((50, 50, 3), dtype=np.uint8))
        assert ctx.rects == []


# ---------------------------------------------------------------------------
# Stage tests
# ---------------------------------------------------------------------------

class TestGrayscaleStage:
    def test_produces_gray(self):
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:] = (40, 80, 120)
        ctx = GrayscaleStage().process(DetectionContext(img=img))
        assert ctx.gray is not None
        assert ctx.gray.shape == (100, 100)

    def test_dark_image_brightened(self):
        img = np.full((100, 100, 3), 30, dtype=np.uint8)
        ctx = GrayscaleStage().process(DetectionContext(img=img))
        assert np.median(ctx.gray) > 30

    def test_light_image_not_overexposed(self):
        img = np.full((100, 100, 3), 220, dtype=np.uint8)
        ctx = GrayscaleStage().process(DetectionContext(img=img))
        assert np.median(ctx.gray) < 255


class TestTopHatStage:
    def test_extracts_bright_elements(self):
        img = np.zeros((200, 300, 3), dtype=np.uint8)
        img[:] = (40, 40, 40)
        img[50:80, 50:150] = (180, 180, 180)
        ctx = DetectionContext(img=img)
        ctx = GrayscaleStage().process(ctx)
        ctx = TopHatStage().process(ctx)
        # TopHat result should have high values where bright element is
        assert ctx.gray[65, 100] > ctx.gray[10, 10]

    def test_needs_gray(self):
        """Auto-generates gray if missing."""
        img = np.full((50, 50, 3), 100, dtype=np.uint8)
        ctx = TopHatStage().process(DetectionContext(img=img))
        assert ctx.gray is not None


class TestOtsuStage:
    def test_produces_binary(self):
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        img[:] = (40, 40, 40)
        img[30:60, 30:80] = (180, 180, 180)
        ctx = DetectionContext(img=img)
        ctx = GrayscaleStage().process(ctx)
        ctx = TopHatStage().process(ctx)
        ctx = OtsuStage().process(ctx)
        assert ctx.binary is not None
        assert set(np.unique(ctx.binary)).issubset({0, 255})

    def test_skips_without_gray(self):
        ctx = OtsuStage().process(DetectionContext(img=np.zeros((10, 10, 3), dtype=np.uint8)))
        assert ctx.binary is None


class TestDilateStage:
    def test_connects_horizontal_gap(self):
        binary = np.zeros((100, 200), dtype=np.uint8)
        binary[40:50, 20:40] = 255
        binary[40:50, 50:70] = 255  # 10px gap
        ctx = DetectionContext(img=np.zeros((100, 200, 3), dtype=np.uint8))
        ctx.binary = binary
        ctx = DilateStage(h_kernel=(2, 15), v_kernel=(7, 2)).process(ctx)
        assert ctx.binary[45, 45] == 255

    def test_skips_without_binary(self):
        ctx = DilateStage().process(
            DetectionContext(img=np.zeros((10, 10, 3), dtype=np.uint8)))
        assert ctx.binary is None


class TestConnectedComponentStage:
    def test_produces_rects(self):
        binary = np.zeros((200, 300), dtype=np.uint8)
        binary[20:60, 20:100] = 255
        binary[100:130, 150:250] = 255
        ctx = DetectionContext(img=np.zeros((200, 300, 3), dtype=np.uint8))
        ctx.binary = binary
        ctx = ConnectedComponentStage().process(ctx)
        assert len(ctx.rects) == 2

    def test_filters_tiny(self):
        binary = np.zeros((200, 300), dtype=np.uint8)
        binary[10:13, 10:13] = 255  # too small
        binary[50:90, 50:150] = 255
        ctx = DetectionContext(img=np.zeros((200, 300, 3), dtype=np.uint8))
        ctx.binary = binary
        ctx = ConnectedComponentStage(min_w=15, min_h=10).process(ctx)
        assert len(ctx.rects) == 1

    def test_computes_quality(self):
        binary = np.zeros((200, 300), dtype=np.uint8)
        binary[20:60, 20:100] = 255
        ctx = DetectionContext(img=np.zeros((200, 300, 3), dtype=np.uint8))
        ctx.binary = binary
        ctx = ConnectedComponentStage().process(ctx)
        assert ctx.quality_score > 0

    def test_should_continue_when_low_quality(self):
        stage = ConnectedComponentStage()
        ctx = DetectionContext(img=np.zeros((10, 10, 3), dtype=np.uint8))
        ctx.quality_score = 0.3
        assert stage.should_continue(ctx) is True

    def test_should_stop_when_high_quality(self):
        stage = ConnectedComponentStage()
        ctx = DetectionContext(img=np.zeros((10, 10, 3), dtype=np.uint8))
        ctx.quality_score = 0.9
        assert stage.should_continue(ctx) is False


class TestRectFilterStage:
    def test_removes_small(self):
        ctx = DetectionContext(img=np.zeros((200, 300, 3), dtype=np.uint8))
        ctx.rects = [(10, 10, 100, 50), (200, 200, 205, 203)]  # big + tiny
        ctx = RectFilterStage(min_area=500).process(ctx)
        assert len(ctx.rects) == 1

    def test_keeps_large(self):
        ctx = DetectionContext(img=np.zeros((200, 300, 3), dtype=np.uint8))
        ctx.rects = [(0, 0, 100, 100)]
        ctx = RectFilterStage(min_area=200).process(ctx)
        assert len(ctx.rects) == 1


class TestMergeStage:
    def test_merges_overlapping(self):
        ctx = DetectionContext(img=np.zeros((200, 300, 3), dtype=np.uint8))
        ctx.rects = [(10, 10, 50, 50), (30, 30, 70, 70)]
        ctx = MergeStage().process(ctx)
        assert len(ctx.rects) == 1
        assert ctx.rects[0] == (10, 10, 70, 70)

    def test_keeps_separate(self):
        ctx = DetectionContext(img=np.zeros((200, 300, 3), dtype=np.uint8))
        ctx.rects = [(10, 10, 50, 50), (200, 200, 250, 250)]
        ctx = MergeStage().process(ctx)
        assert len(ctx.rects) == 2

    def test_chain_merge(self):
        """A overlaps B, B overlaps C → all merge into one."""
        ctx = DetectionContext(img=np.zeros((200, 300, 3), dtype=np.uint8))
        ctx.rects = [(0, 0, 30, 30), (20, 20, 50, 50), (40, 40, 70, 70)]
        ctx = MergeStage().process(ctx)
        assert len(ctx.rects) == 1

    def test_empty(self):
        ctx = DetectionContext(img=np.zeros((10, 10, 3), dtype=np.uint8))
        ctx.rects = []
        ctx = MergeStage().process(ctx)
        assert ctx.rects == []


# ---------------------------------------------------------------------------
# Integration: mini pipeline
# ---------------------------------------------------------------------------

class TestMiniPipeline:
    def _make_ui_image(self):
        img = np.zeros((300, 400, 3), dtype=np.uint8)
        img[:] = (40, 40, 40)
        img[30:60, 30:80] = (180, 180, 180)
        img[30:55, 100:250] = (200, 200, 200)
        img[100:130, 30:80] = (160, 160, 160)
        img[100:120, 100:200] = (180, 180, 180)
        return img

    def test_fast_pipeline(self):
        pipeline = DetectionPipeline([
            GrayscaleStage(), TopHatStage(), OtsuStage(),
            DilateStage(), ConnectedComponentStage(),
        ])
        ctx = pipeline.run(self._make_ui_image())
        assert len(ctx.rects) >= 2
        assert len(ctx.stage_log) <= 5

    def test_standard_pipeline(self):
        pipeline = DetectionPipeline([
            GrayscaleStage(), TopHatStage(), OtsuStage(),
            DilateStage(), ConnectedComponentStage(),
            RectFilterStage(), MergeStage(),
        ])
        ctx = pipeline.run(self._make_ui_image())
        assert len(ctx.rects) >= 1
