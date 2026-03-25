# BrowserRuntime — 感官层设计

> Orchestrator 的能力升级：从步行到骑自行车。

## Context

Orchestrator 当前的浏览器能力仅限于被动读取 Chrome History DB。通过集成 Chrome 内置 AI API（Prompt API、Summarizer、Translator 等）和 CDP 浏览器自动化，将浏览器提升为一个**感官层基础设施**——所有部门都能"看网页、读内容、填表单、理解页面"。

同时通过 WebMCP（experimental）让 Dashboard 自身可被外部 AI agent 操作，实现双向能力。

## 能力栈定位

```
L0  感知层   文件系统(已有) + 终端(已有) + BrowserRuntime(新增)
L1  理解层   Chrome AI(端侧/免费/仅桌面) → Ollama(本地) → Claude(云端)
L2  决策层   三省六部
L3  执行层   Agent SDK + BrowserRuntime + Channel Layer
L4  反馈层   Dashboard(MCP Server) + Telegram + Claw
```

BrowserRuntime 横跨 L0 和 L3——既是感知（看页面），也是执行（操作页面）。
通过**按用途分 tab** 隔离感知与执行：读取操作分配临时 tab（用完即关），填表等有状态操作分配独占 tab。

## 架构

### 组件拓扑

```
src/core/browser_runtime.py          ← 核心：实例管理 + CDP 连接 + Tab 池
src/core/browser_ai.py               ← Chrome AI API 封装（仅桌面环境可用）
src/core/browser_tools.py            ← Agent 可调用的工具函数
src/core/webmcp_server.py            ← [experimental] Dashboard MCP Server 暴露
```

### BrowserRuntime（实例管理）

```python
class BrowserRuntime:
    """
    Chrome 浏览器运行时 — 可拆卸基础设施组件。
    跟 EventsDB、EventBus、LLMRouter 同级。
    不可用时其他组件照常运行。
    """
    async def start() -> None        # 启动 Chrome 实例
    async def stop() -> None         # 优雅关闭
    async def ensure() -> CDPConn    # 懒初始化，返回 CDP 连接（自动重连）
    async def health() -> dict       # 健康检查（端口/进程/页面数/AI能力）

    # Tab 池管理
    async def acquire_tab(purpose: str, dept: str) -> Tab   # 租借 tab
    async def release_tab(tab: Tab) -> None                 # 归还 tab
    async def reap_zombie_tabs(max_age_s: int = 300) -> int # 回收超时 tab

    # 连接参数（env 驱动）
    chrome_path: str                 # Chrome 可执行文件路径
    user_data_dir: str               # 隔离的用户数据目录（data/browser_profile/）
    debug_port: int                  # 默认 9222
    headless: bool                   # Docker 内 True，桌面 False
    max_tabs: int                    # 默认 5（不含 AI 常驻页）
```

**Tab 池设计：**
```
Tab 池（max_tabs=5）:
  ├── [reserved] AI Context Page（about:blank，BrowserAI 专用，不计入配额）
  ├── [leased]   工部 task#42 — https://docs.python.org  (purpose=read, expires=5min)
  ├── [leased]   户部 task#43 — https://issues.chromium.org (purpose=interact, expires=10min)
  └── [free]     3 slots available

语义：
  acquire_tab("read", "engineering")   → 分配临时 tab，5min 超时自动回收
  acquire_tab("interact", "operations") → 分配独占 tab，10min 超时，可续租
  release_tab(tab)                      → 关闭页面，归还 slot
  reap_zombie_tabs()                    → 定时回收超时未归还的 tab（agent 崩溃保护）
```

**生命周期：**
```
scheduler.py 启动
  → BrowserRuntime.start()
  → 检测 Chrome 可执行文件（桌面: Chrome/Beta/Canary 自动发现，Docker: chromium）
  → 启动隔离实例（subprocess）
    - --user-data-dir=<isolated>
    - --remote-debugging-port=9222
    - Docker 额外: --headless --no-sandbox --disable-dev-shm-usage --disable-session-crashed-bubble
  → 等待 /json/version 响应
  → 注册到 health 检查
  → 启动 zombie tab 回收定时器（每 60s）

scheduler.py 停止
  → BrowserRuntime.stop()
  → 关闭所有 tab → 优雅关闭 Chrome 进程
```

**可拆卸设计：**
- `BROWSER_RUNTIME_ENABLED=false` 环境变量一键禁用
- 所有调用方先检查 `runtime.available`，不可用时 graceful fallback
- Docker 内通过 `chromium --headless` 运行
- 桌面环境检测已安装的 Chrome/Beta/Canary
- Chrome 崩溃：自动重启 + 指数退避（1s/2s/4s），max 3 次后标记 unavailable

### BrowserAI（Chrome AI API 封装）

