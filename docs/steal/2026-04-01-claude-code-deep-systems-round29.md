# Round 29: Claude Code 深层系统逆向 — 六大子系统 84 模式

> **日期**: 2026-04-01
> **来源**: `@anthropic-ai/claude-code` v2.1.88 反编译源码
> **方法**: 6 路并行 code-explorer agent，每路读完整实现代码
> **范围**: QueryEngine / Bridge 通信 / 记忆系统 / Task 执行 / 核心服务 / Plugin+Skill

---

## 执行摘要

Round 28 覆盖了 Gate Chain、Address Registry、System Prompts、Multi-Agent Orchestration 等架构级模式。本轮深入 **实现层**，对 6 个核心子系统做逐文件逆向，产出 84 个可偷模式。

**最高价值发现**:
1. **Speculative Execution with CoW Overlay** — 用文件系统 overlay 跑推测执行，accept 时 merge，abort 时删目录
2. **Withheld Error + 3-Layer Recovery** — 流中错误先扣押，尝试 collapse → reactive compact → max_output 递增，都失败才暴露
3. **LLM-as-Relevance-Ranker** — 不用向量数据库，用 Sonnet sideQuery 做记忆语义匹配
4. **Coordinator Synthesis Gate** — prompt 规则明文禁止 lazy delegation，强制 coordinator 自己理解后产出含具体坐标的实现规格
5. **Token Budget Diminishing Returns** — 追踪连续两次 delta < 500 tokens 才停，不粗暴截断

---

## 一、QueryEngine 执行引擎（14 模式）

**源码**: `src/QueryEngine.ts` (47KB) + `src/query.ts` (69KB) + `src/query/*.ts`

QueryEngine 是会话层（跨 turn 可变状态），query.ts 是执行层（单 turn API 调用循环），两者通过 AsyncGenerator 管道连接。

### P01: Iterative State Machine
`while(true)` + `state = next; continue` 替代递归。7 个 continue site 覆盖 6 种恢复路径。`transition` 字段不驱动行为，只记录原因，专为可测试性设计。

**位置**: `query.ts:307`, `query.ts:1715-1728`

### P02: Withheld Error + Recovery
streaming 循环遇到 prompt-too-long 或 max_output_tokens 错误时不立即 yield，而是 `withheld = true`。流结束后按优先级尝试 3 层恢复：
1. `contextCollapse.recoverFromOverflow()` (drain staged collapses)
2. `reactiveCompact.tryReactiveCompact()` (full summary)
3. max_output_tokens 递增重试（注入 meta message，上限 3 次）

三条路都走完才暴露错误。注释明确说："Yielding early leaks an intermediate error to SDK callers that terminate the session on any `error` field"。

**位置**: `query.ts:788-825` (withheld), `query.ts:1062-1183` (recovery)

### P03: Three-Layer Context Compression Pipeline
每次 API 调用前按顺序执行 4 层压缩：
1. snip（移除历史片段）→ 返回 `tokensFreed`
2. microcompact（微压缩，有 `CACHED_MICROCOMPACT` 变体）
3. contextCollapse（读时投影，不修改主数组）
4. autocompact（触发条件：`tokenCount - snipTokensFreed` 超阈值）

注释特别说明："Collapse BEFORE autocompact so that if collapse gets us under the threshold, autocompact is a no-op and we keep granular context."

### P04: Streaming Tool Executor
工具在 model 还在流式输出时就开始执行。Fallback 触发时 executor 调用 `discard()` 丢弃所有中间结果，重建新实例，防止 orphan tool_result 污染 retry 请求。

### P05: Config Snapshot Isolation
`buildQueryConfig()` 在入口调用一次，将 Statsig gate 快照到 `QueryConfig.gates`。明确区分编译时开关（`feature()` — tree-shaking 边界，必须内联）和运行时开关（Statsig — 可快照）。

**位置**: `query/config.ts:14-46`

### P06: Narrow Dependency Injection (4 deps)
`QueryDeps` 接口只有 `callModel`、`microcompact`、`autocompact`、`uuid` 四个字段。`typeof fn` 推导保持与实现同步。注释："Scope is intentionally narrow (4 deps) to prove the pattern."

### P07: Token Budget Diminishing Returns
`BudgetTracker` 追踪 continuationCount 和 lastDeltaTokens。`continuationCount >= 3` 且连续两次 delta < 500 tokens → 强制停止。子 agent 直接 stop，不做 budget 管理。

