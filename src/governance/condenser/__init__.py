# src/governance/condenser/__init__.py
from .base import Condenser, View, Event
from .recent_events import RecentEventsCondenser
from .amortized_forgetting import AmortizedForgettingCondenser
from .llm_summarizing import LLMSummarizingCondenser
from .water_level import WaterLevelCondenser
from .pipeline import CondenserPipeline

__all__ = [
    "Condenser", "View", "Event",
    "RecentEventsCondenser",
    "AmortizedForgettingCondenser",
    "LLMSummarizingCondenser",
    "WaterLevelCondenser",
    "CondenserPipeline",
]