> **重要约束：BrowserAI 仅在桌面环境（非 headless）可用。**
> Chrome 内置 AI API 依赖 on-device 模型（Gemini Nano），需要 GPU/NPU 上下文。
> Headless Chrome（Docker 环境）不加载 on-device 模型，`Summarizer.create()` 等会返回 unavailable。
> Docker 下 BrowserAI 自动跳过，级联直接走 Ollama → Claude。

```python
class BrowserAI:
    """
    Chrome 内置 AI 能力封装。
    通过 CDP Runtime.evaluate 调用页面内的 Web AI API。
    仅桌面环境可用，Docker/headless 下自动降级。
    """
    async def summarize(text: str, type: str = "key-points", length: str = "medium") -> str
    async def translate(text: str, source: str, target: str) -> str
    async def detect_language(text: str) -> list[dict]
    async def prompt(system: str, user: str) -> str          # Gemini Nano
    async def rewrite(text: str, tone: str, length: str) -> str
    async def proofread(text: str, lang: str) -> list[dict]  # [experimental]

    # 能力探测（启动时调用一次，缓存结果）
    async def capabilities() -> dict

    # 同步包装器（供 LLMRouter 调用）
    def summarize_sync(text, **kw) -> str    # 内部用独立线程跑 asyncio
    def translate_sync(text, **kw) -> str
```

**Async/Sync 适配：**
LLMRouter.generate() 是同步方法。BrowserAI 通过独立线程运行 event loop 提供同步包装器：
```python
import threading, asyncio

class _SyncBridge:
    """独立线程跑 asyncio loop，供同步代码调用 async BrowserAI。"""
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)
```

**实现原理：**
通过 CDP `Runtime.evaluate` 在 AI Context Page（常驻空白页）中注入 JS：
```js
const s = await Summarizer.create({type: 'key-points', format: 'markdown', length: 'medium'});
return await s.summarize(inputText);
```

### LLM Router 扩展

在现有级联路由中加入 Chrome AI 作为第零层（仅桌面环境生效）：

```python
ROUTES = {
    "summary":    {"cascade": ["chrome-ai/summarizer", "claude-haiku-4-5-20251001"], "timeout": 30},
    "translate":  {"cascade": ["chrome-ai/translator", "claude-haiku-4-5-20251001"], "timeout": 15},
    "lang_detect":{"backend": "chrome-ai", "model": "language-detector", "timeout": 5,
                   "fallback": "claude", "fallback_model": "claude-haiku-4-5-20251001"},
    "chat":       {"cascade": ["ollama/qwen2.5:7b", "claude-haiku-4-5-20251001"], "timeout": 15},
    # ... 现有路由不变
}

MODEL_TIERS = {
    "chrome-ai/summarizer":        {"cost": 0, "capability": 0.4,  "multimodal": False, "env": "desktop"},
    "chrome-ai/translator":        {"cost": 0, "capability": 0.5,  "multimodal": False, "env": "desktop"},
    "chrome-ai/prompt":            {"cost": 0, "capability": 0.35, "multimodal": False, "env": "desktop"},
    "chrome-ai/language-detector": {"cost": 0, "capability": 0.8,  "multimodal": False, "env": "desktop"},
    # ... 现有模型不变
}
```

**Fallback 逻辑：**
- `env: "desktop"` 标记 → Docker 下自动跳过，不尝试
- BrowserRuntime unavailable → 跳过，走下一级
- Chrome AI 返回空/垃圾（< MIN_RESPONSE_LEN）→ 跳过，走下一级
- 跟现有 Ollama fallback 逻辑完全一致

### BrowserTools（Agent 工具）

部门 Agent 可通过 blueprint 声明使用的浏览器工具。**严格白名单制**——必须在 `allowed_tools` 中显式列出才可用（与现有 Policy 系统一致）。

```python
# 页面操作（安全级别：普通）
async def browser_navigate(url: str) -> dict              # 打开页面，返回 title + 状态
async def browser_screenshot(selector: str = None) -> str  # 截图，返回 base64
async def browser_snapshot() -> str                        # 页面 accessibility snapshot
async def browser_click(uid: str) -> dict                  # 点击元素
async def browser_fill(uid: str, text: str) -> dict        # 填写输入框

# 高危工具（安全级别：需审批 authority: APPROVE）
async def browser_evaluate(js: str) -> Any                 # 执行任意 JS — 默认全部门 denied
async def browser_fill_form(url: str, data: dict) -> dict  # 表单自动化 — 用 snapshot heuristic 定位字段，不调 LLM

# AI 增强操作（安全级别：普通，仅桌面环境可用）
async def browser_summarize_page(url: str) -> str          # 打开页面 + 自动摘要
async def browser_translate_page(url: str, target: str) -> str  # 打开 + 翻译
async def browser_read_page(url: str) -> str               # 打开 + 提取正文（headless 也可用）
```

