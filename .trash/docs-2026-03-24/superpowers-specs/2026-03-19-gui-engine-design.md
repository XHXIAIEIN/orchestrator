# GUI Engine Design Spec

> Give the Ministry of Works eyes and hands — a lightweight GUI automation engine for Orchestrator.

**Date**: 2026-03-19
**Status**: Reviewed (spec review passed with fixes applied)
**Inspired by**: Agent S3 (simular-ai) — borrowed architecture patterns, not code

---

## 1. Problem

Orchestrator can control anything reachable via CLI, API, or file system. But desktop GUI applications (QQ Music, Construct 3 desktop, OBS, Steam client) are a blind spot. When the owner asks "help me do X in app Y", the only option today is listing manual steps — useless for an AI butler.

## 2. Goal

Add a GUI execution engine that can:
- Capture screenshots (multi-monitor)
- Reason about what to do next (LLM)
- Locate UI elements on screen (OCR + vision grounding)
- Execute safe, whitelisted mouse/keyboard actions
- Loop until task is done or fails

First target use case: QQ Music song list extraction.

## 3. Non-Goals (YAGNI)

- Android/mobile automation
- Record-and-replay macro system
- Integration of Agent S source code (pattern-only borrowing)
- Browser automation (already covered by Playwright skill)

## 4. Architecture

```
Governor._dispatch_task()
  spec.task_type == "gui" ?
    ├─ No  → existing Agent SDK pipeline
    └─ Yes → GUIEngine.execute(instruction)

┌─────────────────────────────────────────┐
│            GUIEngine Loop               │
│                                         │
│  1. screen.capture()          [mss]     │
│  2. reasoner.decide()         [LLM]     │
│  3. grounder.locate()         [OCR→VLM] │
│  4. actions.execute()         [pyautogui]│
│  5. trajectory.append()                 │
│  6. done? → return / loop               │
└─────────────────────────────────────────┘
```

### 4.1 Generalist-Specialist Split

| Role | Model | Responsibility |
|------|-------|----------------|
| Reasoner | Claude Haiku / Qwen3 (via LLM Router) | Sees screenshot + trajectory, outputs structured action intent |
| Grounder | Tesseract OCR (precise) → UI-TARS-7B (visual fallback) | Converts natural language element ref to (x, y, monitor_id) |
| Executor | pyautogui | Executes whitelisted actions only |

### 4.2 Safety Model — Whitelist ACL, Not exec()

Agent S uses raw `exec(code)` — we don't. The Reasoner outputs structured JSON, the Executor only accepts whitelisted actions:

```python
ALLOWED_ACTIONS = {
    "click":        {"params": ["x", "y", "button"], "defaults": {"button": "left"}},
    "double_click": {"params": ["x", "y"]},
    "right_click":  {"params": ["x", "y"]},
    "type_text":    {"params": ["text"]},
    "hotkey":       {"params": ["keys"]},        # e.g. ["ctrl", "s"]
    "scroll":       {"params": ["x", "y", "clicks"]},
    "drag":         {"params": ["x1", "y1", "x2", "y2"]},
    "wait":         {"params": ["seconds"]},      # max 10s
    "screenshot":   {"params": []},               # re-capture for verification
    "done":         {"params": ["summary"]},       # task complete signal
    "fail":         {"params": ["reason"]},        # task failed signal
}
```

### 4.3 Dual-Channel Grounding

```
grounder.locate("我喜欢", screenshot, monitor_info)
  ├─ OCR path:  Tesseract word-level bbox → fuzzy match "我喜欢"
  │             → confidence >= 70 (Tesseract 0-100 scale)?
  │               → Yes: return LocateResult(x, y, confidence, monitor_id, method="ocr")
  │               → No:  fall through to vision
  │
  └─ Vision path (fallback): UI-TARS-7B
       screenshot + "我喜欢" → raw coords → scale to screen resolution
       → return LocateResult(x, y, confidence=None, monitor_id, method="vision")
       (UI-TARS has no native confidence score; treat as best-effort)
```

```python
@dataclass
class LocateResult:
    x: int              # logical pixels (DPI-adjusted, ready for pyautogui)
    y: int
    confidence: float | None   # 0-100 for OCR, None for vision
    monitor_id: int
    method: str         # "ocr" | "vision"

# locate() returns LocateResult or None.
# When None: engine.py logs "element not found", skips action, asks Reasoner to retry.
# After 3 consecutive None results for same element: mark step as failed.
```

OCR-first strategy: text labels are the most stable UI anchors. Vision grounding handles icons, images, and unlabeled elements that OCR can't match.

### 4.4 Multi-Monitor Support & Coordinate System

Using `mss` library (faster than pyautogui, native multi-monitor).

**Coordinate system clarification — two distinct coordinate spaces:**

