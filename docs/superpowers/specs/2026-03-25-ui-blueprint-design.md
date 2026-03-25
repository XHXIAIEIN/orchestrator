# UI Blueprint — 桌面自动化蓝图系统

> 状态：V1 已实现，V2 检测流水线已实现，持续迭代中

## 核心思路

在 RPA 操作前，先对目标窗口做一次结构分析，生成 UIBlueprint。后续操作查表走 RPA，不用每步都 OCR + LLM 推理。

```
传统流程（每步 ~2-5s）：
  截图 → OCR → LLM推理 → 操作 → 截图 → OCR → LLM推理 → 操作 → ...

蓝图流程：
  [一次性] 结构化数据优先 → CV 兜底 → 生成蓝图（缓存）
  [后续 ~0.02s/步] 查蓝图 → 直接操作
```

## 第一原则：结构化数据优先，CV 是最后手段

**大部分应用不需要截图、不需要 CV、不需要 OCR。** 只有没有控件树的自绘应用才走 CV 流水线。

```
判断窗口类型 → 选择最优路径

浏览器页面？
  → Chrome DevTools Protocol → DOM 树 / Accessibility Tree
  → 0ms，100% 精确，零 CV
  → 元素类型、层级、文本、可交互性、boundingBox 全部结构化数据

标准 Win32/WPF/WinForms 控件？
  → UI Automation 无障碍树 / EnumChildWindows
  → 0-4ms，精确
  → 控件类型、名称、状态、坐标全部现成

自绘应用（Qt/DirectX/自定义引擎）？
  → 无控件树，必须走 CV 流水线
  → 4-20ms
  → 微信、游戏、某些 Electron 应用
```

## 感知层级体系

```
Layer -1 (0ms): DOM / Accessibility Tree — 浏览器
  Chrome DevTools Protocol，--force-renderer-accessibility
  完美结构化：role, name, boundingBox, value, disabled...
  覆盖：所有网页、PWA、WebView

Layer 0 (0-4ms): Win32 / UI Automation — 标准桌面应用
  EnumChildWindows + UIA 无障碍树
  精确控件树：类名、标题、坐标、状态
  覆盖：文件管理器(614子窗口)、Office、设置、记事本...

Layer 1 (4-20ms): CV 检测流水线 — 自绘应用（兜底）
  TopHat + Otsu + 膨胀 + 连通域 + 嵌套检测 + 分类
  可插拔 Stage 架构，quality_score 提前退出
  覆盖：微信(Qt自绘)、游戏、自定义渲染引擎

Layer 2 (100ms): WinRT OCR — 文字补充
  仅对 Layer 1 识别出的动态区做局部裁剪 OCR
  不做全窗口 OCR

Layer 3 (500ms+): ML 模型 — 语义理解（可选）
  OmniParser: YOLO 图标检测 + Florence 语义描述
  Grounding DINO: 自然语言定位（"找到搜索框"）
  需要 GPU，按需启用
```

### 各层覆盖范围

| 应用类型 | 感知路径 | 耗时 | 精度 |
|---------|---------|------|------|
| Chrome / Edge 网页 | CDP → DOM | 0ms | 完美 |
| Electron (有 a11y) | CDP 或 UIA | 0ms | 完美 |
| 文件资源管理器 | UIA (614 控件) | 3.5ms | 精确 |
| Office / 记事本 | UIA + WM_GETTEXT | 0ms | 精确 |
| WPF / WinForms | UIA | 0ms | 精确 |
| **微信 (Qt 自绘)** | **CV 流水线** | **4-20ms** | **良好** |
| **游戏 (DirectX)** | **CV 流水线** | **4-20ms** | **中等** |
| 复杂未知界面 | CV + OmniParser | 500ms+ | 好 |

### 关键认知

- Layer -1 和 Layer 0 覆盖 **90%+ 的日常应用**
- CV 流水线（Layer 1-3）只在 **~10% 的自绘应用** 上触发
- 投入大量精力优化 CV 检测的 ROI 有限，但对微信这种高频应用仍然重要

## CV 检测流水线（Layer 1 详细设计）

### 可插拔 Stage 架构

```python
DetectionContext  # 共享状态（img, gray, binary, rects, quality_score）
DetectionStage    # ABC（process + should_continue）
DetectionPipeline # 编排器（按序执行，提前退出）
```

### 已实现的 13 个 Stage