**`browser_fill_form` 实现说明：**
用 accessibility snapshot 的 label/aria 属性做 heuristic 字段匹配（`name ↔ label` 映射），不调 LLM，避免递归调用。

**Policy 集成示例：**

```yaml
# departments/engineering/blueprint.yaml — 工部：可读网页，不可操作表单
policy:
  allowed_tools:
    - Bash
    - Read
    - Edit
    - Write
    - browser_navigate
    - browser_read_page
    - browser_summarize_page
    - browser_screenshot
    - browser_snapshot

# departments/operations/blueprint.yaml — 户部：可操作表单（需审批）
policy:
  allowed_tools:
    - Bash
    - Read
    - browser_navigate
    - browser_read_page
    - browser_fill
    - browser_click
    - browser_fill_form           # authority: APPROVE
  approve_required:
    - browser_fill_form

# departments/security/blueprint.yaml — 兵部：浏览器工具全部 denied（默认，不列出即不可用）
policy:
  allowed_tools:
    - Read
    - Grep
    - Glob
```

### WebMCP Server [experimental]

> **现状：WebMCP 的浏览器端 API（`navigator.ai.tools.register()`）截至 2025 年 5 月尚未定稿。**
> Phase 6 先只做 MCP-over-HTTP（JSON-RPC），这是已有标准且 Dashboard Express 可以直接暴露。
> 等 WebMCP 浏览器端标准明确后再加 declarative HTML meta 和 imperative JS API。

```python
class MCPServer:
    """
    将 Orchestrator Dashboard 的核心操作暴露为 MCP tool schema。
    外部 agent 通过 JSON-RPC over HTTP 调用，不需要解析 DOM。
    """
    tools = [
        Tool("get_system_status",    "查看系统状态",   params={}),
        Tool("list_tasks",           "查看任务列表",   params={"status": "open|completed|all"}),
        Tool("create_task",          "创建任务",       params={"description": str, "department": str}),
        Tool("approve_task",         "审批任务",       params={"task_id": int, "decision": "approve|deny"}),
        Tool("get_department_stats", "部门统计",       params={}),
        Tool("query_events",         "查询事件",       params={"source": str, "hours": int}),
        Tool("get_daily_summary",    "获取日报",       params={"date": str}),
    ]
```

**暴露方式（分阶段）：**
1. **Phase 6a — MCP-over-HTTP**：Dashboard Express 新增 `/mcp` 端点，JSON-RPC 协议，现在就能做
2. **Phase 6b — WebMCP Declarative** [deferred]：HTML meta 标签声明 tool schema，等标准定稿
3. **Phase 6c — WebMCP Imperative** [deferred]：JS API 注册复杂操作，等标准定稿

**安全边界：**
- 只暴露只读 + 已有审批流程的操作
- `create_task` / `approve_task` 走现有 Scrutiny + Approval Gateway
- 不暴露直接写文件、执行命令等危险操作
- 需要 API Key 或 Bearer Token 认证

## 配置驱动

### 环境变量

```bash
# docker-compose.yml
BROWSER_RUNTIME_ENABLED=true
BROWSER_CHROME_PATH=/usr/bin/chromium          # Docker: chromium（不是 chromium-browser）
BROWSER_DEBUG_PORT=9222
BROWSER_HEADLESS=true                          # Docker 内 true，桌面 false
BROWSER_USER_DATA_DIR=/data/browser_profile
BROWSER_AI_ENABLED=true                        # 仅桌面生效，Docker 下自动忽略
BROWSER_MAX_TABS=5
WEBMCP_ENABLED=false                           # experimental，默认关
```

### Docker 镜像影响

```dockerfile
# Dockerfile — 新增 Chromium（约 300-400MB 额外空间）
# 建议多阶段构建或 sidecar 容器方案
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
```

**替代方案：** Chromium 作为独立 sidecar 容器（如 `browserless/chromium`），BrowserRuntime 通过网络连接其 CDP 端口。好处是主容器不膨胀，坏处是多一个容器管理。设计支持两种模式——本地进程 vs 远程 CDP endpoint。

### 健康检查

集成到现有 `health.py` 的 `HealthCheck.run()` 模式：

```python
# browser_runtime 作为新的 health section
def _check_browser(self):
    if not self.browser_runtime.available:
        self.issues.append("browser_runtime: disabled or unavailable")
        return {"status": "unavailable"}

    info = self.browser_runtime.health_sync()
    if info["pages_open"] >= info["max_tabs"]:
        self.issues.append("browser_runtime: tab pool exhausted")

    return {
        "status": "healthy" if not self.issues else "degraded",
        "chrome_version": info["version"],
        "debug_port": info["port"],
        "tabs": f"{info['pages_open']}/{info['max_tabs']}",
        "ai_available": info.get("ai_capable", False),  # headless=False 且模型已下载
    }
```

