# R82 — learn-likecc (Claude Code 2.1.88 复刻工程) Steal Report

**Source**: https://github.com/Harzva/learn-likecc | **Stars**: unknown (中等体量，7022 files) | **License**: Educational
**Date**: 2026-04-17 | **Category**: Module (框架骨架 + 若干独立模块深挖)

## TL;DR

learn-likecc 不是又一个"Claude Code 克隆"。它是从 57MB `cli.js.map` 源码泄露反推出 1900+ TypeScript 文件，再叠加一批**产品化的 CLI 基础设施增强**。真正值得偷的不是复刻工程本身，而是四个被打磨到细节的子系统：**per-model 路由层**（modelRoutes）、**配置文件热重载的三道防抖**（chokidar + internalWrite + deletion grace）、**CLI 进程内 HTTP 观察台**（localhost:4310 暴露 session/pane/transcript）、**每窗口 25 字段状态隔离**（SessionTabState）。这些都是 Orchestrator 缺失或做得粗糙的能力。

## Architecture Overview

```
bin/likecode (shell stub)
  └─ ccsource/like-code-main/src/entrypoints/cli.tsx
       ├─ bootstrap/state.ts   (sessionId, remoteMode, nonInteractive)
       ├─ services/api/client.ts
       │    └─ getRouteForModel(model) → {baseURL, apiKey, authToken, headers}
       │         ↑ 读自 settings.modelRoutes 或 env CLAUDE_CODE_MODEL_ROUTES_JSON
       ├─ utils/settings/changeDetector.ts
       │    └─ chokidar.watch(dirs, {awaitWriteFinish}) 
       │         ├─ handleChange → consumeInternalWrite() 抑制自写
       │         └─ handleDelete → DELETION_GRACE_MS 宽限期
       ├─ utils/sessionTabs.ts (25 字段 SessionTabState)
       │    └─ updateSessionTab() — 25 字段浅相等检查防止无效更新
       ├─ utils/workspaceApiServer.ts (2824 行)
       │    └─ createServer() on 127.0.0.1:4310
       │         ├─ GET  /                              (HTML dashboard)
       │         ├─ GET  /api/sessions/current          (session + panes)
       │         ├─ GET  /api/sessions/current/panes    (pane 列表)
       │         ├─ GET  /api/sessions/current/events   (workflow stages)
       │         ├─ GET  /api/sessions/current/subagents
       │         ├─ GET  /api/sessions/current/panes/:id/transcript
       │         ├─ POST /api/workspace/control/submit  (提交 prompt)
       │         ├─ POST /api/workspace/control/interrupt
       │         ├─ POST /api/workspace/control/dialog
       │         ├─ POST /api/workspace/panes/create
       │         └─ POST /api/workspace/panes/switch
       ├─ commands/show.ts — /show, /show:global, /show:user, /show:project, /show:slash
       │    └─ redactSecrets(SECRET_KEY_PATTERN) 递归脱敏
       └─ screens/REPL.tsx + components/SessionTabsBar + SessionWorkspacePanel + SessionPaneDock
```

## Six-Dimensional Scan

| Dimension | Finding | Status |
|-----------|---------|--------|
| **Security / Governance** | `/show` 命令的 `SECRET_KEY_PATTERN = /(token\|api[-_]?key\|auth[-_]?token\|secret\|password)/i` 递归脱敏，长字符串保留头尾 4 位（`sk-ab***cdef`）。`ConfigChange` hook 前置拦截配置变更（返回 block 时跳过 reload）。`isFirstPartyAnthropicUrl` host 白名单判定，非 first-party 才会做 apiKey→authToken 镜像 | 👍 |
| **Memory / Learning** | 项目本身不做记忆，但 `.claude/plans/` 下有 `loloop/` 子目录（自演进迹象），skills/ 下 `skillsmp-find-install` 做 skill 装配 | N/A (不是记忆系统) |
| **Execution / Orchestration** | `SessionLayoutMode = 'single' \| 'tabs' \| 'panes'` 三态切换。`SessionTabKind = 'main' \| 'task' \| 'review' \| 'search' \| 'subagent'`。`Ctrl+g` 作为 window leader key（zellij 风格），后接 `c/n/p/x/s/1-9/h/l`。Pane 可绑定 `subagentId` 做可视化挂接，但 subagent 执行层与 pane 显示层解耦 | 👍 核心卖点 |
| **Context / Budget** | 未发现特殊压缩机制。`transcriptMessages` 直接挂在 tab 上（不分层） | N/A (无专门设计) |
| **Failure / Recovery** | chokidar 的 `awaitWriteFinish` 用 `stabilityThreshold: 1000ms` + `pollInterval: 500ms` 避免读取部分写。`DELETION_GRACE_MS = 1700ms` 处理 auto-updater 的 delete-and-recreate 模式：删除后 1.7s 内重建会被当成 change 而非 delete | 👍 |
| **Quality / Review** | `repo-release-governance` skill 强制每个新需求写进 `.claude/plans/*.md`，未完成保留在 README TODO，完成后同步打钩。`reverse-engineering.md` rule 规定"不修改核心逻辑代码，只补充缺失的配置和类型" | 👍 流程治理 |