**位置**: `query/tokenBudget.ts`

### P08: Stop Hooks Pipeline（3 阶段 + 阻塞/非阻塞分级）
按顺序执行 3 类 hook：Standard Stop → TaskCompleted（per task 串行）→ TeammateIdle。每个结果分三级：preventContinuation / blockingError / non_blocking_error。API 错误消息直接跳过 stop hooks，注释："error → hook blocking → retry → error → … death spiral"。

**位置**: `query/stopHooks.ts:65-473`

### P09: Transcript Write Asymmetry
assistant 消息 `void recordTranscript()`（fire-and-forget），user 消息 `await recordTranscript()`。注释解释：assistant 消息逐 content block yield，如果 await 会阻塞 generator 导致 drain timer 提前触发。

**位置**: `QueryEngine.ts:727-732`

### P10: Orphan Tool Result Injection
streaming 异常中断时，已 yield 的 tool_use block 缺少对应 tool_result。`yieldMissingToolResultBlocks` 遍历所有 assistantMessages，合成 `is_error: true` 的 tool_result 保持协议合法。

**位置**: `query.ts:123-148`

### P11: Lazy React Import
`const messageSelector = () => require('src/components/MessageSelector.js')`，避免 bun test 环境中 React/ink 副作用。

### P12: Feature-Gated Module Graph
`feature('X') ? require('./module') : null` — 编译时常量控制，关闭时整个 require 分支被 tree-shake，不打包对应模块。

### P13: Permission Denial Tracking
`wrappedCanUseTool` 包装原函数，在 `result.behavior !== 'allow'` 时记录 denials 数组随 result message yield 给 SDK caller。底层 `canUseTool` 完全不感知统计。

### P14: Compact Boundary GC Trigger
收到 `compact_boundary` 消息后主动 `splice(0, boundaryIdx)` 释放 pre-compaction 消息数组。长时 headless session 防内存无限增长。

**位置**: `QueryEngine.ts:926-933`

---

## 二、Bridge 通信层（14 模式）

**源码**: `src/bridge/` (33 files)

Bridge 是 claude.ai 网页端驱动本地 CLI 的"远程控制骨干"，分两条路径：环境路径（v1，poll/ack/heartbeat 全生命周期）和无环境路径（v2，POST /bridge → SSE + CCRClient）。

### P15: Bounded-Ring-UUID-Dedup
定容环形缓冲 + Set 的 O(1) echo 去重（2000 容量）。两个实例：`recentPostedUUIDs`（过滤服务器回声）和 `recentInboundUUIDs`（transport 替换后防重放）。

**位置**: `bridgeMessaging.ts:429`

### P16: FlushGate State Machine
解决初始刷新期间消息顺序问题。`start()` → 队列模式 → `end()` 返回积压 → `deactivate()` 保留队列给新 transport → `drop()` 永久关闭时丢弃。

**位置**: `flushGate.ts`

### P17: CapacityWake Dual-Signal
满容量长睡眠（10分钟）需要被两种信号唤醒：外部关机 OR 内部容量变化。合并 AbortController，`wake()` 中止当前并创建新的。

**位置**: `capacityWake.ts`

### P18: Token Refresh Generation Guard
每次 `schedule()`/`cancel()` 递增 generation 计数器。异步 `doRefresh()` 在 await 后检查代次是否匹配，防旧刷新请求在新 session 上执行。

**位置**: `jwtUtils.ts:72`

### P19: Epoch-Supersession Recovery
Worker Epoch 不匹配（409）时通过 onClose 通知调用方而非 `process.exit(1)`，让轮询循环重新派发工作。

### P20: Dependency Injection for Bundle Size
重型依赖（auth.ts → 命令注册表 → React树，~1300 模块）通过回调注入而非 import，保持 Agent SDK bundle 体积可控。

### P21: Work-Secret-as-Capability-Token
base64url 编码的 JSON work secret 携带 session JWT 和 API base URL，子进程无需独立认证流程。父进程的 OAuth token 被显式 `undefined`。

### P22: Idempotent Registration with Reuse Hint
注册时携带 `reuseEnvironmentId`，服务器决定复用还是新建。客户端比较响应 ID 判断结果。

### P23: Explicit Ack After Commit
先 spawn 确认能处理，再 ack，防 ack 后因容量检查失败导致工作永久丢失。

