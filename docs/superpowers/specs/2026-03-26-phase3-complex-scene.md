# Phase 3: 复杂场景适配 — 游戏/动态应用 UI 检测

> 状态：设计中

## 问题定义

Phase 1-2 在微信（简单 UI）上效果良好，但面对游戏和复杂应用时会失效：

| 挑战 | 微信 | 游戏/复杂应用 |
|------|------|------------|
| 颜色 | 6 色调色板 | 上千种，渐变、粒子、光照 |
| 布局 | 固定三列 | 动态 HUD、弹窗、叠层、可拖拽面板 |
| 变化速度 | 秒级（新消息） | 帧级（16ms，60fps） |
| 前景/背景 | UI 就是全部 | UI 叠在动态 3D 场景上 |
| 层级 | 2-3 层 | 5-10 层（场景 → HUD → 菜单 → 对话框 → toast） |
| 文字 | 标准字体 | 艺术字、描边字、阴影字、像素字 |
| 交互 | 点击、打字 | 拖拽、长按、连击、手势、实时反馈 |

### 核心难点

1. **UI 层分离** — HUD 叠在 3D 场景上，TopHat 无法区分"血条"和"红色怪物"
2. **高速变化** — 每帧都不同，增量 DiffStage 永远触发全量重建
3. **色彩复杂** — Otsu 二值化在复杂背景上完全失效
4. **动态布局** — 技能冷却、血量变化、弹窗弹出，骨架不固定

## 技术方案

### 方案 1: 多帧累积 UI 层分离

**原理：游戏场景帧帧在变，但 HUD 骨架位置不动。**

```
采集 N 帧（N=10-30）
  ↓
逐像素计算方差
  ↓
方差低的区域 = HUD 骨架（不动的 UI 元素）
方差高的区域 = 游戏场景（动态内容）
  ↓
只对低方差区域做元素检测
```

```python
class MultiFrameAccumulatorStage(DetectionStage):
    """Accumulate N frames, extract static regions (HUD) vs dynamic (scene)."""

    def __init__(self, n_frames: int = 10):
        self.buffer: list[np.ndarray] = []
        self.n_frames = n_frames

    def add_frame(self, frame: np.ndarray):
        self.buffer.append(frame)
        if len(self.buffer) > self.n_frames:
            self.buffer.pop(0)

    def process(self, ctx):
        if len(self.buffer) < 3:
            return ctx  # not enough frames yet

        # Stack frames and compute per-pixel variance
        stack = np.stack(self.buffer, axis=0).astype(np.float32)
        variance = np.var(stack, axis=0).mean(axis=2)  # (H, W)

        # Low variance = static UI, high variance = dynamic scene
        # Threshold: pixels with variance < 50 are "static"
        static_mask = (variance < 50).astype(np.uint8) * 255
        ctx.binary = static_mask
        return ctx
```

**实测参考：** Papers, Please 项目验证过，10 帧足够分离 HUD。

**性能：** 累积不增加延迟 — 每帧只需存一份灰度图（~1MB），方差计算 ~5ms。

### 方案 2: 颜色量化 + 调色板分析

**原理：UI 用设计师选的有限调色板，游戏场景用自然渲染的连续色彩。量化后 UI 颜色保持清晰，场景颜色变成噪声。**

```
截图 → 八叉树量化（256色 → 8色）
  ↓
提取调色板 → 识别 UI 色 vs 场景色
  ↓
UI 色区域做元素检测
场景色区域标记为动态内容
```

#### 量化器选择

| 量化器 | 速度 | 质量 | 适合 |
|--------|------|------|------|
| K-means | ~100ms | 最优 | 离线分析 |
| **八叉树 (Octree)** | **~5ms** | 好 | **实时处理首选** |
| 中位数切割 (Median Cut) | ~10ms | 好 | 均匀色彩分布 |
| 吴小林 (Wu) | ~8ms | 最优之一 | 最小化量化误差 |

**推荐八叉树** — PIL 内置 `img.quantize(colors=8, method=Image.Quantize.FASTOCTREE)` 直接可用，不需要额外实现。