## 依赖

**新增 Python 依赖：**
- `websockets` — CDP WebSocket 通信（零传递依赖，纯 Python）

这是唯一新增的 pip 依赖。原有的"零外部依赖"风格无法维持在 CDP 通信上——裸 socket 手写 WebSocket 帧解析（握手/分帧/mask/ping-pong/大报文分片）工程量大且容易出 bug，不值得。`websockets` 库本身零依赖、纯 Python，是最小代价。

**系统依赖：**
- Chrome/Chromium 可执行文件
- Docker: `apt-get install -y chromium fonts-noto-cjk`（中文字体支持截图）

## 数据流示例

### 场景 1：工部读外文文档修 Bug

```
任务: "参考 https://example.com/docs 修复 parser bug"
  → 工部 Agent 执行
  → tool_call: browser_read_page("https://example.com/docs")
    → BrowserRuntime.acquire_tab("read", "engineering")  → 拿到临时 tab
    → navigate → 等待加载 → 提取正文
    → 桌面环境? → BrowserAI.detect_language() → "en"
                → BrowserAI.translate(text, "en", "zh") → 中文翻译（免费/端侧）
    → Docker?   → 直接返回英文正文（Agent 自己能读英文）
    → release_tab()  → 关闭页面，归还 slot
  → Agent 基于内容理解文档，修复代码
```

### 场景 2：日报摘要优化（成本优化，仅桌面）

```
桌面: DailyAnalyst → LLMRouter.generate(task_type="summary")
  → cascade[0]: chrome-ai/summarizer（免费/端侧）
  → 质量够 → 直接用
  → 质量不够 → cascade[1]: claude-haiku（付费）

Docker: DailyAnalyst → LLMRouter.generate(task_type="summary")
  → chrome-ai 跳过（env != desktop）
  → cascade[0]: claude-haiku（跟现在一样）
```

### 场景 3：外部 Agent 操作 Dashboard

```
外部 Claude Code 实例:
  → 连接 http://localhost:23714/mcp （JSON-RPC）
  → tool_call: get_system_status()
  → tool_call: list_tasks(status="open")
  → tool_call: create_task(description="优化首页加载速度", department="engineering")
    → Orchestrator 内部走完整派单流程
    → Scrutiny 审查 → 审批 → 执行
```

## 实现顺序

```
Phase 1: BrowserRuntime 核心
         实例管理 + CDP 连接（websockets）+ Tab 池 + 健康检查 + zombie 回收
         验证: start() → Chrome 启动 → health() 返回 healthy → acquire/release tab

Phase 2: BrowserTools 基础
         navigate / screenshot / snapshot / click / fill / read_page
         验证: browser_navigate("https://example.com") → 返回 title → screenshot → 有图

Phase 3: Policy 集成
         浏览器工具加入 blueprint 白名单机制 + approve_required 高危工具门控
         验证: 工部可 browser_read_page，兵部不可；browser_evaluate 全部门 denied

Phase 4: BrowserAI（仅桌面环境）
         Summarizer / Translator / LanguageDetector 封装 + 同步桥接器
         验证: 桌面 → summarize 返回摘要；Docker → capabilities() 返回全 unavailable

Phase 5: LLM Router 级联
         chrome-ai/* 作为第零层插入 cascade + env:desktop 过滤
         验证: 桌面 → summary 先走 chrome-ai；Docker → 跳过直达 Haiku

Phase 6: MCP Server [experimental]
         6a: MCP-over-HTTP（JSON-RPC）暴露 Dashboard 操作
         验证: 外部 curl/Claude Code 通过 /mcp 端点查询系统状态
```

## 风险

| 风险 | 缓解 |
|------|------|
| Chrome 崩溃 | 自动重启 + 指数退避（1s/2s/4s），max 3 次后标记 unavailable |
| Chrome AI 模型未下载 | 启动时 capabilities() 探测并缓存，不可用时跳过 |
| CDP 连接断开 | 自动重连，Tab 池检测连接状态 |
| 内存占用 | headless + max_tabs 限制 + zombie 回收定时器 |
| Agent 崩溃未归还 tab | reap_zombie_tabs() 每 60s 回收超时 tab |
| browser_evaluate 安全风险 | 白名单制默认全 denied + approve_required 门控 |
| WebMCP 标准变动 | Phase 6 先做 MCP-over-HTTP，浏览器端 deferred |
| Docker 镜像膨胀 ~400MB | 支持 sidecar 模式（远程 CDP endpoint），主容器不装 Chromium |
| Docker NTFS 路径 | user_data_dir 放在 Docker volume 内，不用 bind-mount |
| headless 恢复对话框卡死 | Chrome flags: --disable-session-crashed-bubble |
| LLMRouter sync vs BrowserAI async | _SyncBridge 独立线程跑 event loop |
