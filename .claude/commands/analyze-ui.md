Analyze a window's UI using cvui detection pipeline.

Usage: /analyze-ui [window title or part of it]

If no argument given, list all visible windows and let user choose.

Run this Python snippet to detect and describe UI elements:

```python
import cv2, numpy as np
from cvui.window import Win32WindowManager
from cvui.stages import full_pipeline
from cvui.visualize import render_annotated

# Find and capture window
wm = Win32WindowManager()
wm.lock(title_contains='$ARGUMENTS')
png = wm.capture_window()
img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)

# Detect
ctx = full_pipeline().run(img)

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
```

Also save annotated image:
```python
import subprocess
desktop = subprocess.run(['powershell', '-Command', '[Environment]::GetFolderPath("Desktop")'], capture_output=True, text=True).stdout.strip()
render_annotated(png, ctx=ctx).save(f'{desktop}/ui_analysis.png')
print(f'Annotated image: {desktop}/ui_analysis.png')
```

Display:
1. The LLM prompt output (layout, regions, elements with OCR labels)
2. The path to the annotated screenshot
