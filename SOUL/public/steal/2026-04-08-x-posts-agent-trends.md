# R45d — X Posts Agent Trends: KV Cache / Knowledge Wiki / WeClaw / Skill Composition

**Sources**:
- @minlibuilds/2041178722230030384 (KV Cache 深度分析)
- @karpathy/2039805659525644595 (LLM 个人知识库 Pipeline)
- @idoubicc/2040821048577565144 (WeClaw — WeChat-to-Agent Bridge)
- @shao__meng/2041312035250586056 (Agent Skills 四件套推荐)
- https://github.com/fastclaw-ai/weclaw (1173⭐, Go, MIT)
**Date**: 2026-04-08 | **Category**: Survey + Module (WeClaw deep dive)

## TL;DR

四条 X 帖子共同指向一个趋势：**Agent 从"能用"走向"省钱 + 互联 + 自治"**。KV Cache 优化揭示 session 复用的 3-5 倍成本差异；Karpathy 的知识库 pipeline 证明 1M context 下 raw→wiki→lint 闭环比 RAG 更简单；WeClaw 用 6299 行 Go 实现了三层协议桥接 (ACP/CLI/HTTP) + 自动 agent 发现 + 多 agent 广播，是 Channel 层的直接参考目标；Skill 四件套（brainstorm→spec→tdd→browser-debug）构成闭环，验证了我们的 skill 组合方向。

## 架构概览（WeClaw 深度拆解）

```
WeChat ←→ iLink API ←→ WeClaw Core ←→ Agent Layer
                           │
                    ┌──────┼──────────────┐
                    │      │              │
              ACP Agent  CLI Agent   HTTP Agent
              (stdio     (spawn      (OpenAI-compat
               JSON-RPC)  per msg)    chat/completions)
                    │
          ┌────────┼────────┐
          │        │        │
       claude    codex    cursor/kimi/gemini/...
```

**核心模块** (6299 LOC Go):
- `config/detect.go` — 自动发现本地 agent 二进制 + 能力探针 (commandProbe 3s timeout)
- `agent/agent.go` — Agent interface: `Chat()` / `ResetSession()` / `SetCwd()`
- `agent/acp_agent.go` — ACP 长驻进程，JSON-RPC 2.0 over stdio，session/thread 复用
- `agent/cli_agent.go` — CLI spawn per message，stream-json 解析，session resume
- `agent/http_agent.go` — OpenAI-compatible，客户端维护 history
- `messaging/handler.go` — 消息路由：`@agent msg` / 多 agent 广播 / `/cwd` / `/new`

## Steal Sheet

### P0 — Must Steal (4 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| **三层协议桥接 (ACP > CLI > HTTP)** | Agent interface 统一三种通信方式；ACP 复用进程和 session（最快），CLI spawn per msg（兼容），HTTP OpenAI-compat（远程）。优先级递降自动选择 | Channel 层只有 Claude API 直调 + Remote Trigger (Claude Code session)。无 ACP 协议支持，无多 runtime 抽象 | `src/channels/agent_bridge.py`: AgentBridge ABC + ACP/CLI/HTTP 三实现，detect_agents() 自动发现 | ~4h |
| **Agent 自动发现 + 能力探针** | `DetectAndConfigure()` 遍历候选列表，`lookPath()` (PATH + login-shell fallback)，`commandProbe()` 3s 超时试探。零配置开箱即用 | 无。agent 路由硬编码在 chat engine 和 governor dispatcher 里 | `src/channels/agent_discovery.py`: scan PATH for claude/codex/gemini binaries，probe ACP capability，populate config | ~2h |
| **多 Agent 广播** | `@cc @cx hello` 解析多 @ 前缀，`broadcastToAgents()` goroutine 并行 dispatch，先到先回复，每条回复带 `[agent_name]` 前缀 | Channel 层只能发给单个 model (intent-based routing)。无"同一问题问多个 agent 对比"能力 | Chat engine 添加 multi-agent 路由：解析 `@cc @cx` 语法，asyncio.gather 并行调用，结果带 agent 标签分别回复 | ~3h |
| **Session 复用 vs 缓存效率** | ACP 模式复用 session ID (同一进程内保持 KV cache)；CLI 模式用 `--resume sessionID` 恢复；KV Cache 分析显示同会话连续对话 vs 频繁新建 = 3-5x 成本差异 | Agent SDK dispatch 每次创建新 conversation (无 session 复用)；boot.md 编译偶尔变更 system prompt 破坏缓存前缀 | ① Agent SDK 调用加 session_pool，同 user+agent 复用 conversation ② boot.md 编译保持前缀稳定（变更追加到尾部） | ~3h |

### P1 — Worth Doing (5 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Karpathy Wiki-Lint 闭环** | raw data → LLM 编译成 .md wiki (带摘要+反向链接) → LLM Linting (一致性检查、建议新文章) → 归档回 wiki | SOUL/memory 加自动健康检查 agent：定期扫描 memory 文件，标记过时 impression 记忆，检测冲突，建议合并/删除 | ~4h |
| **Slash Command 体系** | `/new` `/cwd` `/info` `/help` + agent alias 系统 (`/cc` = claude, `/cx` = codex)，自定义 alias 从 config 读取 | Channel slash command 已有 `/run` `/approve` `/wake`，但缺少 agent 切换语法。加 `/agent` `/cwd` 命令 | ~2h |
| **Permission Auto-Allow** | `handlePermissionRequest()` 自动找 "allow" option 并回复，agent 无需人工确认即可执行工具 | 我们的 approval gateway 已有 yolo 模式。但 ACP 场景下可参考：对 sub-agent 的 tool call 做分级 auto-allow | ~2h |
| **Markdown→PlainText + Media 提取** | agent 回复的 markdown 转 WeChat 可读纯文本；`ExtractImageURLs()` 从回复中提取图片 URL 自动下载转发 | Telegram sender 已有 markdown 支持，但缺少"从 agent 回复提取媒体自动发送"逻辑 | ~2h |
| **Agent Cwd 切换** | `/cwd /path` 运行时切换所有 agent 工作目录，`SetCwd()` 接口统一 | Wake session 已有 work_dir，但不支持运行时动态切换。加 `/cwd` 到 channel commands | ~1h |

