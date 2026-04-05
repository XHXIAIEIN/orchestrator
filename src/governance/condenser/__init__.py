# src/governance/condenser/__init__.py
from .base import Condenser, View, Event
from .recent_events import RecentEventsCondenser
from .amortized_forgetting import AmortizedForgettingCondenser
from .llm_summarizing import LLMSummarizingCondenser
from .water_level import WaterLevelCondenser
from .pipeline import CondenserPipeline
from .context_condenser import condense_context
from .configurable import ConfigurableCondenser, ConfigurableTrigger, RetentionPolicy
from .upload_stripper import UploadStripper
from .tool_output_pruner import ToolOutputPruner, PruneConfig

# Ratio-Based Compression adapter (stolen from Hermes)
# Wraps governance.compression.ContextCompressor as a Condenser so it can
# participate in CondenserPipeline alongside the OpenHands-style condensers.
try:
    from .ratio_compression import RatioCompressionCondenser
except ImportError:
    RatioCompressionCondenser = None

__all__ = [
    "Condenser", "View", "Event",
    "RecentEventsCondenser",
    "AmortizedForgettingCondenser",
    "LLMSummarizingCondenser",
    "WaterLevelCondenser",
    "CondenserPipeline",
    "condense_context",
    "ConfigurableCondenser",
    "ConfigurableTrigger",
    "RetentionPolicy",
    "UploadStripper",
    "ToolOutputPruner",
    "PruneConfig",
    "RatioCompressionCondenser",
]