## Path Dependency Assessment

- **Locking decisions**: 选择 Bun 运行时 + React/Ink — 决定了所有 polyfill 要做 `bun:bundle` 的 feature flag 兜底。选择 `strict: false` + 40+ stub 模块跳过编译错误 — 把"可运行"优先级置于"类型完整"之上，v2.0.7 仍有 ~2180 类型错误但 CLI 正常。
- **Missed forks**: 本可以做纯 Web UI（不依赖 Ink），或做 WebSocket 流而非 polling。选择了"CLI 内嵌 HTTP 服务器 + 客户端 polling"路线——简单但低效。
- **Self-reinforcement**: modelRoutes 的 env JSON fallback (`CLAUDE_CODE_MODEL_ROUTES_JSON`) 让它不依赖 settings.json 就能用，进一步降低采用门槛；但也意味着路由配置来源变多，debug 成本上升。
- **Lesson for us**: 可以直接学 modelRoutes 的 **三级匹配 + authToken 镜像 + settings/env 双来源** 设计，但要避开"配置来源过多导致难以排查"这个坑——Orchestrator 要强制 single source of truth。

## Steal Sheet

### P0 — Must Steal (4 patterns)

#### P0-1. Per-Model Route Table (modelRoutes)

**Mechanism**: `getRouteForModel(model)` 返回 `{baseURL?, apiKey?, authToken?, headers?}`。匹配优先级：精确 → 小写 → 前缀通配 (`"minimax/*"`)。配置来源优先级：`settings.json` > `env CLAUDE_CODE_MODEL_ROUTES_JSON`。非 first-party URL 时自动把 `apiKey` 镜像到 `authToken`（Bearer auth）。

```typescript
function getRouteForModel(model?: string): ModelRouteConfig | null {
  if (!model) return null
  const routes = parseModelRouteConfig()
  const exact = routes[model]; if (exact) return exact
  const lowerModel = model.toLowerCase()
  for (const [key, value] of Object.entries(routes)) {
    if (key.toLowerCase() === lowerModel) return value
  }
  for (const [key, value] of Object.entries(routes)) {
    const normalizedKey = key.toLowerCase()
    if (!normalizedKey.endsWith('*')) continue
    if (lowerModel.startsWith(normalizedKey.slice(0, -1))) return value
  }
  return null
}

function shouldMirrorRouteApiKeyToAuthToken({route, resolvedBaseURL}) {
  if (!route?.apiKey || route.authToken) return false
  return !isFirstPartyAnthropicUrl(resolvedBaseURL)  // 白名单外自动 Bearer
}
```

**Why it's good**: Orchestrator 现有 LLM 调用层是"每个 provider 一个 adapter 类"，切 provider 要改代码。modelRoutes 把 provider 压成数据配置，一行 JSON 新增 provider，CLI 不用重启。

**How to adapt**:
- 新建 `src/core/llm/model_routes.py`，读取 `config/model_routes.yaml`（或现有 settings）
- 实现 `get_route_for_model(model_id: str) -> ModelRoute | None`，三级匹配
- 在 `src/core/llm/client.py` 的请求构造处 inject `baseURL`/`headers`/`authToken`
- 新增 env fallback `ORCHESTRATOR_MODEL_ROUTES_JSON`（测试用）

**Effort**: ~3h

#### P0-2. Settings Hot Reload with Triple Debounce