### P2 — Reference Only (3 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **Codex App-Server 双协议** | 同时支持 legacy ACP 和 codex app-server (thread/turn/start 模型)，`detectACPProtocol()` 自动识别 | 我们不直接对接 Codex runtime，走 Agent SDK 封装 |
| **CDN AES-128-ECB 加密媒体** | WeChat CDN 媒体需要 AES 解密才能转存，`DownloadFileFromCDN()` | WeChat 特有实现，iLink API 层已处理 |
| **Skill 四件套闭环** | brainstorm → write-prd → tdd → agent-browser 构成完整开发流 | 已有 brainstorming + tdd skill，agent-browser 部分由 desktop_use 覆盖 |

## Comparison Matrix (P0 Patterns)

| Capability | WeClaw | Orchestrator | Gap | Action |
|-----------|--------|-------------|-----|--------|
| Agent 通信协议 | ACP/CLI/HTTP 三层 + 自动降级 | Claude API 直调 + Remote Trigger | **Large** — 无协议抽象层 | Steal: 新建 agent_bridge 模块 |
| Agent 发现 | PATH scan + login-shell + probe | 硬编码路由 | **Large** — 零自动发现 | Steal: detect_agents() |
| Multi-agent 路由 | @cc @cx 并行广播 | Intent-based 单模型路由 | **Large** — 无广播能力 | Steal: multi-agent syntax |
| Session 复用 | ACP session pool + CLI resume | 每次新建 conversation | **Medium** — 浪费 token | Steal: session_pool |
| Slash commands | /new /cwd /info /help + alias | /run /approve /wake | **Small** — 缺 agent 切换 | Enhance: 加几个命令 |
| 消息去重 | sync.Map + 5min TTL | _msg_id_cache + 60s TTL | **None** | Skip |
| Media 处理 | 图片/语音/视频/文件全支持 | 图片/语音/文件支持 | **Small** | Skip |

## Gaps Identified (六维扫描)

| Dimension | Gap |
|-----------|-----|
| **Execution / Orchestration** | 无多 agent 协议抽象层。WeClaw 的 Agent interface + 三层实现是干净的可偷模板 |
| **Context / Budget** | Session 不复用导致 KV cache 浪费。MinLi 的分析量化了 3-5x 差异 |
| **Memory / Learning** | 缺少 memory lint 能力。Karpathy 的 wiki-lint 模式可直接用于 SOUL/memory 健康检查 |
| **Security / Governance** | WeClaw `handlePermissionRequest()` 无条件 auto-allow 是安全隐患。我们的 approval gateway 更好 |
| **Failure / Recovery** | WeClaw 的 `acpStderrWriter` 捕获最后一行错误 + hint 机制值得学习（如 claude 不支持 ACP 时给明确提示） |
| **Quality / Review** | 两边都缺。WeClaw 无 eval loop；我们有 clawvard 但未集成到 channel 层 |

## Adjacent Discoveries

1. **ACP 协议正在成为事实标准** — WeClaw 支持 13+ agent (claude/codex/cursor/kimi/gemini/opencode/openclaw/pi/copilot/droid/iflow/kiro/qwen)，全部走 ACP 或 CLI。这意味着 Orchestrator 如果支持 ACP，可以桥接任何本地 agent
2. **login-shell PATH fallback** — `lookPath()` 先试 `exec.LookPath`，失败后 `zsh -lic "which binary"`。解决 nvm/mise 等 version manager 只在 interactive shell 注册 PATH 的问题。我们的 sub-agent dispatch 可能也有这个隐性 bug
3. **OpenClaw Gateway 协议** — WeClaw 支持 openclaw 的 WebSocket gateway + HTTP 转换，是一个"本地 agent → 远程 gateway → 多协议" 的参考架构
4. **Sidecar 文件模式** — 图片保存时同时写 `.sidecar.md`（UUID + metadata），类似 DocMason 的 workflow.json sidecar。文件+元数据 sidecar 正在成为 agent-native 的标准模式

## Meta Insights

1. **Agent 桥接层是下一个基础设施战场** — 从 WeClaw 支持 13 种 agent 可以看到：未来不是"用哪个 agent"的问题，而是"如何让所有 agent 互联互通"。Orchestrator 的 Channel 层需要从"消费 Claude API"进化到"桥接任意 agent"
2. **KV Cache 意识应该是系统级设计约束** — MinLi 的数据（3-5x 成本差异）说明 session 复用不是优化，是必需品。我们的 boot.md 编译流程、agent dispatch、memory 加载策略都应该考虑"不要打破缓存前缀"
3. **"LLM as Compiler" 范式已成共识** — Karpathy 的 raw→wiki→lint→output 和我们的 SOUL/boot.md 编译是同一模式。区别是他加了 Linting 闭环（自动检查一致性），我们还没有
4. **成本驱动正在重塑架构** — Anthropic 封锁第三方工具消耗订阅额度 → WeClaw 做多 runtime 切换；KV Cache 分析 → session 复用；Karpathy 用 1M context 替代 RAG → 避免检索链路成本。省钱不是优化，是架构选择
