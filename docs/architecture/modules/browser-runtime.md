# Browser Runtime

> Chrome CDP 封装 — 进程生命周期、Tab 池化、防御层、AI API。

## Key Files

| File | Purpose |
|------|---------|
| `browser_runtime.py` | BrowserRuntime — Chrome 进程启动/停止、profile 管理、Tab 池 |
| `browser_cdp.py` | CDPClient（同步 WebSocket CDP）+ TabLease（TTL 租约） |
| `browser_guard.py` | PageFingerprint + ActionLoopDetector（循环检测 + 升级警告） |
| `browser_navigation.py` | 导航、截图、快照、搜索、screencast 帧流 |
| `browser_interaction.py` | 点击（JS/鼠标）、填写、滚动、按键、执行 JS |
| `browser_tools.py` | 薄 re-export 层，汇总 navigation + interaction |
| `browser_ai.py` | BrowserAI — Chrome 内置 Web AI API（Summarizer/Translator/LanguageDetector） |

## Architecture

BrowserRuntime 管理一个隔离的 Chrome 实例。支持 headless（Docker）和 desktop（桌面）两种模式。纯 stdlib 实现，不依赖 Selenium/Playwright。

Tab 池化通过 `TabLease` 实现：每个 Tab 有 purpose（read/interact）、department 归属、TTL（read 300s / interact 600s）。过期 Tab 自动回收。`max_tabs` 限制并发页面数。Profile 管理按平台隔离 session（从 GoLogin 偷师）。

CDPClient 通过 WebSocket 发送 CDP 命令。支持事件订阅模式（从 Carbonyl 偷师），用于 screencastFrame 等持续推帧场景。

## Browser Guard

BrowserGuard 是防御层（从 browser-use 偷师）：

- **PageFingerprint**: URL + 元素数 + DOM 文本哈希，轻量级页面状态比对
- **ActionLoopDetector**: 检测 agent 原地打转，产出升级式警告

Guard 不做决策，只提供信号。警告附加在返回值的 `_guard_warnings` 字段，调度层自行处理。

## Headless vs Desktop

| Mode | Chrome flags | AI API | Use case |
|------|-------------|--------|----------|
| Headless | `--headless=new` | 不可用 | Docker / CI |
| Desktop | 无 headless flag | 可用 | 桌面环境，BrowserAI 需要 |

BrowserAI 在 headless 下自动降级（Web AI API 需要完整渲染引擎）。

## Related

- Spec: `docs/superpowers/specs/2026-03-25-browser-runtime-design.md`