| Stage | 类型 | 功能 |
|-------|------|------|
| GrayscaleStage | 纯 CV | 灰度 + 自适应 gamma |
| TopHatStage | 纯 CV | 去不均匀背景（深色/浅色主题全适配） |
| OtsuStage | 纯 CV | 自动阈值（零参数） |
| DilateStage | 纯 CV | 方向膨胀连接组件 |
| ConnectedComponentStage | 纯 CV | 连通域 + quality_score + 提前退出 |
| RectFilterStage | 纯 CV | 过滤小框 |
| MergeStage | 纯 CV | 合并重叠框 |
| NestedStage | 纯 CV | 递归子元素检测 |
| ClassifyStage | 纯 CV | icon/text/image/container 启发式分类 |
| ChannelAnalysisStage | 纯 CV | RGB 通道语义（选中/未读/链接） |
| DiffStage | 纯 CV | 增量帧对比 |
| OmniParserStage | 可选 ML | YOLO 图标检测 + Florence 描述 |
| GroundingDINOStage | 可选 ML | 自然语言零样本定位 |

### 预设流水线

| 预设 | Stages | 速度 | 用途 |
|------|--------|------|------|
| `fast_pipeline()` | 5 | ~4ms | 只要框 |
| `standard_pipeline()` | 7 | ~5ms | 框 + 过滤合并 |
| `full_pipeline()` | 10+ | ~20ms | 完整分析 + 可选 ML |
| `grounding_pipeline(query)` | 1 | ~2s | 自然语言定位单个元素 |

### 提前退出

ConnectedComponentStage 计算 quality_score（覆盖率 × 碎片度），超过 0.8 就停，后续 Stage 全跳过。

## 骨架区 vs 动态区

| 类型 | 特征 | 操作方式 |
|------|------|----------|
| 骨架区（Skeleton） | 位置固定（搜索框、导航图标、输入框、工具栏） | 缓存坐标 → Win32 直操，0 延迟 |
| 动态区（Dynamic） | 内容变化但边界固定（联系人列表、聊天消息、通知角标） | 裁剪该区域 → 局部 OCR（比全窗口快 5-10x） |

## 数据结构

```python
@dataclass
class UIElement:
    name: str
    rect: tuple[int,int,int,int]  # (left, top, right, bottom)
    element_type: str              # "button" | "input" | "icon" | "label" | "text"
    action: str                    # "click" | "click+type" | "display"
    text: str
    source: str                    # "dom" | "uia" | "win32" | "cv" | "ocr" | "omniparser"
    confidence: float

@dataclass
class UIBlueprint:
    window_class: str
    window_size: tuple[int, int]
    elements: list[UIElement]
    zones: list[UIZone]
    perception_layers: list[str]   # 实际走了哪条路 ["dom"] or ["win32"] or ["win32","cv","ocr"]
    created_at: float
```

## 文件结构（已实现）

| 文件 | 职责 |
|------|------|
| `types.py` | UIElement, UIZone, UIBlueprint 数据模型 |
| `perception.py` | PerceptionLayer ABC + Win32Layer, CVLayer, OCRLayer |
| `detection.py` | DetectionStage ABC + 13 个 Stage + DetectionPipeline + 预设 |
| `blueprint.py` | BlueprintBuilder — 编排感知层、缓存 |
| `visualize.py` | render_skeleton / render_annotated / render_grayscale / detect_elements |
| `engine.py` | DesktopEngine.analyze() + read_zone() |

## 相关研究

### 开源项目

| 项目 | 核心方法 | 我们借鉴了什么 |
|------|---------|------------|
| UIED | 纯 CV top-down coarse-to-fine | TopHat + 嵌套递归检测 |
| OmniParser | YOLO + Florence | OmniParserStage（可选 ML） |
| STEVE-R1 | Qwen2VL-7B + R1 CoT | 复杂多步推理，留作扩展 |
| Windows-Use/MCP | UI Automation 无障碍树 | Layer 0 的无障碍树方案 |
| Meituan vision-ui | DBNet + CRNN | OCR 流水线参考 |

### 学术文献

| 论文 | 关键发现 |
|------|---------|
| UIED (ESEC/FSE 2020) | 混合 CV+DL 优于纯 DL，嵌套检测是关键 |
| REMAUI (ASE 2015) | CV 边缘 + OCR 互补融合 |
| Grounding DINO (ECCV 2023) | 自然语言零样本定位，COCO 52.5 AP |
| Rico (UIST 2017) | 66k UI 界面，最大移动 UI 数据集 |
| ScreenAI (Google 2024) | DETR + VLM 做 UI 元素检测 |

### CV 技术参考

| 技术 | 用在哪里 |
|------|---------|
| Top-Hat 变换 | GrayscaleStage — 去不均匀背景，比 adaptive threshold 快 10x |
| Otsu 自动阈值 | OtsuStage — 零参数，替代手动调 C 值 |
| 形态学梯度 | 备选方案（膨胀-腐蚀 = 边框线） |
| 暗通道先验 | 探索过，适合视觉输出但不适合检测前处理 |
| RGB 通道差值 | ChannelAnalysisStage — G-R=选中, R-B=未读, B-R=链接 |
| 自适应 gamma | GrayscaleStage — `gamma = log(100/255) / log(median/255)` |
