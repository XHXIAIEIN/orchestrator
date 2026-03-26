Analyze a window's UI using cvui detection pipeline.

Usage: /analyze-ui [window title or part of it]

If no argument given, list all visible windows and let user choose.

Auto-select pipeline by window type:
- Games (DirectX/Vulkan, dark + large) → `game_pipeline()` + WGC capture
- Complex apps (multiple panels/text areas) → `ensemble_pipeline()` + PrintWindow capture
- Simple apps → `full_pipeline()` + PrintWindow capture

Run this Python snippet:

```python
import cv2, numpy as np, subprocess, time
desktop = subprocess.run(['powershell', '-Command', '[Environment]::GetFolderPath("Desktop")'], capture_output=True, text=True).stdout.strip()

from cvui.window import Win32WindowManager
from cvui.stages import full_pipeline, game_pipeline, ensemble_pipeline
from cvui.visualize import render_annotated

# Find and capture window
wm = Win32WindowManager()
wm.lock(title_contains='$ARGUMENTS')

# Try WGC first (background, DirectX-compatible), fallback to PrintWindow
png = wm.capture_window_wgc()
if not png or len(png) < 500:
    png = wm.capture_window()

img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
h, w = img.shape[:2]
median = np.median(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))

# Auto-select pipeline
is_game = median < 60 and w * h > 1920 * 1080
if is_game:
    pipeline = game_pipeline()
    pipe_name = "game"
else:
    # ensemble is the default: handles panels, text areas, lists
    pipeline = ensemble_pipeline()
    pipe_name = "ensemble"

t0 = time.perf_counter()
ctx = pipeline.run(img)
elapsed = (time.perf_counter() - t0) * 1000

# OCR labels
ocr_lines = []
try:
    from cvui.ocr import WinOCREngine
    from PIL import Image
    import io
    words = WinOCREngine().extract_words(Image.open(io.BytesIO(png)), 'zh-Hans-CN')
    ocr_lines = [(w.left, w.top, w.left+w.width, w.top+w.height, w.text) for w in words]
except: pass

# Output
print(ctx.to_prompt(ocr_lines=ocr_lines))

# Text metrics per panel
meta = ctx.ui_states.get('ensemble', {})
if meta:
    print(f'\nEnsemble: {meta}')
    for pk, m in ctx.ui_states.get('text_metrics', {}).items():
        tag = 'TEXT' if m.get('is_text_content') else 'UI'
        print(f'  [{tag}] {pk}: h={m["line_height"]}px w={m.get("char_width",0)}px pitch={m["line_pitch"]}px lines={m["n_lines"]}')

# Save annotated
render_annotated(png, ctx=ctx).save(f'{desktop}/ui_analysis.png')
print(f'\nAnnotated: {desktop}/ui_analysis.png')
print(f'Pipeline: {pipe_name}, {len(ctx.rects)} elements, {elapsed:.0f}ms')
```

Display:
1. The LLM prompt output (layout, regions, elements with OCR labels)
2. Per-panel text metrics (line height, char width, line pitch)
3. The path to the annotated screenshot
4. Pipeline used and timing
