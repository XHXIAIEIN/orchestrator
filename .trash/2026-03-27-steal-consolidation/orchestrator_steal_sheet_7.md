---
name: orchestrator-steal-sheet-7
description: 2026-03-26 第七轮偷师：CV+VLM UI检测 — labelU/UIED/OmniParser/Gemini/PaddleX/NVIDIA TAO/NExT-Chat(pix2emb)，cvui 演进路线
type: project
---

## 主题

**cvui 从纯 CV 到 CV+VLM 混合检测的演进路线**

背景：`game_pipeline` 在 Disco Elysium 设置页上暴露了纯 CV 的天花板——SaturationFilter 对低饱和场景（灰色天空/建筑）无能为力，参数怎么调都有残留误检。需要引入语义级理解来做"第一刀"区域定位。

## 来源清单

| # | 项目 | Stars | 核心价值 |
|---|------|-------|---------|
| 1 | **labelU** (OpenDataLab) | 1.5K | 多模态标注平台，格式转换器 + 预标注工作流 |
| 2 | **UIED** (MulongXie) | 1K+ | CV+CNN 混合 UI 检测，学术论文级流水线 |
| 3 | **OmniParser v2** (Microsoft) | 10K+ | YOLO 检测 + Florence-2 captioning + PaddleOCR 三件套 |
| 4 | **Gemini Image Understanding** (Google) | — | VLM 原生 bbox [y,x,y,x] 0-1000 + 分割 mask |
| 5 | **PaddleX PP-ShiTuV2** (Baidu) | — | 检测→特征提取→向量检索 三级联管道 |
| 6 | **NVIDIA TAO + Grounding DINO** | — | 商用许可 Swin-Tiny 骨干，ODVG 格式微调 |
| 7 | **NExT-Chat** (清华+NUS) | — | pix2emb 范式：LMM 输出位置 embedding → 解码为 bbox/mask |

## 偷到的模式

### P0 — 立即可偷到 cvui

#### 1. VLM Zone Stage（首刀语义分离）← Gemini + OmniParser 思路

**问题**：SaturationFilterStage 按像素统计分离 UI/场景，灰色天空和灰色面板像素层面一样。
**偷法**：新建 `VLMZoneStage`，插到 pipeline 最前面：

```
截图 → VLM("哪些区域是 UI 面板？") → zones[] → CV pipeline 只在 zone 内检测
```

- Gemini 的 bbox 格式：`[ymin, xmin, ymax, xmax]` 归一化到 0-1000，需 `÷1000×实际尺寸`
- OmniParser 的做法：YOLO 检测交互元素 → Florence-2 生成描述 → PaddleOCR 读文字
- **cvui 偷法**：只偷第一步（区域定位），不用 VLM 做全量检测。首次 ~200ms，缓存命中 0ms
- `BlueprintBuilder` 已按 `(window_class, width, height)` 缓存，天然适配

#### 2. 混合检测三件套（UIED 架构）← UIED 论文

UIED 的三阶段架构和 cvui 高度同构：

| UIED | cvui 对应 | 差异 |
|------|-----------|------|
| Text Detection (EAST/OCR) | OCRLayer | cvui 用 WinOCR |
| Graphic Detection (CV contour) | CV Pipeline (TopHat→CC) | cvui 更精细（21 Stage） |
| CNN Classification | ClassifyStage | cvui 用启发式，UIED 用训练的 CNN |

**偷法**：ClassifyStage 的启发式分类（aspect ratio + area）太粗糙。可以训练一个轻量 CNN 分类器替代：
- 从 cvui 的 RectFilter 后裁出每个 element patch
- 送入小型分类网络（MobileNetV3-Small, ~2M params, <5ms）
- 分类：button / text / slider / icon / checkbox / dropdown / image

#### 3. 检测→特征→检索 三级联管道 ← PaddleX PP-ShiTuV2

PP-ShiTuV2 的架构：`Detection → Feature Extraction → FAISS Retrieval`

**偷法→ cvui BlueprintBuilder 缓存升级**：
- 当前缓存 key = `(window_class, width, height)`，精确匹配
- 偷 PP-ShiTuV2 的向量检索思路：对 UI 截图做特征提取，FAISS 近似匹配
- 同类窗口（不同分辨率/不同 tab）可以复用检测结果的骨架
- **但目前精确缓存够用，这个 P2 再考虑**

#### 4. 格式转换器插件系统 ← labelU converter

labelU 的 `converter.py` 支持 9 种输出格式（COCO/YOLO/MASK/VOC/TFRecord...），用 dispatcher 模式：

```python
def convert(format_type, annotations, ...):
    converters = {"coco": to_coco, "yolo": to_yolo, "mask": to_mask, ...}
    return converters[format_type](annotations)
```

**偷法→ cvui DetectionContext.to_xxx()**：
- 当前只有 `to_prompt()` 和 `to_report()`
- 加 `to_coco()`, `to_yolo()`, `to_labelme()` 让检测结果可直接用于训练标注
- 这样 cvui 既是检测工具，也是标注数据生成器