| Space | Source | Used by |
|-------|--------|---------|
| Physical pixels | mss screenshot, Tesseract bbox, UI-TARS output | OCR grounder, Vision grounder |
| Logical pixels (DPI-scaled) | pyautogui moveTo/click | ActionExecutor |

The conversion happens in `ScreenManager.to_logical_coords()`:
- `scale_factor` is read from Win32 `ctypes.windll.shcore.GetScaleFactorForMonitor()` at init
- Formula: `logical = physical / (scale_factor / 100)`
- All `LocateResult` coordinates are **logical pixels** — ready for pyautogui with no further conversion

```python
class ScreenManager:
    def __init__(self):
        """Probe all monitors, read DPI scale factors via Win32 API."""

    def capture(self, monitor_id: int = 0) -> tuple[bytes, MonitorInfo]:
        """Capture specific monitor. 0 = all monitors stitched."""

    def capture_all(self) -> list[tuple[bytes, MonitorInfo]]:
        """Capture each monitor separately."""

    def to_logical_coords(self, phys_x: int, phys_y: int, monitor_id: int) -> tuple[int, int]:
        """Convert physical pixel coords (from screenshot) to logical coords (for pyautogui).
        Applies DPI scaling + monitor offset."""

    def to_global_coords(self, local_x: int, local_y: int, monitor_id: int) -> tuple[int, int]:
        """Convert monitor-local logical coords to global logical coords."""

@dataclass
class MonitorInfo:
    id: int
    x_offset: int      # global offset (logical)
    y_offset: int
    width: int          # physical pixels
    height: int
    width_logical: int  # logical pixels (for pyautogui)
    height_logical: int
    scale_factor: int   # Windows scale percentage (100, 125, 150, 200...)
```

### 4.5 Trajectory Context (Sliding Window)

```python
@dataclass
class TrajectoryStep:
    screenshot_thumbnail: bytes   # resized to 640px wide JPEG, ~80-120KB each
    action: dict                  # the action taken
    result: str                   # "success" / error message
    timestamp: float

class Trajectory:
    max_steps: int = 8           # matching Agent S's default
    steps: list[TrajectoryStep]

    def to_prompt_context(self) -> list[dict]:
        """Convert to LLM Router-compatible format.
        Screenshots are base64-encoded in memory (no temp files).
        Passed via LLMRouter.generate(images=[b64_str, ...])."""
```

The Reasoner sees the last N steps as context, preventing loops ("I already clicked this button 3 times").

Memory budget: 8 steps x ~120KB = ~1MB max. base64 overhead ~33% → ~1.3MB in prompt. Well within context limits.

## 5. File Structure

```
src/gui/
  __init__.py
  engine.py              # GUIEngine: main loop, orchestrates all components
  actions.py             # ActionExecutor: whitelist + pyautogui execution
  screen.py              # ScreenManager: multi-monitor capture + coord mapping
  grounder.py            # GroundingRouter: dispatches OCR → Vision fallback
  grounder_vision.py     # VisionGrounder: UI-TARS-7B via vLLM/Ollama
  grounder_ocr.py        # OCRGrounder: Tesseract word-level bbox + fuzzy match
  prompts.py             # Reasoner prompt templates
  trajectory.py          # Trajectory sliding window
```

## 6. LLM Router Extension

New route in `ROUTES` dict:

```python
"gui_reason": {
    "backend": "ollama",
    "model": "gemma3:27b",       # MUST be vision-capable (Qwen3 is text-only)
    "timeout": 45,
    "fallback": "claude",
    "fallback_model": "claude-haiku-4-5-20251001",
},
"grounding": {
    "backend": "vllm",          # new backend type
    "model": "ui-tars-1.5-7b",
    "base_url": "http://localhost:8000",  # vLLM default
    "timeout": 30,
    "grounding_width": 1920,
    "grounding_height": 1080,
},
```

UI-TARS via vLLM uses OpenAI-compatible API. New `_vllm_generate()` method in LLMRouter:
- Uses `openai` SDK (already a dependency via Agent S research) pointing at local vLLM endpoint
- Image format: base64 in OpenAI vision message format (`{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}`)
- **Fallback behavior**: grounding route has NO fallback (unlike ollama routes). If vLLM is down, `grounder_vision.py` returns `None` and engine falls back to OCR-only mode. This is acceptable — OCR handles most text-labeled elements.

New backend branch in `LLMRouter.generate()`:
```python
elif backend == "vllm":
    return self._vllm_generate(prompt, route, max_tokens, temperature, b64_images)
```

## 7. Governor Integration

### 7.1 Task Type — Explicit, Not Guessed

`task_type: "gui"` is set **upstream** (by InsightEngine when generating recommendations, or by the owner when manually creating tasks). Governor does NOT re-guess task type from keywords — that would bypass the existing scrutiny flow and create classification conflicts with `estimate_blast_radius()`.

The `spec` dict gains an optional `task_type` field: `"cli"` (default, existing behavior) or `"gui"`.

### 7.2 Blast Radius

