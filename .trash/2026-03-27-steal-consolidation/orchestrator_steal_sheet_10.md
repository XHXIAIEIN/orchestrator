---
name: 偷师 bytebot
description: 第十轮偷师：bytebot（10.6K star）— Takeover人机交接 / InputCapture事件聚合 / 自动截图 / type vs paste / Context Summarization / MCP暴露
type: reference
---

## bytebot（10.6K star）— 桌面操控 Agent

**仓库**: `bytebot-ai/bytebot` | TypeScript/NestJS | Apache 2.0

### 架构：四层分离

```
bytebot-ui (Next.js :9992)     ← 前端 VNC 实时观看 + 任务管理
bytebot-agent (NestJS :9991)   ← LLM 调度 + 任务队列 + 消息历史
bytebotd (NestJS :9990)        ← 桌面守护进程，操控桌面
Ubuntu 22.04 + XFCE            ← 虚拟桌面
```

Agent 和 Desktop 通过 HTTP API 通信，物理隔离。

### 核心差异：零感知 vs 我们的三层感知

bytebot 没有 OCR、没有元素检测、没有 CV pipeline。全靠 LLM 原生视觉看截图决定下一步。
- 每个操作后等 750ms → 自动截图 → 作为 tool_result 返回
- 固定 1280×960 绝对坐标，无缩放/DPI 处理
- 底层引擎：`@nut-tree-fork/nut-js`（X11）

### P0 可偷模式

#### 1. Takeover + InputCapture（人机交接）
- `uiohook-napi` 监听全局鼠标/键盘事件
- 事件转为标准 ComputerAction 格式，注入消息历史
- Agent 恢复后能看到用户做了什么
- debounce：click 250ms 去重（取最高 clickCount），typing 500ms 聚合为 TypeTextAction，scroll 4次聚合
- 鼠标移动 debounce 250ms 自动截图，click/drag 发截图+动作对
- **偷法**：`pynput` 监听 + debounce 聚合 → 注入 trajectory

#### 2. 操作后自动截图
- 每个非截图 action 执行后等 750ms → 自动截图附加到 tool_result
- LLM 不需要显式调 screenshot
- **偷法**：ActionExecutor 层自动附加截图，省一轮 LLM 调用

#### 3. type vs paste 分离
- `type_text`：逐字符按键，≤25字符/密码
- `paste_text`：`xclip` 写剪贴板 → Ctrl+V，长文本/特殊字符
- `isSensitive` 标记阻止回显密码
- **偷法**：actions.py 加 `paste_text` action + `sensitive` 参数

### P1 可偷模式

#### 4. Context Summarization
- 监控 token usage，达 context window 75% 时触发
- 用同一 LLM 生成对话摘要，存 DB，旧消息标记已摘要
- 下次迭代只加载 [最新摘要 + 未摘要消息]
- **偷法**：trajectory.py 加 `summarize()` 方法

#### 5. MCP 端点暴露
- bytebotd 通过 `/mcp` SSE 暴露全部桌面操作工具
- agent-cc 变体用 Claude Code SDK `query()` + MCP
- **偷法**：desktop_use 加 MCP server 层

#### 6. 任务调度 + 子任务
- LLM 通过 `create_task` 工具创建后续任务（IMMEDIATE/SCHEDULED）
- Scheduler 每 5 秒轮询，按优先级取任务

### 不偷的

- 固定 1280×960 绝对坐标 — 我们的物理→逻辑归一化更好
- 零感知纯视觉方案 — 成本太高
- NestJS 微服务拆分 — 过度工程
- `charToKeyInfo()` 只有 ASCII 映射 — 太弱

### 对比优势

| 维度 | bytebot | desktop_use |
|------|---------|-------------|
| 感知 | 纯 LLM 视觉 | Win32+CV+OCR 三层 |
| 元素检测 | 无 | CC+Classify+Blueprint |
| 坐标系 | 固定绝对 | DPI 归一化 |
| 人机交接 | ✅ Takeover+InputCapture | ❌ |
| 上下文管理 | LLM 摘要 | 固定窗口 |
| MCP | ✅ SSE 端点 | ❌ |