```python
class ColorQuantizeStage(DetectionStage):
    """Quantize to limited palette, separate UI colors from scene colors."""

    def __init__(self, n_colors: int = 8, method: str = "octree"):
        self.n_colors = n_colors
        self.method = method

    def process(self, ctx):
        from PIL import Image
        pil = Image.fromarray(ctx.img[:, :, ::-1])  # BGR → RGB

        # Quantize
        if self.method == "octree":
            quantized = pil.quantize(colors=self.n_colors,
                                      method=Image.Quantize.FASTOCTREE)
        elif self.method == "median_cut":
            quantized = pil.quantize(colors=self.n_colors,
                                      method=Image.Quantize.MEDIANCUT)
        else:
            quantized = pil.quantize(colors=self.n_colors)

        # Extract palette
        palette = quantized.getpalette()[:self.n_colors * 3]
        colors = [(palette[i], palette[i+1], palette[i+2])
                  for i in range(0, len(palette), 3)]

        # Store palette info for classification
        ctx.ui_states["palette"] = colors

        # Convert quantized back to array for further processing
        q_array = np.array(quantized.convert("RGB"))[:, :, ::-1]  # RGB → BGR
        ctx.img = q_array
        return ctx
```

### 方案 3: 多色彩空间交叉分析

**原理：不同色彩空间突出不同信息。**

| 色彩空间 | 强项 | UI 检测用途 |
|---------|------|-----------|
| **HSV** | 色相/饱和度分离 | 按颜色分类 UI 元素（红=警告，绿=确认） |
| **LAB** | 感知均匀亮度 | 比灰度更准的亮度对比（L 通道） |
| **YCrCb** | 亮度/色度分离 | 分离文字（亮度通道）和彩色背景 |
| **HSL** | 亮度独立 | 浅色/深色主题自适应 |

```python
class MultiColorSpaceStage(DetectionStage):
    """Analyze image in multiple color spaces for richer feature extraction."""

    def process(self, ctx):
        import cv2
        # LAB — L channel is perceptually uniform brightness
        lab = cv2.cvtColor(ctx.img, cv2.COLOR_BGR2LAB)
        l_channel = lab[:, :, 0]

        # HSV — S channel highlights colorful elements (icons, badges)
        hsv = cv2.cvtColor(ctx.img, cv2.COLOR_BGR2HSV)
        s_channel = hsv[:, :, 1]

        # Use L channel as gray (better than simple grayscale for UI)
        ctx.gray = l_channel

        # Store saturation for later classification
        ctx.ui_states["saturation_map"] = s_channel
        return ctx
```

**LAB 的 L 通道比 RGB 灰度更好** — 因为它是感知均匀的，人眼觉得同样亮的东西 L 值相同。RGB 灰度 (`0.299R + 0.587G + 0.114B`) 对绿色过度加权。

### 方案 4: 抖动/渐变检测

**原理：渐变背景和纯色 UI 面板的像素分布不同。**

- 纯色面板：像素值几乎完全相同
- 渐变背景：像素值沿某个方向线性变化
- 场景噪声：像素值随机分布

```python
class GradientDetectorStage(DetectionStage):
    """Detect and mask gradient regions (game backgrounds, not UI)."""

    def process(self, ctx):
        import cv2
        if ctx.gray is None:
            return ctx

        # Compute local variance in small patches
        kernel = np.ones((15, 15), np.float32) / 225
        mean = cv2.filter2D(ctx.gray.astype(np.float32), -1, kernel)
        sq_mean = cv2.filter2D((ctx.gray.astype(np.float32))**2, -1, kernel)
        local_var = sq_mean - mean**2

        # High local variance = texture/scene, low = solid UI panel
        # Medium = gradient (transitions smoothly)
        # Mask out high-variance regions (not UI)
        scene_mask = (local_var > 500).astype(np.uint8) * 255
        ctx.ui_states["scene_mask"] = scene_mask

        # Apply: zero out scene regions in binary
        if ctx.binary is not None:
            ctx.binary[scene_mask > 0] = 0
        return ctx
```

### 方案 5: 实时 HUD 追踪（而非逐帧全量检测）

**原理：第一帧全量检测，后续帧只追踪已知元素的位移/变化。**

```
Frame 1: 全量检测 → 蓝图（血条在 (10,20)，技能栏在 (100,500)...）
Frame 2-N: 对每个已知元素：
  → 模板匹配（在小范围内搜索）→ 更新坐标
  → 如果找不到 → 标记为消失
  → 如果有新的大面积变化 → 局部重检测
```