**Mechanism**: chokidar 文件监听 + 三道防抖：
1. **`awaitWriteFinish`**: `stabilityThreshold: 1000ms` + `pollInterval: 500ms` 等文件写稳
2. **`consumeInternalWrite(path, 5000ms)`**: 自己写的 settings 被标记，5s 内的 change 事件被抑制
3. **`DELETION_GRACE_MS = 1700ms`**: delete 事件不立即生效，等宽限期内若有 add/change 则取消删除

```typescript
watcher = chokidar.watch(dirs, {
  depth: 0,
  awaitWriteFinish: {
    stabilityThreshold: FILE_STABILITY_THRESHOLD_MS,   // 1000
    pollInterval: FILE_STABILITY_POLL_INTERVAL_MS,     // 500
  },
  atomic: true,
})

function handleDelete(path: string): void {
  const source = getSourceForPath(path); if (!source) return
  if (pendingDeletions.has(path)) return
  const timer = setTimeout((p, src) => {
    pendingDeletions.delete(p)
    void executeConfigChangeHooks(src, p).then(results => {
      if (hasBlockingResult(results)) return  // ConfigChange hook 可阻断
      fanOut(src)
    })
  }, DELETION_GRACE_MS, path, source)
  pendingDeletions.set(path, timer)
}
```

**Why it's good**: Orchestrator 当前改 `.claude/settings.json` 或 `docker-compose.yml` 都要重启容器。三道防抖让热重载变得安全——auto-updater 的 delete-and-recreate 不会误触 reload，自己 write 也不会触发自己。

**How to adapt**:
- Python 对应：`watchdog.observers.Observer` + 自己实现 stability window
- 在 `src/core/config/watcher.py` 实现 `ConfigWatcher`：
  - `_internal_writes: dict[Path, float]` 记录内部写入时间戳
  - `_pending_deletions: dict[Path, asyncio.Task]` 管理宽限期
  - emit `config_changed` 信号给订阅者
- `src/governance/hooks.py` 增加 `config_change` hook 点位

**Effort**: ~4h

#### P0-3. CLI In-Process HTTP Observatory

**Mechanism**: Node `createServer` 启动 127.0.0.1:4310，通过 `publishWorkspaceApiSnapshot(state)` 推入最新 AppState，handler 读 `latestSnapshot` 构造响应。GET 端点 = 只读快照，POST 端点 = 控制命令（submit prompt / create pane / interrupt）。

```typescript
let latestSnapshot: AppState | null = null

export function publishWorkspaceApiSnapshot(state: AppState): void {
  latestSnapshot = state  // 主进程在 state 变更时推
}

async function handleWorkspaceRequest(req, res) {
  const url = new URL(req.url ?? '/', getWorkspaceApiBaseUrl())
  // POST 路由：submit / interrupt / panes/create / panes/switch / dialog
  if (method === 'POST' && pathname === '/api/workspace/control/submit') {
    const body = await readJsonBody(req)
    writeJson(res, 200, await submitWorkspacePrompt(body.prompt))
    return
  }
  // GET 路由：从 latestSnapshot 构造只读视图
  if (pathname === '/api/sessions/current') {
    writeJson(res, 200, {session: {...buildSessionSummary(state), panes: buildPaneSummary(state)}})
  }
  // ...
}

export function startWorkspaceApiServer(): void {
  if (serverStarted) return
  serverStarted = true
  const server = createServer(handleWorkspaceRequest)
  server.listen(getWorkspaceApiPort(), '127.0.0.1')
  server.on('error', () => {/* 端口占用时保持 CLI 可用 */})
}
```

**Why it's good**: Orchestrator 有 `dashboard/` 独立 Web 前端，但后端和 agent runtime 解耦，看 session 实时状态要查 DB + Redis。内置 HTTP 观察台让 "agent 在干什么" 可直接 `curl localhost:4310/api/sessions/current` 拿到，不需要走 DB。控制端点让外部工具（比如 hook、另一个 agent）可以注入 prompt，天然支持 agent-to-agent 场景。

**How to adapt**:
- Python 版：`aiohttp.web.Application` 或 `fastapi.FastAPI` 跑在 orchestrator 主进程内
- `src/core/observatory/server.py`：
  - `publish_snapshot(state: OrchestratorState)` 推入快照
  - GET `/api/sessions/current`、`/tasks`、`/agents`、`/transcript/:id`
  - POST `/api/control/submit`、`/interrupt`
