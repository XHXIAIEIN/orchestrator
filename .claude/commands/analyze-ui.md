Analyze a window's UI using cvui detection pipeline.

Usage: /analyze-ui [window title or part of it]

If no argument given, list all visible windows and let user choose.

Detect the window type and choose the best pipeline:
- Games (DirectX/Vulkan) → `game_pipeline()` + WGC capture
- Normal apps → `full_pipeline()` + PrintWindow capture

Run this Python snippet:

```python
import cv2, numpy as np, subprocess
desktop = subprocess.run(['powershell', '-Command', '[Environment]::GetFolderPath("Desktop")'], capture_output=True, text=True).stdout.strip()

from cvui.window import Win32WindowManager
from cvui.stages import full_pipeline, game_pipeline
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

# Auto-select pipeline: dark + large = likely game
is_game = median < 60 and w * h > 1920 * 1080
pipeline = game_pipeline() if is_game else full_pipeline()
ctx = pipeline.run(img)

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

# Save annotated
render_annotated(png, ctx=ctx).save(f'{desktop}/ui_analysis.png')
print(f'\nAnnotated: {desktop}/ui_analysis.png')
print(f'Pipeline: {"game" if is_game else "full"}, {len(ctx.rects)} elements, {len(ctx.zones)} zones')
```

Display:
1. The LLM prompt output (layout, regions, elements with OCR labels)
2. The path to the annotated screenshot
3. Whether game or standard pipeline was used