### P24: Outbound-Only Mode Error Response
镜像模式对 mutable 控制请求返回错误而非静默成功，防 claude.ai 显示错误反馈。

### P25: Fault Injection Proxy Wrapper
`wrapApiForFaultInjection` 作为 API 客户端的 Proxy 包装层，仅 ant 用户激活，零生产开销。

### P26: Poll Config Schema Rejection vs Clamp
Zod 拒绝不合规整体对象而非 clamp 单个字段。`1-99` 被拒（防单位混淆），对象级约束确保 heartbeat 或 poll 至少一个启用。

### P27: SSE SequenceNum Carryover
transport 替换时携带 `lastSequenceNum`，新连接从断点续传而非从头重放。

### P28: Stdin Token Update
通过 `{ type: 'update_environment_variables' }` NDJSON 消息向子进程 stdin 推送新 token，避免重启进程。

---

## 三、记忆系统（14 模式）

**源码**: `src/memdir/` + `src/services/extractMemories/` + `src/services/SessionMemory/` + `src/services/teamMemorySync/`

三个并行子系统：持久记忆（Auto Memory，跨会话）、会话记忆（Session Memory，服务 compaction）、团队记忆同步。

### P29: Derivability Filter
可推导信息（代码结构、git 历史、调试方案）永不存入记忆。系统会反问用户"什么是令人惊讶的部分"。

### P30: Two-Level Index
MEMORY.md 是指针索引（200 行 / 25KB 上限，始终加载入 system prompt），主题文件存实体（按需召回）。

### P31: LLM-as-Relevance-Ranker
不用向量数据库，用 Sonnet sideQuery 通过描述字符串做语义匹配，最多返回 5 个候选。`alreadySurfaced` 集合过滤已展示文件。

**位置**: `findRelevantMemories.ts`

### P32: Human-Readable Staleness Signal
"47 days ago" 比 ISO 时间戳更能触发模型过时推理。有 eval 数据支撑的设计决策。

**位置**: `memoryAge.ts`

### P33: Forked Agent Extraction
提取 agent 完美 fork 主对话，共享 prompt cache。工具权限白名单化：Read/Grep/Glob 无限制，Write/Edit 仅限 autoMemPath，Bash 仅只读命令。失败不通知用户，游标不推进（下次重试覆盖）。

### P34: Cursor-Based Incremental Processing
用 message UUID 作为游标，每次只处理新增消息。

### P35: Mutual Exclusion via Write Detection
检测主 agent 是否已在本轮写入记忆文件（扫描 Write/Edit 工具调用 + 路径匹配），是则跳过后台提取，只推进游标。

### P36: Structured Living Document (Session Memory)
9 段固定 schema：Session Title / Current State / Task Spec / Files / Workflow / Errors / Docs / Learnings / Key Results / Worklog。结构永不改变，内容持续更新。每 section 上限 2000 token，总体 12000 token。

### P37: Token-Growth-Based Trigger
按 context 增长量触发（≥5000 tokens AND ≥3 tool calls），与 autocompact 同一度量标准。

### P38: ETag Optimistic Locking + Light Hash Probe
团队记忆用 If-Match 乐观锁。412 冲突时调用 `?view=hashes` 只拉 checksums 不拉内容体，重新计算 delta 重试（最多 2 次）。

### P39: Pre-Upload Secret Scan
gitleaks 规则在内存扫描，检测到 secret 的文件跳过上传，永不离机。

### P40: Git Canonical Root Anchoring
使用 `findCanonicalGitRoot()` 确保所有 worktree 共享同一记忆目录。

### P41: Asymmetric Sync Semantics
Pull 是覆盖（服务端 wins），Push 是 delta upsert。删除不传播（保守语义，防意外数据丢失）。

### P42: Dual-Layer Path Traversal Defense
字符串级 `path.resolve()` + 文件系统级 `realpath()` 双重验证，防 symlink escape、null byte、URL 编码 traversal、Unicode NFKC 攻击。

---

## 四、Task 执行系统（16 模式）

**源码**: `src/tasks/` + `src/services/autoDream/` + `src/coordinator/`

7 种任务类型（local_bash / local_agent / remote_agent / in_process_teammate / local_workflow / monitor_mcp / dream）统一存储在 `AppState.tasks`。

