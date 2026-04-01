# Agentlytics 偷师报告

**仓库**: https://github.com/f/agentlytics
**作者**: [@f](https://github.com/f) (Fatih Kadir Akın)
**定位**: 跨 16 种 AI 编辑器的本地统一分析仪表盘
**技术栈**: Node.js + Express + SQLite (WAL) + React + Vite；Deno 沙盒 CLI 作为轻量替代
**日期**: 2026-04-01

---

## 项目概述

Agentlytics 用一条命令 (`npx agentlytics`) 把 Cursor、Windsurf、Claude Code、VS Code Copilot、Gemini CLI、Codex、Kiro 等 16 种 AI 编码工具的会话历史汇聚到一个本地 SQLite 数据库，然后用 Express REST API + React SPA 呈现仪表盘。核心价值：**跨编辑器的 AI 使用审计 + 成本估算 + 团队共享（Relay）**。

### 核心架构

```
editors/*.js adapters → cache.js (SQLite) → server.js (REST) → React UI
                                          → relay-server.js (团队模式)
                                          → mcp-server.js (MCP 协议暴露)
                                          → share-image.js (SVG 分享卡)
                                          → mod.ts (Deno 沙盒 CLI)
```

---

## 可偷模式清单

### 1. Editor Adapter Interface（编辑器适配器接口）

**优先级**: P0

**描述**: 每个编辑器是一个独立的 JS 模块（`editors/cursor.js`、`editors/claude.js` 等），统一导出 6 个接口：

| 接口 | 职责 |
|------|------|
| `name` | 编辑器标识 |
| `getChats()` | 返回会话列表（标准化字段：id, title, folder, createdAt, updatedAt） |
| `getMessages(chat)` | 返回消息列表（标准化字段：role, content, _model, _inputTokens, _toolCalls） |
| `getUsage()` | 返回订阅/配额信息 |
| `getArtifacts(folder)` | 扫描项目级配置文件 |
| `getMCPServers()` | 收集 MCP 服务器配置 |

`editors/index.js` 做聚合——遍历所有适配器，try-catch 静默跳过失败的，确保一个适配器挂掉不影响整体。

**代码证据**:

```javascript
// editors/index.js — 防御性聚合
async function getAllChats() {
  const allChats = [];
  for (const editor of editors) {
    try {
      const chats = await editor.getChats();
      allChats.push(...chats);
    } catch (e) { /* 静默跳过 */ }
  }
  return allChats.sort((a, b) => b.updatedAt - a.updatedAt);
}
```

**偷法**: Orchestrator 目前的数据采集器是按功能模块组织的（Telegram bot、QQ 音乐等），没有统一的采集器接口。可以抽象出一个 `Collector` 接口协议：

```
interface Collector {
  name: string
  collect(): AsyncIterable<CollectedItem>
  getStatus(): CollectorStatus
  getMeta(): CollectorMeta
}
```

每个数据源（Telegram、QQ 音乐、浏览器历史等）实现这个接口，`collectors/index.js` 做防御性聚合。这比现在的 ad-hoc 采集稳健得多。

---

### 2. Multi-Pass Model Name Normalization（多遍模型名归一化）

**优先级**: P0

**描述**: `pricing.js` 中的 `normalizeModelName()` 用多遍策略把各种奇葩的模型名映射到统一 key：

1. **精确匹配**: 直接查 pricing.json
2. **去除 provider 前缀**: `anthropic/claude-3-5-sonnet` → `claude-3-5-sonnet`
3. **去除日期后缀**: `claude-3-5-sonnet-20241022` → `claude-3-5-sonnet`
4. **去除修饰词**: `-latest`, `-preview`, `-experimental`
5. **模糊前缀匹配**: 最长 key 优先

每个 pass 之间有 early return，命中就停。

**代码证据**:

```javascript
// pricing.js — normalizeModelName 多遍策略
function normalizeModelName(raw) {
  let name = raw.toLowerCase().trim();
  // Pass 1: 精确匹配
  if (pricing[name]) return name;
  // Pass 2: 去 provider 前缀
  name = name.replace(/^(anthropic|openai|google)\//,'');
  if (pricing[name]) return name;
  // Pass 3: 去日期后缀
  name = name.replace(/-\d{8}$/,'');
  if (pricing[name]) return name;
  // Pass 4: 模糊前缀，最长匹配
  const candidates = Object.keys(pricing).filter(k => name.startsWith(k));
  return candidates.sort((a,b) => b.length - a.length)[0] || null;
}
```

**偷法**: Orchestrator 的 token 计费和模型路由也面临模型名混乱问题（Claude Code 内部用 `MODEL_CLAUDE_3_5_SONNET` 枚举，API 用 `claude-3-5-sonnet-20241022`，用户可能写 `sonnet`）。直接偷这个多遍归一化模式，作为 `utils/model-normalize.js`。

---

### 3. SSE Progress Streaming（SSE 进度流）

**优先级**: P0

**描述**: `cache.js` 的 `scanAllAsync()` 用 generator yield 实现异步扫描，配合 `server.js` 的 `/api/refetch` SSE endpoint，实现扫描进度实时推送到前端。

关键设计：扫描循环每处理一个编辑器就 yield 一次进度事件，Express 端用 SSE 推给浏览器。前端能实时看到"正在扫描 Cursor... 发现 234 个会话"这样的进度。

**代码证据**:

```javascript
// cache.js — async generator 进度流
async function* scanAllAsync() {
  for (const editor of editors) {
    yield { type: 'scanning', editor: editor.name };
    const chats = await editor.getChats();
    yield { type: 'found', editor: editor.name, count: chats.length };
    // ... 批量插入
    yield { type: 'cached', editor: editor.name, count: inserted };
  }
  yield { type: 'done', total };
}

// server.js — SSE 推送
app.get('/api/refetch', (req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/event-stream' });
  (async () => {
    for await (const event of scanAllAsync()) {
      res.write(`data: ${JSON.stringify(event)}\n\n`);
    }
    res.end();
  })();
});
```

**偷法**: Orchestrator 的 Dashboard 目前用轮询看采集状态。可以改为 SSE：采集器运行时用 generator yield 进度事件，Dashboard server 通过 SSE 实时推送。用户体验从"刷新看结果"变成"看着数字跳"。

---

### 4. Pricing Sync Pipeline（定价同步管道）

**优先级**: P1

**描述**: `sync-pricing.js` 从 models.dev API 拉取最新模型定价，和本地 `pricing.json` 做三方 diff（新增/更新/删除），默认 dry-run 只展示差异，`--write` 才真写入。

关键设计点：
- **保留手动条目**: 远端没有的本地条目不会被删
- **保留缓存价格**: 远端缺少 cache_read/cache_write 字段时保留本地值
- **lastVerified 时间戳**: 每次 write 更新审计时间

**代码证据**:

```javascript
// sync-pricing.js — 智能合并策略
if (remotePrice && !remotePrice.cache_read && localPrice?.cache_read) {
  merged.cache_read = localPrice.cache_read;  // 保留本地缓存价格
  merged.cache_write = localPrice.cache_write;
}
meta.lastVerified = new Date().toISOString();
```

**偷法**: Orchestrator 还没有成本追踪。当我们加入 token 成本估算时，可以直接借鉴这套模式：
1. 维护一个 `pricing.json`（或从 Agentlytics 直接 fork）
2. 写一个 `sync-pricing` 脚本定期从 models.dev 拉取
3. dry-run + write 分离，手动条目保留

---

### 5. Cross-Editor MCP Discovery（跨编辑器 MCP 发现）

**优先级**: P1

**描述**: `editors/base.js` 的 `parseMcpConfigFile()` + `queryMcpServerTools()` 实现了跨编辑器的 MCP 服务器发现和工具枚举。

流程：
1. 从每个编辑器的配置文件（`~/.cursor/mcp.json`、`~/.claude.json` 等）解析 MCP 服务器定义
2. 对每个服务器发起 JSON-RPC 2.0 `tools/list` 请求（支持 HTTP/SSE 和 stdio 两种传输）
3. stdio 传输的三步握手：initialize → initialized notification → tools/list
4. 10 秒超时，失败静默跳过

`server.js` 进一步做了 **MCP tool call 归因**——把会话中的 tool call 匹配到具体的 MCP server，处理四种编辑器特有的命名前缀：

```
Windsurf: mcp{N}_{tool}
Cursor:   mcp_{ServerName}_{tool}
Claude:   mcp__server__tool
其他:     直接匹配
```

**代码证据**:

```javascript
// base.js — stdio 三步握手
async function queryMcpServerTools(server) {
  // 1. initialize
  proc.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'initialize',id:1,...}));
  // 2. initialized notification
  proc.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized'}));
  // 3. tools/list
  proc.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'tools/list',id:2}));
}
```

**偷法**: Orchestrator 用 MCP 但没做跨工具的 MCP 发现。如果我们要做"你装了多少个 MCP server、哪些工具被用了"的审计，这套 discovery + attribution 模式可以直接搬。特别是 tool call 归因的四种前缀匹配——我们的 Claw 审批系统可以用来判断"这个 tool call 来自哪个 MCP server"。

---

### 6. SVG Share Card Generator（SVG 分享卡生成器）

**优先级**: P1

**描述**: `share-image.js` 纯 JS 生成 1200×675 SVG 统计卡片，不依赖任何图形库。包含：
- KPI 行（sessions / tokens / streak / cost）
- 双列 section（editors / costs / peak hours / top models）
- 小时热力条（sparkline with intensity coloring）
- 主题系统（dark/light）
- HTML 转义防注入

**关键设计**: 不用 canvas、不用 puppeteer、不用任何图形依赖——纯模板字符串拼 SVG。零依赖、可在任何 Node.js 环境运行。

**偷法**: Orchestrator 的 Telegram bot 目前发纯文本统计。可以用同样的 SVG 模板方式生成好看的统计卡片，通过 Telegram bot 发图片。零依赖 SVG 生成比 puppeteer 截图轻量 100 倍。

---

### 7. Relay Team Sync Protocol（团队中继同步协议）

**优先级**: P2

**描述**: 完整的团队会话共享系统：

```
本地机器 → relay-client.js → POST /relay/sync → relay-server.js (SQLite)
                                                    ↓
                                                mcp-server.js (MCP 暴露)
                                                    ↓
                                                AI 客户端可查询团队成员的会话
```

- HMAC-SHA256 认证（虽然 key 是硬编码的 "agentlytics-relay"）
- 30 秒定时同步
- 用户合并（`/relay/merge-users`）
- MCP 暴露 4 个工具让 AI 客户端能查询团队数据

**偷法**: 这是一个有趣的方向——如果 Orchestrator 未来要做多机协同（比如 Mac Mini + Windows 主机），可以参考这个 relay 协议的简洁设计。但认证要比硬编码 HMAC key 强。

---

### 8. Dual-Runtime Architecture（双运行时架构）

**优先级**: P2

**描述**: `mod.ts` 是完整的 Deno 版本，不依赖 SQLite FFI，纯文件读取。用 Deno 的权限沙盒（`--allow-read --allow-env`）确保安全。

关键区别：
- Node 版本走 SQLite，能读 Cursor 的 SQLite 数据库
- Deno 版本只读文件系统，跳过需要 SQLite 的编辑器
- 两者共享相同的消息标准化逻辑

**偷法**: 参考价值。如果 Orchestrator 的某些功能需要在沙盒环境运行（比如用户提交的脚本），可以考虑 Deno 沙盒作为执行层。

---

## 架构亮点

### 1. 极致的"零配置"体验
一条 `npx agentlytics` 完成所有事：检测已安装的编辑器、扫描会话、建 SQLite 缓存、构建 React UI、启动服务器。用户不需要配置任何东西。这个 DX 设计值得学习——Orchestrator 的 `docker compose up` 虽然简单，但比 `npx` 一条命令还是重。

### 2. 防御性聚合模式
整个系统的哲学是"部分失败不影响整体"。每个适配器 try-catch 独立、MCP 查询 10 秒超时静默跳过、用户未安装的编辑器自动跳过。这使得 16 个适配器中任意几个挂掉，其余照常工作。

### 3. 成本估算的多层降级
token → model 的归因采用 4 级降级：
1. 消息级元数据直接标注 model
2. 会话级主导模型（多数票）
3. 字符数估算（~4 chars/token）
4. 数据源级默认模型

不会因为一条消息缺元数据就放弃整个会话的成本估算。

### 4. SQL Viewer 开放查询
`/api/query` 端点允许用户对 SQLite 数据库执行任意 SELECT 查询（限制为只读操作）。这给高级用户自助分析的能力，而不需要导出数据。

---

## 与 Orchestrator 的差距分析

### 他们有而我们没有的

| 能力 | Agentlytics | Orchestrator |
|------|-------------|--------------|
| 跨编辑器会话聚合 | 16 个编辑器适配器 | 无（只追踪自己的会话） |
| Token 成本估算 | 完整的定价库 + 多层降级 | 无 |
| SVG 分享卡 | 零依赖生成 | 无（Telegram 发纯文本） |
| MCP tool call 归因 | 四种前缀模式匹配 | 无 |
| SQL 自助查询 | 开放 SELECT | 无 |
| 团队共享 (Relay) | 完整协议 | 无 |
| 活动热力图 | 按小时/星期可视化 | Dashboard 有但粒度粗 |

### 我们有而他们没有的

| 能力 | Orchestrator | Agentlytics |
|------|-------------|-------------|
| Agent 编排 | 三省六部 + sub-agent 派单 | 无（纯分析，不执行） |
| 多通道审批 | Claw + TG + WX | 无 |
| SOUL 系统 | 人格 + 记忆 + 反思 | 无 |
| 桌面自动化 | desktop_use + cvui | 无 |
| 数据采集器 | Telegram/浏览器/QQ音乐 | 只采集编辑器数据 |
| Hook 系统 | guard.sh + audit.sh | 无 |
| Docker 部署 | 完整 compose 栈 | npx 单进程 |

### 可以互补的地方

1. **Agentlytics 的编辑器适配器 → Orchestrator 的数据源**: 我们可以直接用 Agentlytics 的 SQLite 缓存作为一个数据源，在 Dashboard 展示跨编辑器的 AI 使用情况
2. **Orchestrator 的 Agent 能力 → Agentlytics 的 Roadmap**: 他们计划加"LLM-powered session summaries"，我们已经有完整的 Agent 框架可以做这件事
3. **定价数据共享**: pricing.json 可以直接复用，省去维护成本

---

## 实施优先级

| # | 模式 | 优先级 | 工作量 | 收益 |
|---|------|--------|--------|------|
| 1 | Editor Adapter Interface | P0 | 中 | 统一采集器接口，减少 ad-hoc 代码 |
| 2 | Multi-Pass Model Normalization | P0 | 小 | token 计费的基础设施 |
| 3 | SSE Progress Streaming | P0 | 小 | Dashboard 实时反馈 |
| 4 | Pricing Sync Pipeline | P1 | 中 | 成本追踪功能的基础 |
| 5 | Cross-Editor MCP Discovery | P1 | 中 | 审计 MCP 生态 |
| 6 | SVG Share Card | P1 | 小 | Telegram bot 视觉升级 |
| 7 | Relay Team Sync | P2 | 大 | 多机协同 |
| 8 | Dual-Runtime Architecture | P2 | 大 | 沙盒执行参考 |