### P1 — 短期可偷

#### 5. 预标注 + 人工修正工作流 ← labelU Pre-Annotation

labelU 的 `TaskPreAnnotation` 模型：AI 先标注 → 人工修正 → 保留来源审计链。

**偷法→ /analyze-ui 增强**：
- 当前 `/analyze-ui` 只输出结果图
- 加"交互修正"模式：VLM 预标注 → 用户在 dashboard 上拖拽修正 bbox → 修正结果回写为训练数据
- 形成 **检测→修正→训练→检测** 的飞轮

#### 6. Gemini 结构化输出格式 ← Gemini Image Understanding

Gemini 的 bbox + segmentation 输出格式值得直接复用：

```json
{
  "box_2d": [ymin, xmin, ymax, xmax],  // 归一化 0-1000
  "label": "设置面板",
  "mask": "base64_encoded_png"           // 概率图，127 阈值二值化
}
```

**偷法→ VLMZoneStage 输出格式**：
- 统一用 0-1000 归一化坐标（与 Gemini 兼容）
- `DetectionContext` 内部用像素坐标，输入输出层做归一化/反归一化
- 这样 VLM 后端可以是 Gemini / Claude / 本地 VLM，格式统一

#### 7. pix2emb 范式（位置 embedding 而非坐标文本）← NExT-Chat 清华+NUS