```python
class TrackingStage(DetectionStage):
    """Track known elements across frames instead of re-detecting."""

    def __init__(self, prev_rects: list = None, search_radius: int = 30):
        self.prev_rects = prev_rects or []
        self.search_radius = search_radius

    def process(self, ctx):
        import cv2
        if not self.prev_rects or ctx.gray is None:
            return ctx  # first frame, need full detection

        tracked = []
        for pr in self.prev_rects:
            x1, y1, x2, y2 = pr
            # Extract template from previous location
            # Search in expanded region of current frame
            sx1 = max(0, x1 - self.search_radius)
            sy1 = max(0, y1 - self.search_radius)
            sx2 = min(ctx.width, x2 + self.search_radius)
            sy2 = min(ctx.height, y2 + self.search_radius)

            search_region = ctx.gray[sy1:sy2, sx1:sx2]
            template = ctx.gray[y1:y2, x1:x2]  # use current frame's content at old location
            # ... template matching ...

        ctx.rects = tracked
        return ctx
```

## 分层策略（更新）

```
Phase 1-2 (已实现):
  Layer -1: DOM        → 浏览器
  Layer  0: Win32/UIA  → 标准应用
  Layer  1: CV 流水线   → 自绘应用（微信）
  Layer  2: OCR        → 文字补充
  Layer  3: ML 模型    → 语义理解

Phase 3 (本期):
  Layer  1.1: 多帧累积     → 从动态场景分离 HUD 层
  Layer  1.2: 颜色量化     → 调色板分析 + UI 色/场景色分离
  Layer  1.3: 多色彩空间   → LAB 亮度 + HSV 饱和度交叉
  Layer  1.4: 渐变检测     → 过滤游戏背景渐变
  Layer  1.5: 元素追踪     → 帧间追踪替代逐帧重检测
```

## 适用场景矩阵

| 场景 | 当前方案 | Phase 3 补充 |
|------|---------|------------|
| 微信、设置 | TopHat + Otsu ✓ | 不需要 |
| 游戏 HUD | 失败 | 多帧累积 + 颜色量化 |
| 游戏菜单 | 部分成功 | 颜色量化 + 渐变检测 |
| 视频播放器 | DiffStage 触发全量 | 多帧累积（控制栏不动） |
| CAD/PS 等工具 | TopHat 部分成功 | 多色彩空间 + 颜色量化 |
| 直播弹幕 | 失败 | 多帧累积（弹幕动，UI 不动） |
| 游戏对话框 | 部分成功 | 颜色量化（对话框颜色固定） |

## Stage 实现清单

| Stage | 核心算法 | 复杂度 | 依赖 |
|-------|---------|--------|------|
| MultiFrameAccumulatorStage | 多帧方差 | 中 | numpy |
| ColorQuantizeStage | 八叉树/中位数切割量化 | 低 | PIL |
| MultiColorSpaceStage | LAB + HSV 多空间 | 低 | opencv |
| GradientDetectorStage | 局部方差渐变检测 | 低 | opencv |
| TrackingStage | 模板匹配帧间追踪 | 中 | opencv |

## 先例

- **Papers, Please game_agent** (`D:\Steam\steamapps\common\PapersPlease\game_agent\`)
  - 验证了多帧检测 + OmniParser 在游戏场景的可行性
  - `core/screen.py` — 截图 + 区域裁剪
  - `core/ui_knowledge.py` — HUD 位置缓存 + 场景识别
  - `core/omniparser_client.py` — 服务器/本地模式 YOLO 检测

- **imgcook (阿里)** — Puppeteer 合成 UI 截图作为训练数据，可用于游戏 HUD 检测模型训练

- **UIED** — top-down coarse-to-fine 策略在复杂背景上的表现优于 bottom-up

## 性能预算

| 场景 | 目标延迟 | 策略 |
|------|---------|------|
| 游戏 60fps 实时 | <16ms/帧 | 多帧累积 + 追踪（不逐帧重检测） |
| 游戏菜单/暂停 | <50ms | 全量检测（画面静止） |
| 动态应用实时 | <33ms/帧 | 缩放 + 快速流水线 |
| 离线分析 | 无限制 | 全量 + ML 模型 |

## 预设流水线扩展

```python
def game_pipeline() -> DetectionPipeline:
    """For games: multi-frame accumulate → quantize → detect → track."""
    return DetectionPipeline([
        MultiFrameAccumulatorStage(n_frames=10),
        ColorQuantizeStage(n_colors=8),
        GrayscaleStage(),
        TopHatStage(),
        OtsuStage(),
        DilateStage(),
        ConnectedComponentStage(),
        RectFilterStage(),
        MergeStage(),
        ClassifyStage(),
    ])

def realtime_pipeline(prev_rects=None) -> DetectionPipeline:
    """For real-time: track known elements, minimal re-detection."""
    return DetectionPipeline([
        DiffStage(),
        TrackingStage(prev_rects=prev_rects),
    ])
```
