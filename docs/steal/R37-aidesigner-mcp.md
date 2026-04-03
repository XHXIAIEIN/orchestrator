# Round 37 — AI Designer MCP

| Field | Value |
|-------|-------|
| Date | 2026-04-03 |
| Source | [aidesigner.ai/docs/mcp](https://www.aidesigner.ai/docs/mcp) |
| Stars | N/A (SaaS product) |
| Category | MCP-as-Distribution, Design-as-Service |

## Source 概述

AI Designer MCP 是一个 HTTP-based MCP server，让任何 MCP-compatible AI 编辑器（Claude Code / Cursor / Codex / VS Code Copilot / Windsurf）能直接生成和迭代 production-ready UI 设计。核心创新不是 UI 生成本身，而是 **用 MCP 协议作为产品分发层**。

### 架构亮点

1. **HTTP MCP Server** — 单个 `https://api.aidesigner.ai/api/v1/mcp` endpoint，所有客户端共用
2. **Multi-Host Installer** — `npx init [host]` 自动注入 `.mcp.json` + agents + skills + commands
3. **Agent + Skill + Command 三件套** — 一次 init 全部就位
4. **Artifact Run Storage** — `.aidesigner/runs/[timestamp]/` 结构化输出（HTML + metadata + preview + adoption）
5. **repo_context 自动注入** — 自动分析项目框架/样式/组件，作为 context 传入每次调用
6. **generate → refine 状态循环** — 通过 run_id 链接迭代
7. **Doctor 自诊断** — 验证 config / connectivity / auth
8. **Design Modes** — inspire / clone / enhance 不同操作模式

## 偷师提取

### P0 — 直接实施

#### 1. Orchestrator Core MCP Server
**来源**: HTTP MCP Server 模式
**当前差距**: `desktop_use/mcp_server.py` 只暴露低级 GUI 操作（screenshot/click/type），而高价值工具（dispatch_task / query_status / wake_claude / read_file）只能通过 TG bot 的 chat channel 访问
**偷什么**: 把 orchestrator 核心能力包装成 HTTP MCP server，让 Claude Code 能直接：
- `dispatch_task` — 派单给 Governor
- `query_status` — 查系统健康/采集器/任务状态
- `get_recent_logs` — 读最近日志
- `trigger_collection` — 手动触发采集
- `search_memory` — 语义搜索 Qdrant 记忆
**实施路径**: 复用 `chat/tools.py` 的 tool definitions，加 FastMCP HTTP transport
**价值**: Claude Code 直接操控 orchestrator，不再需要绕道 TG bot

#### 2. Doctor Self-Diagnostic
**来源**: `npx ... doctor` 命令
**当前差距**: 无结构化健康检查，`/status` skill 只读 docker ps + 最近采集
**偷什么**: 结构化诊断命令，检查项：
- Docker container running ✓/✗
- Database accessible + size
- Qdrant connection + collections
- Each collector health (last run time, error count)
- Each channel status (TG bot connected, WeChat alive)
- GPU available (nvidia-smi)
- Disk space
- Recent error rate
**输出**: pass/warn/fail per component，一目了然
**实施路径**: `/doctor` skill 或 MCP tool

#### 3. System Snapshot Auto-Injection (repo_context 模式)
**来源**: AI Designer 的 `repo_context` 参数 — 每次调用自动附带项目元数据
**当前差距**: Governor 派单时不附带系统快照，agent 冷启动需要自己去查状态
**偷什么**: 每次 governor dispatch 自动附带 system_context：
```json
{
  "container_status": "up 5h",
  "db_size": "16M",
  "recent_errors": 0,
  "active_channels": ["telegram"],
  "last_collection": "2026-04-03T14:30:00",
  "collector_health": {"steam": "ok", "github": "ok", "bilibili": "warn"},
  "pending_tasks": 2
}
```
**价值**: Agent 不再冷启动，立即有全局视野

### P1 — 中期考虑

#### 4. Stateful Refinement Loop
**来源**: generate → refine via run_id
**当前差距**: Governor 任务是 fire-and-forget，没有基于 run_id 的迭代链
**偷什么**: 用户通过 TG 说"上次的分析再深入一点"，系统自动找到上一个 run_id，把结果 + 新指令一起传给 agent
**依赖**: run_id 已存在于 DB，需要在 channel 层加 refinement routing

#### 5. Analysis Adoption Brief
**来源**: `adoption.json` — 设计输出附带框架适配指南
**偷什么**: Governor 输出分析报告时，附带 `recommendation.json`：
```json
{
  "findings": ["Steam 采集器连续 3 次超时"],
  "actions": [
    {"priority": "high", "action": "检查 Steam API rate limit", "owner": "auto"},
    {"priority": "medium", "action": "增加重试间隔", "owner": "manual"}
  ],
  "auto_fixable": true
}
```

#### 6. Operation Modes
**来源**: inspire / clone / enhance 模式
**偷什么**: Governor dispatch 支持模式参数：
- `quick` — 快速扫描，2 分钟内出结果
- `deep` — 深度审计，完整分析链
- `compare` — 对比模式，和上次结果比较
- `fix` — 自动修复模式，发现问题直接修

### P2 — 参考存档

#### 7. Multi-Host Installer
`npx init [host]` 单命令安装到任意 AI 编辑器。如果 orchestrator 变成产品，这是分发模式。目前单用户，ref-only。

#### 8. Credit/Usage as MCP Tool
Token 用量/成本追踪暴露为 MCP tool。已有 `cost_tracking.py`，未来可通过 MCP 暴露。

#### 9. OAuth + API Key Dual Auth
Interactive OAuth for humans, API key for CI/CD。本地系统不需要，ref-only。

## 与现有系统的映射

| AI Designer 概念 | Orchestrator 对应 | 差距 |
|---|---|---|
| HTTP MCP Server | `desktop_use/mcp_server.py` (低级) | 核心能力未暴露 |
| generate_design | `dispatch_task` (chat tool) | 只能通过 TG |
| refine_design | 无 | 无 refinement loop |
| repo_context | 无 | Agent 冷启动 |
| .aidesigner/runs/ | `_runs_mixin.py` + DB | 已有 run 概念 |
| doctor | `/status` skill | 非结构化 |
| Agent + Skill + Command | `.claude/` 全套 | ✅ 已有 |
| Design Modes | Governor priority | 无 mode 参数 |

## 实施优先级

| # | Pattern | Priority | Effort | 依赖 |
|---|---------|----------|--------|------|
| 1 | Core MCP Server | P0 | Medium | FastMCP + chat/tools.py |
| 2 | Doctor Diagnostic | P0 | Low | 无 |
| 3 | System Snapshot Injection | P0 | Low | query_status 现有逻辑 |
| 4 | Refinement Loop | P1 | Medium | run_id + channel routing |
| 5 | Adoption Brief | P1 | Low | Governor output format |
| 6 | Operation Modes | ~~P1~~ **Done** | Low | Governor dispatch params |
| 7 | Multi-Host Installer | P2 | — | ref-only |
| 8 | Credit as MCP Tool | P2 | — | ref-only |
| 9 | Dual Auth | P2 | — | ref-only |

**总计**: 9 模式 (3 P0 / 3 P1 / 3 P2)
