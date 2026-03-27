---
name: orchestrator-steal-sheet-9
description: 2026-03-27 第九轮偷师：Carbonyl（17.1K star）— 渲染管线劫持 / Unicode像素网格 / 共享内存IPC / LoDPI缩放 / 文本保真拦截 / 终端作为显示设备
type: project
---

## 来源

**Carbonyl** — https://github.com/fathyb/carbonyl (17.1K stars)
- "Chromium running inside your terminal"
- 语言：Rust（核心渲染 `libcarbonyl`）+ C++（Chromium 修改层）
- 架构：fork Chromium headless shell → 动态加载 Rust 核心库 → Skia Device 拦截 → ANSI 终端输出
- 性能：60fps、空闲 0% CPU、滚动 ~15% CPU，比 Browsh 快 50x

技术博客：https://fathy.fr/carbonyl

## 核心架构

```
Chromium Renderer (Skia)
    │
    ├─ TextCaptureDevice ──→ 拦截 glyph → 保留可选文本
    │
    └─ SkBitmap 输出
           │
    HostDisplayClient (自定义)
           │
    共享内存映射 ──→ Mojo IPC ──→ Browser Process
           │
    LoDPI 1/7 缩放 → 像素网格 49x 压缩
           │
    四象限二值化 → Unicode ▄ 字符 + 24-bit ANSI 色
           │
    终端输出 ← ANSI DCS 输入事件回流
```

## 偷到的模式

### P0 — 可偷到 Orchestrator 的

#### 1. 渲染管线劫持（Renderer Hijacking）← Carbonyl 核心思路

**原理**：不重写引擎，在现有渲染管线的**出口处**插入自定义 Device/OutputClient，把像素流重定向到任意目标。

**偷法→ desktop_use + browser**：
- 当前 `browser_screenshot()` 用 CDP `Page.captureScreenshot` 截图，是"请求-响应"模式，有延迟
- Carbonyl 的做法是替换 `SoftwareOutputDevice`，compositor 每帧直接写入共享内存，零拷贝
- **可偷**：对 headless Chrome 启用 CDP `Page.screencastFrame` 事件流（持续推帧），而非每次主动截图
- 效果：desktop_use 的感知循环从"截图→分析→截图"变成"持续帧流→按需分析"，延迟降低 2-5x

#### 2. Unicode 像素网格（Terminal as Display）← ▄ 半块字符技巧

**原理**：Unicode U+2584（下半块）让每个终端字符格承载 2 个像素——前景色=下半像素，背景色=上半像素。配合 24-bit ANSI 转义序列，终端变成一个低分辨率但全彩的显示设备。

**偷法→ channel 层 / dashboard**：
- Telegram/WeChat 不支持 ANSI，但支持等宽字体 + Unicode
- 可以用 ▄▀█░▒▓ 等块字符在消息中渲染**小型像素图**（热力图、状态矩阵、简易图表）
- **已有基础**：Telegram channel 已有 ASCII 动画，可以升级为 Unicode 块字符动画
- 实际应用：系统健康度用 8x4 的色块矩阵一目了然，比文字描述直观 10x

#### 3. 共享内存 IPC 零拷贝（SharedMemory Rendering）← 性能杀手锏

**原理**：Carbonyl 把 `HostDisplayClient` 替换为自定义实现，compositor 写入 shared memory region，browser 进程直接映射读取，避免序列化/反序列化。CPU 从 400% 降到 15%。

**偷法→ desktop_use 感知层**：
- 当前 `MSSScreenCapture` 每次截图都是完整帧拷贝（mss → numpy array → PIL → bytes）
- 可以引入 `multiprocessing.shared_memory` 让截图进程写入共享内存，感知层直接读取
- 对于连续帧场景（GUI 自动化循环），省掉每帧的序列化开销
- **配合帧差分**：共享内存里保留上一帧，只在变化区域触发 OCR/CV 分析

#### 4. LoDPI 缩放策略（Resolution Adaptation）← 聪明的偷懒

**原理**：Carbonyl 把 display scale 强制设为 1/7，像素网格缩小 49 倍。渲染负载线性下降，但终端字符分辨率本来就低，不损失视觉质量。