**论文**: [NExT-Chat: An LMM for Chat, Detection and Segmentation](https://arxiv.org/abs/2311.04498)
**作者**: Ao Zhang, Yuan Yao, Wei Ji, Zhiyuan Liu, Tat-Seng Chua

**核心思想**：现有 VLM 做检测有两种范式：
- **pix2seq**（Gemini/Shikra 用的）：把 bbox 坐标当文本生成 `[y1,x1,y2,x2]` → 精度受 tokenizer 限制
- **pix2emb**（NExT-Chat 提出）：LMM 输出**位置 embedding 向量**，再用专门的 decoder 解码为 bbox/mask

架构：CLIP ViT-L (视觉) + LLaMA-7B (语言) + SAM ViT-H (分割 decoder)，三阶段训练：
1. VL + Detection 预训练
2. Instruction Following + Detection
3. 加入 Segmentation

**性能**：
- POPE-Random: 87.7（超 Shikra 86.9）
- Region Caption: 79.6（大幅超 Kosmos-2 的 62.3）
- Referring Segmentation: 68.9（超 LISA 67.9）

**偷法→ cvui VLMZoneStage 的输出格式选择**：
- 如果用 pix2seq（Gemini 风格）：坐标是文本，解析简单，但精度受限（Gemini 用 0-1000 量化缓解）
- 如果用 pix2emb：需要专门的 decoder head，但精度更高，且可以同时输出 bbox + mask
- **近期用 pix2seq（简单，Gemini/Claude 直接支持）**
- **长期如果训练自己的模型，考虑 pix2emb（精度更好）**

关键启示：VLM 做 grounding 不是只有"让模型吐坐标"一条路。embedding 解码是更优雅的方式，因为空间信息本质上是连续的，强行量化成 token 序列会丢精度。

#### 8. NVIDIA TAO 微调 Grounding DINO ← NVIDIA TAO Toolkit（原 #7）

NVIDIA 提供商用许可的 Grounding DINO（Swin-Tiny 骨干），可在 TAO 中微调：
- 数据格式：ODVG (JSONL) 训练 + COCO 验证
- 骨干：Swin-Tiny，用 NVImageNetv2 预训练
- 硬件要求：V100/A100，15GB+ VRAM

**偷法→ 长线目标**：
- 收集 cvui 的 `/analyze-ui` 修正数据作为训练集
- 微调一个专门的 UI Element Grounding DINO
- 替代当前的 `GroundingDINOStage`（通用模型 → 领域微调模型）

### P2 — 长线参考

#### 8. OmniParser 全套 ← Microsoft OmniParser v2

完整管线：YOLO icon 检测 → Florence-2 icon caption → PaddleOCR 文字提取 → 结构化输出

cvui 已有：CV 检测 + WinOCR，缺的是 icon caption（知道图标是什么意思）。
长线考虑加一个 `IconCaptionStage`，用 Florence-2-base (~230M) 对每个 icon 类 rect 生成描述。

#### 9. 多模态标注平台 ← labelU 全栈

labelU 的 React monorepo 前端（image/video/audio-annotator）+ FastAPI 后端 + SQLite/MySQL。
如果 cvui 要做标注数据生产线，可以参考 labelU-Kit 的组件架构：
- `image-annotator-react`：Canvas 渲染 + 工具切换 + undo/redo
- `@labelu/formatter`：Registry 模式的格式转换插件

#### 10. Gemini Segmentation Mask ← Gemini 2.5+

Gemini 2.5 支持逐像素分割 mask（base64 PNG 概率图）。
cvui 目前只做 bbox 级别检测。语义分割是更远的目标，但 Gemini 的 API 格式可以先适配。

## 候选本地 VLM 对比

| 模型 | 参数量 | VRAM | 延迟 (估) | 适合场景 |
|------|--------|------|-----------|---------|
| Florence-2-base | 230M | ~1GB | ~80ms | icon 分类/caption |
| moondream2 | 1.8B | ~4GB | ~150ms | 区域定位 + 简单 QA |
| Qwen2-VL-2B | 2B | ~5GB | ~200ms | 最佳理解力/延迟平衡 |
| PaliGemma-3B | 3B | ~6GB | ~300ms | 精确 grounding |
| Grounding DINO (Swin-T) | ~170M | ~2GB | ~50ms | 纯检测，无理解 |

**推荐路线**：
1. 近期：Grounding DINO 做 zone 检测（快 + 准 + 商用友好）
2. 中期：Qwen2-VL-2B 做语义区域理解（"这是菜单/设置面板/背景画"）
3. 长期：微调专用模型，用 cvui 积累的修正数据

## cvui 演进路线图

```
当前: 纯 CV Pipeline (21 Stage + Ensemble)
  ↓
Phase 1: + VLMZoneStage (Grounding DINO / 本地 VLM)
  ↓       解决场景/UI 分离的语义理解缺口
Phase 2: + CNN ClassifyStage (替代启发式)
  ↓       + to_coco()/to_yolo() 格式导出
Phase 3: + IconCaptionStage (Florence-2)
  ↓       + 交互修正 → 训练数据飞轮
Phase 4: + 微调 Grounding DINO on UI data
          真正的领域专用检测模型
```

### 补充模式（对话中后续发现）

#### 11. Image Tiling 大图切块检测 ← DarkHelp

DarkHelp 把大图切成 NxN tiles 分别检测再合并。解决 cvui 的实际问题：2564×1647 截图缩放到 640 会丢细节。
**偷法→ cvui**: 加 `TilingStage`，切 tile → 每个 tile 跑 pipeline → 合并去重。小元素（checkbox、滑块旋钮）不再被缩放吞掉。

#### 12. Prompt-based 多任务统一模型 ← DOTS OCR

1.7B VLM 通过 prompt 切换：layout detection (F1=0.93) / OCR / region grounding。
**长线参考**：如果 cvui 未来挂模型，统一 VLM 比 YOLO+OCR+classifier 三件套干净。

#### 13. 合成数据训练 ← Rolodex / DocLayout-YOLO DocSynth-300K

用合成数据训 YOLO 检测器，不需要手动标注。DocLayout-YOLO 用 bin-packing 算法生成 300K 合成文档页面。
**偷法→ 微模型训练**：UI 截图 + 随机游戏背景合成训练数据。

#### 15. DOTS OCR 布局解析替代 CV 首阶段 ← dots.ocr-1.5

1.7B VLM，prompt_layout_only 模式可直接输出 bbox + 类别（title/text/list-item/caption 等）。
在 Disco Elysium 截图上实测效果好——每行设置项都识别出来，中文正确。
**偷法→ cvui**: 可作为 VLMZoneStage 的另一个后端选择，替代 Grounding DINO。布局解析比通用检测更贴合 UI 场景。
- 模型：https://huggingface.co/rednote-hilab/dots.ocr
- Demo：https://dotsocr.xiaohongshu.com/

#### 14. 纯 CV 结构性过滤（对话验证）

DBSCAN 密度聚类 + 多维异常检测（饱和度/方差/边缘密度/邻域密度），Otsu 自动阈值。
效果：56→41 rects，右侧场景基本清除，60ms，0 模型。接近 Hybrid (YOLO 39MB + CV) 效果。
**已实现为 structural_v4**，可包装为 `StructuralFilterStage`。

## Sources

- [DarkHelp (tiling/server)](https://github.com/stephanecharette/DarkHelp)
- [Darknet V3](https://github.com/hank-ai/darknet)
- [DOTS OCR](https://medium.com/data-science-in-your-pocket/dots-ocr-the-best-small-sized-ocr-ever-b069d92153c2)
- [DocLayout-YOLO](https://arxiv.org/abs/2410.12628)
- [labelU - OpenDataLab](https://github.com/opendatalab/labelU)
- [UIED - MulongXie](https://github.com/MulongXie/UIED)
- [OmniParser v2 - Microsoft](https://github.com/microsoft/OmniParser)
- [Gemini Image Understanding](https://ai.google.dev/gemini-api/docs/image-understanding)
- [PaddleX PP-ShiTuV2](https://paddlepaddle.github.io/PaddleX/3.3/pipeline_usage/tutorials/cv_pipelines/general_image_recognition.html)
- [NVIDIA TAO Grounding DINO](https://docs.nvidia.com/tao/tao-toolkit/latest/text/cv_finetuning/pytorch/object_detection/grounding_dino.html)
- [NVIDIA nv-grounding-dino NIM](https://build.nvidia.com/nvidia/nv-grounding-dino/modelcard)
- [Grounding DINO - IDEA Research](https://github.com/IDEA-Research/GroundingDINO)
