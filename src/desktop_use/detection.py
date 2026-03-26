"""Detection pipeline — re-exported from cvui library.

All detection stages, pipeline, and presets are provided by the cvui package.
This module re-exports everything for backward compatibility.

Install cvui: pip install -e path/to/cvui  (or pip install cvui)
"""

# Re-export everything from cvui
from cvui.pipeline import DetectionContext, DetectionStage, DetectionPipeline
from cvui.stages import (
    DownscaleStage, GrayscaleStage, TopHatStage, OtsuStage,
    DilateStage, ConnectedComponentStage, RectFilterStage, MergeStage,
    NestedStage, ClassifyStage, ChannelAnalysisStage, DiffStage,
    ListQuantizeStage, OmniParserStage, GroundingDINOStage,
    fast_pipeline, standard_pipeline, full_pipeline, grounding_pipeline,
)

__all__ = [
    "DetectionContext", "DetectionStage", "DetectionPipeline",
    "DownscaleStage", "GrayscaleStage", "TopHatStage", "OtsuStage",
    "DilateStage", "ConnectedComponentStage", "RectFilterStage", "MergeStage",
    "NestedStage", "ClassifyStage", "ChannelAnalysisStage", "DiffStage",
    "ListQuantizeStage", "OmniParserStage", "GroundingDINOStage",
    "fast_pipeline", "standard_pipeline", "full_pipeline", "grounding_pipeline",
]