- 启动时在 main loop 绑定端口（默认 4310），失败降级为日志 warning 不阻断
- **关键**：handler 完全 stateless，只读 `latest_snapshot`——不引入并发锁

**Effort**: ~6h (含 HTML dashboard 骨架)

#### P0-4. Per-Window 25-Field State Isolation

**Mechanism**: `SessionTabState` 一个窗口 25 个字段全隔离——transcript、todos、draftInput、inputMode、pastedContents、stashedPrompt、vimMode、isSearchingHistory、showBashesDialog、isHelpOpen、isMessageSelectorVisible、messageSelectorPreselectUuid、submitCount、conversationId、showAllInTranscript、transcriptDumpMode、transcriptSearch* ×4、model、provider、repoLabel、worktreePath、status、subagentId、unreadCount。

`updateSessionTab` 做 25 字段浅相等检查，所有字段相同则返回 `state` 原引用（React 跳过 re-render）：

```typescript
export function updateSessionTab(state, tabId, updates): SessionTabsState {
  const existing = state.tabs[tabId]; if (!existing) return state
  const nextTab = {...existing, ...updates, updatedAt: new Date().toISOString()}
  const sameTab =
    nextTab.title === existing.title &&
    nextTab.kind === existing.kind &&
    /* ... 23 more fields ... */ &&
    JSON.stringify(nextTab.pastedContents) === JSON.stringify(existing.pastedContents) &&
    JSON.stringify(nextTab.stashedPrompt) === JSON.stringify(existing.stashedPrompt) &&
    JSON.stringify(nextTab.transcriptPreview) === JSON.stringify(existing.transcriptPreview)
  if (sameTab) return state  // ← 原引用返回 = React 跳过 re-render
  return {...state, tabs: {...state.tabs, [tabId]: nextTab}}
}
```

**Why it's good**: Orchestrator 的 multi-task / multi-agent 如果未来做 pane 视图，直接面临"A agent 的 todo 串到 B agent 的窗口"问题。这套设计给了清单——25 个具体字段哪些必须按窗口隔离，哪些可以共享。另外 25 字段浅相等检查是 React + Ink 架构下减少 terminal redraw 的关键性能技巧。

**How to adapt**:
- 不是立即实施，而是作为 "orchestrator 做多窗口 TUI 的设计参考"
- 列入 `SOUL/public/prompts/orchestrator-tui-design.md`（未来占位）
- 短期：把现有 `src/tui/` 的 state 字段清单拉齐，检查哪些 "应该隔离但现在共享"

**Effort**: ~1h（整理清单，不实施）+ 后续按需 8h

### P1 — Worth Doing (4 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Format-preserving secret redaction** | `SECRET_KEY_PATTERN = /(token\|api[-_]?key\|auth[-_]?token\|secret\|password)/i` 递归遍历对象；长 value 保留 `head4***tail4` 格式，短 value 全 `***` | Orchestrator `src/security/redact.py` 加入同款正则 + 格式保留；现有 logging/dashboard 输出点套用 | 1.5h |
| **Layered config inspection `/show` commands** | `/show`、`/show:global`、`/show:user`、`/show:project`、`/show:slash` 分别展开 global / user / project / slash 命令的生效配置 + raw file 内容 + 脱敏后 JSON | Orchestrator 增加 CLI 子命令 `orch config show [--source global\|project\|local]`，调用现有 settings loader | 2h |
| **`repo-release-governance` skill 强制闭环** | 每个新需求 → `.claude/plans/*.md`；未完成 → README TODO；完成 → 打钩；user-facing → CHANGELOG + 版本字符串 + pages | Orchestrator 可写一个对应 skill（已有 `SOUL/public/prompts/rationalization-immunity.md` 可承载），强制 memory / steal report / plan 三处同步 | 1.5h |
| **Settings source tri-location (settings > env JSON > {})** | `parseModelRouteConfig()` 三源兜底：`getSettings_DEPRECATED().modelRoutes` > `process.env.CLAUDE_CODE_MODEL_ROUTES_JSON` > `{}` | Orchestrator 配置统一 fallback 模式：`config/*.yaml > env JSON > default`。测试时 env 可覆盖，生产用 yaml | 1h |