`estimate_blast_radius()` gains a GUI-aware clause:
```python
if spec.get("task_type") == "gui":
    return "MEDIUM — GUI automation, can click wrong buttons but no data destruction"
```

### 7.3 Execution Flow — Where the Branch Goes

The GUI branch is an **early return** in `execute_task()`, inserted **after** status is set to "running" but **before** `_prepare_prompt()` and `_run_agent_session()`:

```python
def execute_task(self, task_id: int) -> dict:
    task = self.db.get_task(task_id)
    spec = task.get("spec", {})
    # ... existing setup ...

    now = datetime.now(timezone.utc).isoformat()
    self.db.update_task(task_id, status="running", started_at=now)

    # === GUI BRANCH: early return, bypasses Agent SDK entirely ===
    if spec.get("task_type") == "gui":
        return self._execute_gui_task(task_id, task, spec, now)

    # === existing CLI path continues below ===
    prompt = self._prepare_prompt(...)
    # ...
```

`_execute_gui_task()` is a new private method:
```python
def _execute_gui_task(self, task_id, task, spec, now) -> dict:
    from src.gui.engine import GUIEngine
    engine = GUIEngine(max_steps=15, trajectory_size=8)
    try:
        result = engine.execute(
            instruction=task["action"],
            target_app=spec.get("target_app", ""),
            monitor_id=spec.get("monitor_id", 0),
        )
        output = result.summary
        status = "done" if result.success else "failed"
    except Exception as e:
        output = str(e)[:2000]
        status = "failed"

    # Finalize — but skip quality review chain (no git diff to review)
    finished = datetime.now(timezone.utc).isoformat()
    self.db.update_task(task_id, status=status, output=output, finished_at=finished)
    self.db.write_log(f"GUI task #{task_id} {status}: {output[:80]}", "INFO", "governor")
    # No _dispatch_quality_review() — GUI tasks have no commits to review
    return self.db.get_task(task_id)
```

## 8. Dependencies

New pip dependencies:
- `mss` — multi-monitor screenshot (pure Python, no binary deps)
- `pyautogui` — mouse/keyboard automation
- `pytesseract` — OCR (requires system Tesseract install)
- `Pillow` — image processing (likely already installed)
- `rapidfuzz` — fuzzy string matching for OCR text → element mapping

System dependencies:
- Tesseract OCR: `winget install UB-Mannheim.TesseractOCR`
- UI-TARS-7B: deployed via vLLM (separate setup, not blocking Phase 1)

## 9. Phased Implementation

### Phase 1: Foundation (no vision model needed)
- `screen.py` — multi-monitor capture with mss
- `actions.py` — whitelist executor with pyautogui
- `grounder_ocr.py` — Tesseract OCR grounding
- `engine.py` — main loop with OCR-only grounding
- `trajectory.py` — sliding window context
- `prompts.py` — Reasoner prompts

Testable with: "open Notepad, type hello, save as test.txt"

### Phase 2: Vision Grounding
- `grounder_vision.py` — UI-TARS-7B integration
- `grounder.py` — OCR → Vision fallback router
- LLM Router `_vllm_generate()` method
- vLLM deployment script for UI-TARS

Testable with: "in QQ Music, click the heart icon" (no text label, needs vision)

### Phase 3: Governor Integration
- Task type detection in Governor
- GUI-specific scrutiny rules
- Dashboard live view (stream screenshots to dashboard websocket)
- Run-log entries for GUI tasks

## 10. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| DPI scaling makes coords wrong | ScreenManager reads per-monitor scale_factor, adjusts coords |
| Reasoner hallucinates actions | Whitelist rejects unknown actions; max_steps prevents infinite loops |
| UI-TARS gives wrong coords | OCR-first strategy avoids vision model for text elements; confidence threshold triggers retry |
| pyautogui interacts with wrong window | Pre-step: verify target app is focused (pyautogui.getActiveWindow) |
| Owner is using the computer while GUI task runs | GUI tasks should warn "I'm about to take control of mouse/keyboard" and respect a kill switch (ESC key) |

## 11. Kill Switch

Leverage pyautogui's built-in FailSafe (mouse to top-left corner raises `FailSafeException`) — do NOT disable it. Additionally, add ESC key listener via `pynput` as a secondary kill:

- `pyautogui.FAILSAFE = True` (default, keep it)
- `pynput.keyboard.Listener` in a daemon thread, sets `threading.Event` on ESC
- `GUIEngine` checks the event before every action
- If either triggers: immediately stop, mark task as "interrupted", log trajectory

`pynput` on Windows works without admin rights for keyboard hooks (it uses `SetWindowsHookEx` which doesn't require elevation for the calling process's session).

The listener daemon thread has a heartbeat: engine checks `listener.is_alive()` before each step. If the listener died, engine pauses and logs a warning rather than continuing without a safety net.

This is critical — the owner must always be able to yank back control.