**偷法→ desktop_use CV pipeline**：
- cvui 的 `DownscaleStage` 已经在做类似的事，但是固定缩放比
- 可以偷 Carbonyl 的思路：**根据目标分辨率反推缩放比**
  - 终端输出 → 激进缩放（1/4~1/8）
  - Channel 消息 → 中等缩放（1/2~1/4）
  - 全精度分析 → 不缩放
- 这是一个**自适应降采样策略**，而非写死的参数

#### 5. 文本保真拦截（TextCaptureDevice）← 文本 vs 像素的分离

**原理**：Carbonyl 在 Skia 渲染 glyph 之前用 `TextCaptureDevice` 拦截文字，保留原始 Unicode 文本。终端里的文字是真正可选择的文本，不是像素画出来的。

**偷法→ desktop_use OCR 优化**：
- 当前流程：截图 → 全图 OCR → 提取文字。OCR 是最慢的环节
- Carbonyl 的思路：如果能在**渲染前**就拿到文字，根本不需要 OCR
- **可偷**：对 Chrome 页面，用 CDP `DOM.getDocument` + `Runtime.evaluate` 直接提取 DOM 文本，跳过 OCR
- 对 Win32 窗口，用 `Win32Layer` 的 `EnumChildWindows` 获取控件文本（已有，但可以更激进地信任它）
- **分层策略**：能拿到结构化文本 → 用文本；拿不到 → 降级到 OCR。和 Carbonyl 的 TextCapture + 像素 fallback 同构

### P1 — 架构启发（不直接偷，但影响设计思路）

#### 6. 终端作为一等显示设备（Terminal-First Display）

**原理**：Carbonyl 证明终端不只是"文字输出"，而是一个功能完整的显示设备——有像素、有色彩、有输入事件、有刷新率。

**启发→ orchestrator 整体**：
- 当前 orchestrator 的"眼睛"是 dashboard（Web UI），"嘴巴"是 channel（TG/WX）
- 缺一个**终端原生 UI**——在 SSH 会话里直接看状态、看日志、交互式操作
- Python 生态有 `textual`（TUI 框架，同一作者做了 rich），可以做一个轻量终端 dashboard
- 不是要用 Carbonyl 本身，而是借它的思路：**终端也是一个 channel**

#### 7. Mojo IPC 自定义服务（CarbonylRenderService）

**原理**：Carbonyl 定义了自己的 Mojo 接口 `CarbonylRenderService`，在 Chromium 多进程之间传递渲染数据，避免走标准的 GPU readback 路径。

**启发→ Agent SDK 多进程架构**：
- 当前 orchestrator 的 agent 之间通过文件/数据库/HTTP 通信
- 如果未来需要高频数据交换（比如 desktop_use 的帧流 → 分析器），可以考虑 shared memory + 简单 IPC 协议
- 不需要 Mojo 这么重，`multiprocessing.Queue` + `shared_memory` 就够

#### 8. 输入事件回流（ANSI DCS → Chromium Events）

**原理**：终端的键盘/鼠标事件通过 ANSI Device Control Sequences 传回 Carbonyl，再注入 Chromium 的事件系统。形成完整的交互闭环。

**启发→ channel 双向交互**：
- Telegram channel 已经有命令解析（`/command`），但还没有"在终端里交互式操作 orchestrator"的能力
- Carbonyl 的 DCS 回流思路 → channel 的回调机制可以更统一：任何 channel 的用户输入 → 统一事件 → dispatcher → 执行

## 实施优先级

| # | 模式 | 难度 | 价值 | 依赖 |
|---|------|------|------|------|
| 1 | CDP screencastFrame 帧流 | 低 | 高 | browser_cdp.py |
| 2 | Unicode 块字符可视化 | 低 | 中 | channel formatter |
| 3 | 共享内存截图 IPC | 中 | 高 | desktop_use screen.py |
| 4 | 自适应降采样策略 | 低 | 中 | cvui DownscaleStage |
| 5 | 文本优先分层策略 | 低 | 高 | desktop_use perception.py |
| 6 | 终端 TUI dashboard | 高 | 中 | 新模块 |

## 总结

Carbonyl 的核心洞察：**不要重写引擎，劫持渲染出口**。这个思路在 orchestrator 里翻译为：
- 不要用截图+OCR 模拟人眼看屏幕 → 直接从 DOM/Win32 API 拿结构化数据
- 不要每次主动请求状态 → 订阅事件流，按需分析
- 终端/消息应用也是显示设备 → 用 Unicode 块字符做轻量可视化