### P2 — Reference Only (3 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **Source Map 反向工程方法论** | 从 57MB `cli.js.map` 还原 1900+ TS 文件 + 40+ stub 模块 + `strict: false` | Orchestrator 不做源码还原工作，但"stub 模块撑起可运行基线"是通用的修复策略 |
| **`Ctrl+g` window leader key (zellij-style)** | window 管理前缀键 + 二级命令 `c/n/p/x/s/1-9/h/l` | Orchestrator 目前没有 TUI 多窗口，引用存档 |
| **bin/likecode shell launcher** | shell wrapper 脚本让本地项目暴露全局命令；检测 bun/CLI 存在性后 `exec bun run` | Orchestrator 已有 docker-compose 启动流，无需此模式 |

## Comparison Matrix (P0 patterns)

| Capability | learn-likecc | Orchestrator 现状 | Gap | Action |
|-----------|--------------|-------------------|-----|--------|
| **Per-model provider routing** | `getRouteForModel` 三级匹配 + apiKey→authToken 镜像 + settings/env 双源 | 无 modelRoutes 概念（grep `model_routes\|modelRoutes` 无结果）；LLM 调用层按 provider class 硬编码 | Large | **Steal** (P0-1) |
| **Config hot reload** | chokidar + awaitWriteFinish + internalWrite 5s 抑制 + deletion 1.7s grace + ConfigChange hook 前置拦截 | watchdog 在 3 处出现但非配置热重载路径；改 settings.json 需重启 | Large | **Steal** (P0-2) |
| **In-process HTTP observatory** | 127.0.0.1:4310 暴露 6 GET + 5 POST，`publishSnapshot` 推快照，handler stateless | `dashboard/server.js` 独立 Node 进程，后端观察要查 DB/Redis | Large | **Steal** (P0-3) |
| **Per-window state isolation** | `SessionTabState` 25 字段 + `updateSessionTab` 浅相等检查 | `src/tui/` 存在但无 pane/tab 隔离设计 | Medium (未来需求) | **Enhance later** (P0-4 存档) |
| **Secret redaction** | 正则 + 格式保留 | `src/security/` 已有；未验证是否覆盖所有日志输出路径 | Small | **Enhance** (P1) |
| **Layered config inspection** | `/show`、`/show:global/user/project/slash` | 无等价命令 | Medium | **Steal** (P1) |

## Triple Validation Gate (P0 patterns)

| Pattern | Cross-domain reproduction | Generative power | Exclusivity | Score |
|---------|--------------------------|------------------|------------|-------|
| **P0-1 modelRoutes** | ✓ OneAPI, Helicone, LiteLLM 都有 per-model routing | ✓ 给定新 model 名可预测命中哪条路由 | ✓ 三级匹配 + authToken 自动镜像 + first-party 白名单判定是独特组合 | **3/3** |
| **P0-2 Settings hot reload triple debounce** | ✓ Next dev server/Vite HMR 有 awaitWriteFinish；webpack 有 debounce | ✓ 能预测"删除后 1.7s 内重建"会被当成 change | ✓ internalWrite 5s + deletion 1.7s + ConfigChange hook 三层是独特组合 | **3/3** |
| **P0-3 CLI HTTP observatory** | ✓ Node `--inspect`, Python `debugpy`, Grafana Agent 都有内置 server | ✓ 新加状态字段，API 能立即暴露 | 中等 — "localhost + snapshot"不够独特，但 "publish + stateless handler + 控制端点"组合有特色 | **2.5/3** |
| **P0-4 Per-window 25-field isolation** | ✓ tmux/zellij/iTerm2 都做窗口级状态 | ✓ 新增输入模式加到 TabState 即隔离 | ✓ 把 vim mode + search state + conversationId + submitCount 全部 per-tab 少见 | **3/3** |

## Knowledge Irreplaceability Assessment

| Pattern | Categories hit | Reasoning |
|---------|---------------|-----------|
| **P0-1 modelRoutes** | Judgment heuristics, Hidden context | "non-first-party URL 自动镜像 apiKey→authToken" 是踩过 Bearer vs API Key 兼容坑后的判断；isFirstPartyAnthropicUrl 白名单是隐性契约 |
| **P0-2 Settings hot reload** | Pitfall memory, Failure memory, Judgment heuristics | DELETION_GRACE_MS 注释里直接写"handles delete-and-recreate pattern during auto-updates"——这是真踩过坑；5s internalWrite 窗口是经验值 |
| **P0-3 HTTP observatory** | Unique behavioral patterns | "发布-订阅快照 + stateless handler + 读写端点并存"是一种明确的架构选择 |
| **P0-4 Per-window isolation** | Hidden context, Pitfall memory | 25 个字段里的 `messageSelectorPreselectUuid`/`transcriptSearchCount`/`conversationId` 这种细粒度隔离是典型的"串味 bug 修完后沉淀"的清单 |