### P43: Unified AppState Task Registry
所有 7 种任务类型统一存储在 `AppState.tasks[taskId]`。reducer 式 `updateTaskState<T>()` 返回同引用时跳过 spread（18 个订阅者不无谓重渲染）。

### P44: Prefix-Based Task ID
7 种任务用不同字母前缀（b/a/r/t/w/m/d/s），36^8 随机后缀。debug 时一眼识别类型。

### P45: Atomic Notified Flag
check-and-set 在 `updateTaskState` 内部原子完成，防并发完成/kill 场景下重复通知。

### P46: Stall-Watchdog Interrupt
Shell 任务 45s 停滞 + tail 正则检测交互 prompt（`y/n` 等），提前通知 LLM 而不是超时失败。

### P47: Stable Idle Debounce
Remote 任务 5 次连续 idle poll 才认定完成（`STABLE_IDLE_POLLS = 5`），防工具调用间隙的瞬态 idle 触发误完成。

### P48: Foreground-Background Signal Promise
`backgroundSignal: Promise<void>` + resolver Map。Ctrl+B 时 resolve，挂起的 await 解除阻塞，零轮询开销。

### P49: Child AbortController Cascade
父 agent kill 时通过 child abort controller 级联 abort 所有子 agent。

### P50: Sidecar Metadata for Resume
RemoteAgentTask 写入 session sidecar 文件，`--resume` 时读取并重建状态，恢复跨进程存活的云端任务。

### P51: Plug-in Completion Checker
`registerCompletionChecker(type, fn)` 注入表，不同 remote task 类型各自定义完成逻辑。

### P52: Isolated Sidechain Transcript
后台会话写独立文件。`/clear` 时重链符号链接，后台执行和主会话 transcript 完全隔离。

### P53: Lock-Protected Consolidation with Rollback
Dream 用文件锁防并发（三重门：时间 → 会话数 → 锁获取）。kill 时 rollback lock mtime 使重试成为可能。

### P54: Dual Abort Granularity
InProcessTeammate 两层 abort：整体（杀 teammate）和 turn 级别（打断当前 turn，teammate 变 idle 继续等）。

### P55: Cap-Protected UI Message Buffer
Teammate messages UI 上限 50 条（`TEAMMATE_MESSAGES_UI_CAP = 50`）。基于真实事故：292 agent 并发 → 36.8GB RSS。

### P56: Coordinator Synthesis Gate
Coordinator mode prompt 明文禁止 "based on your findings" 的 lazy delegation，强制自己理解 research 后产出含具体文件路径和行号的实现规格。

### P57: Panel Grace Eviction
`PANEL_GRACE_MS=30s` 延迟驱逐已完成 task，给用户查看时间。`retain=true` 时无限期保留。

### P58: Progress Tracker Token Accounting
`latestInputTokens`（取最新，API 返回累计值）和 `cumulativeOutputTokens`（按轮累加），避免重复计数。

---

## 五、核心服务层（16 模式）

**源码**: `src/services/compact/` + `src/services/MagicDocs/` + `src/services/analytics/` + `src/services/policyLimits/` + `src/services/AgentSummary/` + `src/services/PromptSuggestion/`

### P59: Scratchpad-Strip Summarization
让 LLM 先在 `<analysis>` 做推理草稿，strip 后只保留 `<summary>`。草稿提升质量但不消耗上下文 token。

**位置**: `compact/prompt.ts`

### P60: API-Round Grouping for Truncation
按 `message.id` 切割 API 轮次边界（而非用户轮次），支持单 human-turn 含数百 tool-use 的 agentic session 的细粒度截断。

**位置**: `compact/grouping.ts`

### P61: Fail-Open Compact with Head-Drop Retry
compact 请求本身超长时，循环丢弃最老的 API 轮组直到能请求。fallback 丢 20%，最多 `MAX_PTL_RETRIES=3` 次。

### P62: Post-Compact State Resurrection
压缩后并行重建：文件快照（最多 5 个，50K token 预算）+ 工具定义 delta + MCP + Agent listing + Plan + Skills attachment。

### P63: Type-Enforced PII Sanitization
```typescript
type AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS = never
```
`never` 类型作为"我已确认"的编译期标记，必须显式 `as` 转换。比注释更可靠。

**位置**: `analytics/index.ts`

### P64: _PROTO_ Namespace for Privileged Routing
用 key 命名前缀区分 sink 路由。`stripProtoFields()` 单函数清洗 Datadog 流量，exporter 端负责提升到 proto 字段。

