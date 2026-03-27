# desktop_use — GUI Automation Module

`src/desktop_use/` is a pluggable desktop GUI automation module. It captures screenshots, runs LLM reasoning to decide actions, grounds elements via OCR, and executes mouse/keyboard actions in a kill-switch-protected loop.

## Directory layout (14 files)

```
src/desktop_use/
├── types.py        # Data models (see Types below)
├── engine.py       # DesktopEngine — main perception-action loop (max_steps, trajectory, pluggable backends)
├── ocr.py          # OCREngine (ABC) + WinOCREngine (WinRT/winocr default)
├── match.py        # MatchStrategy (ABC) + FuzzyMatchStrategy (3-pass: exact → merged → fuzzy)
├── screen.py       # ScreenCapture (ABC) + MSSScreenCapture (physical→logical pixel conversion)
├── window.py       # WindowManager (ABC) + Win32WindowManager (foreground + background modes, WGC + PrintWindow)
├── actions.py      # ActionExecutor (ABC) + PyAutoGUIExecutor. ALLOWED_ACTIONS: click, double_click, right_click, type_text, hotkey, scroll, drag, wait, screenshot, done, fail
├── trajectory.py   # Trajectory — sliding window of (screenshot, action, result) steps for LLM context
├── prompts.py      # REASONER_SYSTEM prompt + build_reasoner_prompt() template
├── perception.py   # PerceptionLayer (ABC) + Win32Layer, CVLayer, OCRLayer → PerceptionResult
├── blueprint.py    # BlueprintBuilder — runs perception layers in fallback order → UIBlueprint (cached by window_class+size)
├── detection.py    # Re-exports from cvui: DetectionPipeline, all Stages, presets
├── visualize.py    # Re-exports from cvui: render_skeleton, render_annotated, render_grayscale, detect_elements
└── __init__.py     # Public API re-exports
```

## Types (types.py)

| Type | Fields / Purpose |
|------|-----------------|
| `OCRWord` | text, bbox, confidence |
| `LocateResult` | bbox, confidence, monitor_id, method ("ocr"\|"vision"\|...) |
| `MonitorInfo` | x, y, width/height (physical + logical), scale_factor |
| `WindowInfo` | hwnd, title, class_name, rect, process_name, pid |
| `GUIResult` | success, message, steps_taken |
| `TrajectoryStep` | screenshot (b64), action (dict), result (str) |
| `UIElement` | label, bbox, element_type, source, confidence, children |
| `UIZone` | name, bbox, elements list |
| `UIBlueprint` | window_class, size, zones list, raw_elements, timestamp |
| `PerceptionResult` | elements list, source str, confidence float |

## ABCs → Implementations

All injectable via DesktopEngine constructor:

| ABC | Implementation | Module |
|-----|---------------|--------|
| `ScreenCapture` | `MSSScreenCapture` | screen.py |
| `WindowManager` | `Win32WindowManager` | window.py |
| `OCREngine` | `WinOCREngine` | ocr.py |
| `MatchStrategy` | `FuzzyMatchStrategy` | match.py |
| `ActionExecutor` | `PyAutoGUIExecutor` | actions.py |
| `PerceptionLayer` | `Win32Layer`, `CVLayer`, `OCRLayer` | perception.py |

## Detection stages

From cvui, re-exported via detection.py:

- Image processing: `DownscaleStage`, `GrayscaleStage`, `TopHatStage`, `OtsuStage`, `DilateStage`, `ChannelAnalysisStage`
- Element detection: `ConnectedComponentStage`, `RectFilterStage`, `MergeStage`, `NestedStage`, `ClassifyStage`
- Differencing/quantization: `DiffStage`, `ListQuantizeStage`
- Model-backed: `OmniParserStage`, `GroundingDINOStage`

## Pipelines (presets from cvui)

| Pipeline | Stages | Use case |
|----------|--------|----------|
| `fast_pipeline` | Downscale → Grayscale → Otsu → CC → Filter → Merge | Quick element count |
| `standard_pipeline` | + TopHat + Classify + Nested | Normal automation |
| `full_pipeline` | + ChannelAnalysis + all filters | Thorough analysis |
| `grounding_pipeline` | GroundingDINOStage | Model-based grounding |

## Perception layers

Run in order, fast→slow:

1. `Win32Layer` — free, EnumChildWindows, Win32 API
2. `CVLayer` — runs a DetectionPipeline on screenshot
3. `OCRLayer` — winocr (WinRT OCR)

## Key patterns

- All components are ABC-based + injectable via DesktopEngine constructor
- detection.py and visualize.py are thin re-export wrappers over the `cvui` package
- Coords are normalized to logical pixels at the ScreenCapture boundary
- BlueprintBuilder caches by (window_class, width, height)
- `DesktopEngine.execute(instruction, target_app, monitor_id, process_name, window_title) → GUIResult`

## TODO / Known gaps

- No Linux/macOS backends — all implementations are Windows-only (Win32, WinRT, WGC)
- No cross-platform ScreenCapture beyond MSS (which works cross-platform but window management doesn't)
- No headless mode — requires a live desktop session
- OmniParserStage and GroundingDINOStage require external model services (not bundled)
- No retry/recovery strategy in DesktopEngine when LLM returns malformed actions
- BlueprintBuilder cache has no TTL/invalidation beyond window_class+size key
- Trajectory window size is fixed at construction — no adaptive trimming based on token budget

## Working rules

- 测试 UI 检测效果用 `/analyze-ui` skill，不要手写 mss/ctypes 截图代码
- cvui 现有 Stage 能组合就组合，不要重写已有逻辑
- `render_annotated(screenshot, rects=rects)` 或 `render_annotated(screenshot, ctx=ctx)`
- 修改 detection/visualize.py 时记住它们只是 cvui 的 re-export，真正逻辑在 cvui 包里
