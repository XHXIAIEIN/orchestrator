"""desktop_use -- pluggable desktop GUI automation module."""

from .types import (
    OCRWord,
    LocateResult,
    MonitorInfo,
    WindowInfo,
    GUIResult,
    TrajectoryStep,
)
from .ocr import OCREngine, WinOCREngine
from .match import MatchStrategy, FuzzyMatchStrategy
from .screen import ScreenCapture, MSSScreenCapture
from .window import WindowManager, Win32WindowManager
from .actions import ActionExecutor, PyAutoGUIExecutor, ALLOWED_ACTIONS
from .trajectory import Trajectory
from .engine import DesktopEngine
from .prompts import REASONER_SYSTEM, build_reasoner_prompt
from .types import UIElement, UIZone, UIBlueprint
from .perception import PerceptionLayer, Win32Layer, CVLayer, OCRLayer, PerceptionResult
from .blueprint import BlueprintBuilder
from .visualize import render_skeleton, render_annotated, render_grayscale, detect_elements

__all__ = [
    # Types
    "OCRWord", "LocateResult", "MonitorInfo", "WindowInfo",
    "GUIResult", "TrajectoryStep",
    # OCR
    "OCREngine", "WinOCREngine",
    # Match
    "MatchStrategy", "FuzzyMatchStrategy",
    # Screen
    "ScreenCapture", "MSSScreenCapture",
    # Window
    "WindowManager", "Win32WindowManager",
    # Actions
    "ActionExecutor", "PyAutoGUIExecutor", "ALLOWED_ACTIONS",
    # Trajectory
    "Trajectory",
    # Engine
    "DesktopEngine",
    # Prompts
    "REASONER_SYSTEM", "build_reasoner_prompt",
    # Blueprint
    "UIElement", "UIZone", "UIBlueprint",
    "PerceptionLayer", "Win32Layer", "CVLayer", "OCRLayer", "PerceptionResult",
    "BlueprintBuilder",
    # Visualization
    "render_skeleton", "render_annotated", "render_grayscale", "detect_elements",
]