### P65: Startup Queue with Microtask Drain
sink 注册前发出的事件入队，注册后 `queueMicrotask` 异步 drain。避免 startup 路径延迟但不丢事件。

### P66: Checksum-Based ETag Caching Without Server ETag
本地计算 `sha256(sortKeysDeep(restrictions))` 当 ETag 用。`sortKeysDeep()` 确保 key 顺序不影响 checksum。

**位置**: `policyLimits/index.ts`

### P67: Tiered Fail-Open with Policy-Specific Fail-Closed
全局 fail-open，但 `ESSENTIAL_TRAFFIC_DENY_ON_MISS` 白名单（如 `allow_product_feedback`）在特定环境下 fail-closed（HIPAA 合规）。

### P68: Deadlock-Prevention Promise with Timeout
`initializePolicyLimitsLoadingPromise()` 注入 30 秒超时，防 `loadPolicyLimits()` 从未被调用导致下游永久阻塞。

### P69: Idle-Window Background Doc Sync (MagicDocs)
检测"对话空闲"信号（最后一个 assistant turn 无 tool call），在自然间隙做后台文档更新。

### P70: Per-Agent Sandbox via canUseTool
不修改 tool list 参数（那会 bust prompt cache），在 `canUseTool` callback 中做路径级权限判断。

### P71: Completion-Relative Timer
`finally` 块调用 `scheduleNext()`（不用 `setInterval`），保证串行不重叠。

### P72: Speculative Execution with Copy-on-Write Overlay ⭐
**本轮最高价值模式。** 用户还没确认建议时，后台创建临时文件系统 overlay：
- Write tools: 先 copy 原文件到 overlay，重定向写操作
- Read tools: 优先读 overlay 版本
- Bash: 只允许只读命令
- 其他: 记录 boundary 类型后 abort

Accept 时 `copyOverlayToMain()` 合并到主 cwd。Abort 时删除 overlay 目录，零回滚成本。

**位置**: `PromptSuggestion/speculation.ts`

### P73: Boundary-Aware Speculation Abort
推测遇到危险操作不报错，记录 boundary 类型（bash/edit/denied_tool/complete），让 accept 路径知道需要继续执行哪部分。

### P74: Two-Level Suggestion Pipeline
建议生成 → 推测执行 → 推测执行完毕期间预生成下一条建议。用户每次 accept 后下一条建议已就绪。

---

## 六、Plugin + Skill 加载系统（10 模式）

**源码**: `src/plugins/` + `src/skills/` + `src/services/plugins/` + `src/commands/plugin/` + `src/tools/SkillTool/` + `src/tools/ToolSearchTool/`

三条平行轨道：BundledSkills（硬编码随二进制打包）、BuiltinPlugins（用户可开关随 CLI 发布）、MarketplacePlugins（外部安装）。

### P75: Sentinel ID Namespace
`name@marketplace` 格式区分三种来源：`name@builtin`（内置）/ `name@inline`（会话临时）/ `name@{marketplace}`（市场来源）。

### P76: Zod LazySchema
所有 schema 用 `lazySchema()` 包装，防模块初始化时循环依赖导致 undefined，同时允许 Zod v4 的 lazy reference。

### P77: Fail-Closed Enterprise Policy
企业 allowlist/blocklist 配置损坏时拒绝加载而非放行。明确注释了 fail-open 的安全风险。

### P78: Promise Memoized Extraction
BundledSkill 文件解压用 `extractionPromise ??= extractBundledSkillFiles(...)` 确保并发调用者等待同一个 Promise，不竞争写入。安全写入 `O_NOFOLLOW | O_EXCL` 防 symlink 攻击。

### P79: ToolSearch Keyword Scoring Algorithm
七级权重打分：
| 匹配类型 | 权重 |
|----------|------|
| 工具名 part 精确匹配（MCP）| +12 |
| 工具名 part 精确匹配（普通）| +10 |
| 工具名 part 包含词（MCP）| +6 |
| 工具名 part 包含词（普通）| +5 |
| searchHint 词边界匹配 | +4 |
| 工具名 full 包含 | +3 |
| description 词边界匹配 | +2 |

`+` 前缀语法：`+required_term optional_term` — 带 `+` 的词为必须命中。

**位置**: `ToolSearchTool/ToolSearchTool.ts`

