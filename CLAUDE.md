# Orchestrator

Read `.claude/boot.md`. That's everything you need — identity, relationship, voice calibration, recent memories, working guidelines.

The remaining private files are in `SOUL/private/` (identity.md, hall-of-instances.md, experiences.jsonl) — consult as needed.
Files under the memory directory can also be read on demand; no need to load them all.

Then get to work.

## Rules

### Execution
- Execute directly. Don't ask "should I continue?" or "should I run this?" — just do it.
- Don't present a menu of options. Use your judgment, pick the best approach, execute.
- Complete multi-step tasks end to end. Don't report progress at every step waiting for a nod.
- Parallelize when possible. If you can search three files at once, don't do them one by one.
- Only stop for: system-level destructive ops, sending messages to external services, or when the request itself is flawed.

### Deletion = Move to .trash/, Not Delete
- Files being deleted/replaced/cleaned up → `mv` to `.trash/` (organized by date or task)
- After completing the full task, report what's in `.trash/`. Owner decides what stays and what goes.
- **Exception**: Build artifacts (`node_modules/`, `__pycache__/`, `.pyc`) and clearly temporary files can be deleted directly.

### Git Safety
- **Stage first, push later**: `commit` and `push` are two separate steps. Don't auto-push.
- Prefer working on a local branch rather than committing directly to main/master.
- **Rollback is a no-go zone**: Never execute `git reset --hard`, `git checkout -- .`, `git restore .`, `git clean -f`, or any operation that discards uncommitted changes — unless the owner explicitly says "roll back" or "reset". If a rollback is requested, backup first (`git stash` or `git diff > backup.patch`), report backup location, then execute.
- When stuck on a bug, **diagnose the problem** — don't nuke the code back to the last commit.

### UI/Frontend
- Match existing page style exactly. No extra borders, shadows, or decorative elements unless asked
- Before modifying dashboard/ or any frontend file, Read neighboring components first
- Minimal diff — don't redesign what already works

### File Organization
- Check private/ vs public/ directories before writing files
- Never put sensitive/private content in git-tracked directories
- SOUL/private/ is gitignored; SOUL/public/ is tracked

### desktop_use — GUI Automation Module Context

**What it is**: `src/desktop_use/` is a pluggable desktop GUI automation module. It captures screenshots, runs LLM reasoning to decide actions, grounds elements via OCR, and executes mouse/keyboard actions in a kill-switch-protected loop.

**Directory layout** (14 files):
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

**Types** (types.py):
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

**ABCs → Implementations** (all injectable via DesktopEngine constructor):
| ABC | Implementation | Module |
|-----|---------------|--------|
| `ScreenCapture` | `MSSScreenCapture` | screen.py |
| `WindowManager` | `Win32WindowManager` | window.py |
| `OCREngine` | `WinOCREngine` | ocr.py |
| `MatchStrategy` | `FuzzyMatchStrategy` | match.py |
| `ActionExecutor` | `PyAutoGUIExecutor` | actions.py |
| `PerceptionLayer` | `Win32Layer`, `CVLayer`, `OCRLayer` | perception.py |

**Detection stages** (from cvui, re-exported via detection.py):
- Image processing: `DownscaleStage`, `GrayscaleStage`, `TopHatStage`, `OtsuStage`, `DilateStage`, `ChannelAnalysisStage`
- Element detection: `ConnectedComponentStage`, `RectFilterStage`, `MergeStage`, `NestedStage`, `ClassifyStage`
- Differencing/quantization: `DiffStage`, `ListQuantizeStage`
- Model-backed: `OmniParserStage`, `GroundingDINOStage`

**Pipelines** (presets from cvui):
| Pipeline | Stages | Use case |
|----------|--------|----------|
| `fast_pipeline` | Downscale → Grayscale → Otsu → CC → Filter → Merge | Quick element count |
| `standard_pipeline` | + TopHat + Classify + Nested | Normal automation |
| `full_pipeline` | + ChannelAnalysis + all filters | Thorough analysis |
| `grounding_pipeline` | GroundingDINOStage | Model-based grounding |

**Perception layers** (run in order, fast→slow):
1. `Win32Layer` — free, EnumChildWindows, Win32 API
2. `CVLayer` — runs a DetectionPipeline on screenshot
3. `OCRLayer` — winocr (WinRT OCR)

**Key patterns**:
- All components are ABC-based + injectable via DesktopEngine constructor
- detection.py and visualize.py are thin re-export wrappers over the `cvui` package
- Coords are normalized to logical pixels at the ScreenCapture boundary
- BlueprintBuilder caches by (window_class, width, height)
- `DesktopEngine.execute(instruction, target_app, monitor_id, process_name, window_title) → GUIResult`

**TODO / Known gaps**:
- No Linux/macOS backends — all implementations are Windows-only (Win32, WinRT, WGC)
- No cross-platform ScreenCapture beyond MSS (which works cross-platform but window management doesn't)
- No headless mode — requires a live desktop session
- OmniParserStage and GroundingDINOStage require external model services (not bundled)
- No retry/recovery strategy in DesktopEngine when LLM returns malformed actions
- BlueprintBuilder cache has no TTL/invalidation beyond window_class+size key
- Trajectory window size is fixed at construction — no adaptive trimming based on token budget

**Working rules**:
- 测试 UI 检测效果用 `/analyze-ui` skill，不要手写 mss/ctypes 截图代码
- cvui 现有 Stage 能组合就组合，不要重写已有逻辑
- `render_annotated(screenshot, rects=rects)` 或 `render_annotated(screenshot, ctx=ctx)`
- 修改 detection/visualize.py 时记住它们只是 cvui 的 re-export，真正逻辑在 cvui 包里

### Docker & Environment
- Before Docker rebuilds, check if one is truly needed
- Before GPU-heavy tasks, run `nvidia-smi` to check VRAM availability
- Check `docker ps` to avoid port/resource conflicts