全部 P0 命中 2+ 类别，符合架构级偷师。

## Gaps Identified

| Dimension | Their coverage | Our gap | Priority |
|-----------|----------------|---------|----------|
| Security/Governance | 配置变更前置 hook 拦截；格式保留式脱敏 | Orchestrator 有 hook 系统但无 config-change 专属 hook；脱敏未必覆盖所有日志点 | P1 |
| Execution/Orchestration | Per-window 状态隔离 + sessionTabs metadata 持久化 | 未做多窗口 TUI；多 agent 并行时 state 合并策略粗糙 | 未来 |
| Failure/Recovery | chokidar awaitWriteFinish + deletion grace 防 partial write | 配置文件监听非核心路径；没有 "writing window" 抑制机制 | P0 (随 P0-2) |
| Quality/Review | `repo-release-governance` skill 三处同步（plan/README/CHANGELOG） | memory/steal report 有同步约定但缺强制机制 | P1 |

Memory/Learning 和 Context/Budget 维度此项目不做深入——**N/A 原因**：learn-likecc 是 CLI 产品化项目，不是记忆/压缩系统，这两维度无内容可窃。

## Adjacent Discoveries

- **Bun `bun:bundle` feature flag polyfill 模式**：入口点用 `const feature = (_name) => false` 关掉所有未实现 feature。对 Orchestrator 未来接 Bun 生态有参考价值（当前无此需求）。
- **`cli.js.map` 57MB → 1900 TS 文件**的还原流程：SourceMap + 扫 import 重建 package.json → `strict: false` 撑过编译 → stub 模块兜底缺失 import。*这是"逆向任何公开 minified JS 产品"的通用方法论*。
- **`SessionLayoutMode` 三态（single/tabs/panes）**：比二态（on/off）更灵活，适合"渐进增强"——先支持 tabs 再升 panes 时不用改接口。Orchestrator 未来多 agent 视图可借鉴。
- **`awesome-*.md` 文件分主题组织资料索引**（awesome-agent, awesome-rag, awesome-skills, awesome-claude-code-source）：learn-likecc 用 README 之外的 awesome 文件做主题索引，避免 README 膨胀。

## Meta Insights

1. **"源码还原 + 产品化增强"的杠杆率**：learn-likecc 最有价值的不是"还原了 Claude Code 源码"（大家都能做），而是建立了一个**可持续改的底座**后，迭代出 modelRoutes / hot reload / observatory 这些具体增强。还原 = 地基，增强 = 楼层。Orchestrator 已有地基，应该更关注"下一批增强"。

2. **"localhost 内置 HTTP 观察台"是 AI Agent 领域正在形成的共识**：Claude Code 的 hidden features 里出现过（见 `R35-claude-code-ecosystem` 等报告），learn-likecc 独立实现。出现两次不同团队各自发明 = 真需求信号。Orchestrator 应该把它列入 P0。

3. **"三道防抖"是"安全热重载"的事实标准**：单纯文件监听不够——`awaitWriteFinish`（防部分写）+ `internalWrite 抑制`（防自触发）+ `deletion grace`（防 delete-and-recreate 误报），三者缺一会在 auto-updater 场景下炸。Orchestrator 做配置热重载别只用 watchdog 的原始事件流。

4. **per-window 25 字段清单是 multi-agent UI 的"防串味备忘录"**：不是教你"要做 pane 隔离"，而是给你一个"哪些字段串味会让用户抓狂"的实战清单。即使 Orchestrator 不做 TUI pane，这个清单对"两个 agent 共享一个任务对象但各有 UI 状态"的场景也直接适用。

5. **治理 skill 的冗余约定**（`repo-release-governance` 把 plan/README/CHANGELOG 同步固化为 skill）—— 说明即使在一个作者为主的项目，也不能靠"记得更新"。Orchestrator 的 memory/steal report/plan 同步应该走同款强制 skill 路径。