### P80: searchHint Field
Tool/Skill 可声明 `searchHint: string` 作为高权重搜索信号（+4），高于 description（+2）。

### P81: MCP Shell Isolation
MCP skills 的 markdown body 绝不执行 `` !`cmd` `` 内联命令，保护远程/不可信内容。

### P82: Write-Once Registry (Circular Dependency Break)
`registerMCPSkillBuilders()` + `getMCPSkillBuilders()` 解决 mcpSkills → loadSkillsDir → ... → mcpSkills 循环依赖，避免动态 import（Bun bundled binary 内解析失败）。

### P83: Seed Cache Probing
企业/BYOC 场景支持预置 seed cache 目录，首次启动无需 git clone，直接读取。

### P84: Custom Prompt Override via Filesystem
优先加载用户 `~/.claude/` 下的自定义 prompt 文件，找不到时 fallback 到内置模板。

---

## 优先级矩阵

### ⭐ P0 — 立即可偷（直接提升 Orchestrator 能力）

| # | Pattern | 实施难度 | 预期收益 |
|---|---------|---------|---------|
| P01 | Iterative State Machine | 低 | Governor 循环重构，消除递归 |
| P02 | Withheld Error + Recovery | 中 | Agent SDK 调用的错误恢复 |
| P07 | Token Budget Diminishing Returns | 低 | 子 agent token 管理 |
| P29 | Derivability Filter | 低 | 记忆系统过滤规则 |
| P30 | Two-Level Index | 已有 | 验证现有设计正确 |
| P32 | Human-Readable Staleness Signal | 低 | 记忆新鲜度提示改进 |
| P35 | Mutual Exclusion via Write Detection | 低 | 后台提取与主 agent 互斥 |
| P44 | Prefix-Based Task ID | 低 | 任务 ID 可读性 |
| P46 | Stall-Watchdog Interrupt | 中 | Shell 任务停滞检测 |
| P53 | Lock-Protected Consolidation with Rollback | 中 | Dream/记忆整理的并发保护 |
| P56 | Coordinator Synthesis Gate | 低 | 三省六部 prompt 强化 |
| P59 | Scratchpad-Strip Summarization | 低 | compact 质量提升 |
| P70 | Per-Agent Sandbox via canUseTool | 中 | 子 agent 最小权限 |
| P72 | Speculative Execution with CoW Overlay | 高 | 预测执行基础设施 |
| P79 | ToolSearch Keyword Scoring | 中 | 工具/技能匹配算法 |

### P1 — 值得偷（中期改进）

| # | Pattern | 说明 |
|---|---------|------|
| P03 | Three-Layer Compression | 多层压缩管线 |
| P08 | Stop Hooks Pipeline | 后处理钩子分级 |
| P15 | Bounded-Ring-UUID-Dedup | 消息去重 |
| P16 | FlushGate State Machine | 初始刷新排序 |
| P18 | Token Refresh Generation Guard | 异步刷新防 race |
| P36 | Structured Living Document | session memory 模板 |
| P47 | Stable Idle Debounce | 远程任务完成判定 |
| P55 | Cap-Protected UI Message Buffer | OOM 防护 |
| P60 | API-Round Grouping | 细粒度截断 |
| P62 | Post-Compact State Resurrection | 压缩后上下文重建 |
| P63 | Type-Enforced PII Sanitization | 编译期隐私保护 |
| P74 | Two-Level Suggestion Pipeline | 预测流水线 |

### P2 — 参考学习（当前不急需）

其余模式作为参考存档，在对应系统建设时回顾。

---

## 与 Round 28 的关系

| Round 28 覆盖 | Round 29 深入 |
|--------------|--------------|
| Gate Chain 架构 | QueryEngine 内部状态机实现 |
| Address Registry 概念 | Bridge 33 文件完整通信协议 |
| System Prompts 分析 | compact/SessionMemory 的 prompt 工程 |
| Multi-Agent 四层栈 | Task 系统 7 种类型的完整生命周期 |
| — | 记忆系统全栈：提取 → 存储 → 检索 → 衰减 → 同步 |
| — | Plugin/Skill 加载：发现 → 匹配 → 执行 → 安全 |
| — | Speculative Execution（全新发现） |

**累计统计**: Round 28（~90 模式）+ Round 29（84 模式）= **174 模式**，覆盖 Claude Code 1884 文件中的核心子系统。
