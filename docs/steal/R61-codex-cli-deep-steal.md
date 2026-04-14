# R61: OpenAI Codex CLI — 深度偷师报告（第二轮）

> 仓库: https://github.com/openai/codex (Apache 2.0)
> 上次扫描: 2026-04-01 (R28，表面级)
> 本轮日期: 2026-04-14
> 分支: steal/round-deep-rescan-r60
> 代码量: ~3200+ Rust 源文件（自 R28 以来新增大量模块）
> 重点: Rust TUI 架构 / Agent 编排核心 / 流式渲染 / Guardian 深层机制 / 上下文管理

---

## TL;DR

上次扫描（R28）停留在 prompt 模板层。本轮深入 Rust 实现层，发现了六个在源码层才能看到的架构级模式：

1. **自适应流式渲染（两档变速）** — TUI 流式输出不是「每次收到内容就渲染」，而是 Smooth/CatchUp 双模式，用队列深度+最老行龄做迟滞切换，彻底解决 token 流频繁刷新的画面撕裂问题
2. **Guardian 是独立 sub-agent** — 不是 prompt 里加几句话，而是起一个完整的 gpt-5.4 子 session，timeout 90 秒，fail-closed，有专用的 transcript cursor 做增量传递
3. **MultiAgentV2 的工具粒度设计** — spawn/send_message/followup_task/wait/close 是独立工具，其中 `send_message` 是 QueueOnly（不触发 turn），`followup_task` 是 TriggerTurn（立刻触发），精确控制执行节奏
4. **Session 预热（Prewarm）** — 新 session 启动后立即向 API 发一个空 request，把 TCP 连接 + auth 都热好，等用户真正提交时直接复用，消灭首 turn 延迟
5. **Compaction 的 BeforeLastUserMessage 注入** — mid-turn compaction 时把 initial context 插在「最后一条真实 user message」之前，确保模型训练时看到的 compaction 后格式得以保留
6. **TurnDiffTracker 的语义级 diff** — 不是简单 before/after 文件对比，而是用 UUID 内部文件名做 rename 追踪，所有历史 patch 都在内存中累积，最终 git-diff 格式输出

---

## 架构总览（深层视角）

### 调度层 → 实践层 → 消费层 → 状态层 → 边界层

```
┌─────────────────────────────────────────────────────────────────┐
│                     调度层 (Dispatch)                            │
│  ThreadManager → AgentControl → AgentRegistry                   │
│  spawn_agent_with_metadata() / reserve_spawn_slot()             │
│  深度限制: exceeds_thread_spawn_depth_limit(depth, max_depth)   │
├─────────────────────────────────────────────────────────────────┤
│                     实践层 (Runtime)                             │
│  Session → TurnContext → RegularTask.run()                      │
│  run_turn() loop → ToolCallRuntime → ToolRouter                 │
│  MultiAgentV2: spawn/send_message/followup_task/wait/close      │
├─────────────────────────────────────────────────────────────────┤
│                     消费层 (Output/Rendering)                    │
│  TUI: ChatWidget → StreamController → AdaptiveChunkingPolicy    │
│  流式管道: push_delta → commit_complete_lines → enqueue → drain  │
│  双模式: Smooth(1行/tick) ↔ CatchUp(全队列/tick)               │
├─────────────────────────────────────────────────────────────────┤
│                     状态层 (State)                               │
│  ContextManager (history + token info + ref context item)       │
│  AgentRegistry (活跃agent树 + 昵称 + 总计数 AtomicUsize)        │
│  TurnDiffTracker (UUID内部名 + baseline + rename追踪)           │
├─────────────────────────────────────────────────────────────────┤
│                     边界层 (Safety/Approval)                     │
│  Guardian (gpt-5.4 sub-agent, 90s timeout, fail-closed)         │
│  ToolOrchestrator (approval → sandbox select → retry)           │
│  ExecPolicy (命令前缀语法解析 + allow/deny/ask)                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 六维扫描

### 维度1：安全/治理 (Security/Governance)

#### Guardian 实现深度解析

Guardian 不是"在 system prompt 里加安全规则"，而是：

**架构**:
```rust
// codex-rs/core/src/guardian/mod.rs
const GUARDIAN_PREFERRED_MODEL: &str = "gpt-5.4";
pub(crate) const GUARDIAN_REVIEW_TIMEOUT: Duration = Duration::from_secs(90);
const GUARDIAN_MAX_MESSAGE_TRANSCRIPT_TOKENS: usize = 10_000;
const GUARDIAN_MAX_TOOL_TRANSCRIPT_TOKENS: usize = 10_000;
const GUARDIAN_MAX_ACTION_STRING_TOKENS: usize = 16_000;
const GUARDIAN_RECENT_ENTRY_LIMIT: usize = 40;

pub(crate) struct GuardianAssessment {
    pub risk_level: GuardianRiskLevel,       // Low/Medium/High/Critical
    pub user_authorization: GuardianUserAuthorization,
    pub outcome: GuardianAssessmentOutcome,  // Allow/Deny
    pub rationale: String,
}
```

**Guardian Transcript Cursor 机制**（R28 未发现）:
```rust
// codex-rs/core/src/guardian/prompt.rs
pub(crate) struct GuardianTranscriptCursor {
    pub parent_history_version: u64,   // 历史版本号
    pub transcript_entry_count: usize, // 已传给 guardian 的条数
}

pub(crate) enum GuardianPromptMode {
    Full,                              // 首次审查：全量 transcript
    Delta { cursor: GuardianTranscriptCursor }, // 重试：只传增量
}
```

重试时 guardian 不重新读完整历史——用 cursor 定位上次读到的位置，只传新增的部分。节省 token 同时加快重试速度。

**两种失败模式明确分离**:
```rust
// guardian/review.rs
pub(crate) fn guardian_rejection_message(...) -> String {
    "This action was rejected due to unacceptable risk.\nReason: {rationale}\n
     The agent must not attempt to achieve the same outcome via workaround,
     indirect execution, or policy circumvention."
}

pub(crate) fn guardian_timeout_message() -> String {
    "The automatic permission approval review did not finish before its deadline.
     Do not assume the action is unsafe based on the timeout alone.
     You may retry once, or ask the user for guidance or explicit approval."
}
```

拒绝 ≠ 超时。拒绝是明确的禁止；超时给 agent 一次重试机会。

**Guardian 只在特定条件下启用**:
```rust
pub(crate) fn routes_approval_to_guardian(turn: &TurnContext) -> bool {
    turn.approval_policy.value() == AskForApproval::OnRequest
        && turn.config.approvals_reviewer == ApprovalsReviewer::GuardianSubagent
}
```

不是默认开的，只有配置了 `approvals_reviewer = "guardian"` 才走 Guardian 路径，否则直接弹给用户。

**Policy.md 的关键变化**（相比 R28）:

本轮读到的 `policy.md` 有明显更新，增加了大量细粒度规则：
- **Data Exfiltration**: 区分"用合法凭证认证"（允许）vs"凭证本身被发出去"（高风险）
- **Git actions**: `--force-with-lease` 到用户自己的特性分支 = medium；触碰 protected/default 分支 = high/critical
- **Low-Risk Actions**: 沙箱重试/降级本身不可疑；工作区外路径的文件操作默认 low risk

---

### 维度2：记忆/学习 (Memory/Learning)

R28 已覆盖 Phase 1+2 记忆管道。本轮发现两个新细节：

**TurnDiffTracker 是记忆的物理基础**:
```rust
// codex-rs/core/src/turn_diff_tracker.rs
pub struct TurnDiffTracker {
    external_to_temp_name: HashMap<PathBuf, String>,  // 外部路径 → UUID
    baseline_file_info: HashMap<String, BaselineFileInfo>,
    temp_name_to_current_path: HashMap<String, PathBuf>,  // rename 追踪
    git_root_cache: Vec<PathBuf>,
}
```

每次工具调用修改文件时，先调 `on_patch_begin()` 抓取文件的 baseline 快照（SHA1），之后可以随时生成标准 unified diff。这个 diff 是 memory phase 1 的重要信号来源：「本轮修改了什么」。

**GhostSnapshot Task 的 4 分钟警告**:
```rust
// codex-rs/core/src/tasks/ghost_snapshot.rs
const SNAPSHOT_WARNING_THRESHOLD: Duration = Duration::from_secs(240);

tokio::time::sleep(SNAPSHOT_WARNING_THRESHOLD) => {
    // 发送警告: "Repository snapshot is taking longer than expected.
    // Large untracked or ignored files can slow snapshots;
    // consider adding large files or directories to .gitignore"
}
```

这是 undo/rollback 的数据基础。GhostSnapshot 在后台悄悄给 git 打 ghost commit，让 undo 有依据。超过 4 分钟还没完就主动提示用户检查 .gitignore。

---

### 维度3：执行/编排 (Execution/Orchestration)

#### MultiAgentV2 工具集的精确语义

这是 R28 完全没有的新模块：

**五个独立工具**:
```
spawn_agent     → 创建新 agent 线程，返回 thread_id
send_message    → QueueOnly，入队不触发 turn（父 agent 发完继续干自己的活）
followup_task   → TriggerTurn，立刻唤醒目标 agent 执行
wait_agent      → 阻塞直到 mailbox 有变化或超时（min/max clamp）
close_agent     → 关闭目标 agent 线程
list_agents     → 列出当前活跃 agent
```

**关键区别 send_message vs followup_task**:
```rust
// message_tool.rs
pub(crate) enum MessageDeliveryMode {
    QueueOnly,   // send_message: 入队，目标 agent 自己决定什么时候读
    TriggerTurn, // followup_task: 立刻唤醒目标 agent 开始一个新 turn
}
```

这个区别极其重要：orchestrator 发完任务可以继续做其他事（QueueOnly），或者需要立刻把任务推给 worker 开始执行（TriggerTurn）。两者语义完全不同。

**子 Agent 的上下文注入**:
```rust
// spawn.rs
pub(crate) const SPAWN_AGENT_DEVELOPER_INSTRUCTIONS: &str = r#"<spawned_agent_context>
You are a newly spawned agent in a team of agents collaborating to complete a task.
You can spawn sub-agents to handle subtasks, and those sub-agents can spawn their own sub-agents.
You are responsible for returning the response to your assigned task in the final channel.
When you give your response, the contents of your response in the final channel will be
immediately delivered back to your parent agent.
The prior conversation history was forked from your parent agent.
Treat the next user message as your assigned task, and use the forked history only as background context.
</spawned_agent_context>"#;
```

每个 spawned agent 自动获得这段 context，明确自己的角色定位：历史是背景，user message 才是任务。

**深度限制的实现**:
```rust
// spawn.rs
let child_depth = next_thread_spawn_depth(&session_source);
let max_depth = turn.config.agent_max_depth;
if exceeds_thread_spawn_depth_limit(child_depth, max_depth) {
    return Err(FunctionCallError::RespondToModel(
        "Agent depth limit reached. Solve the task yourself.".to_string(),
    ));
}
```

超深度不是报错退出，是把错误返回给模型（"Solve the task yourself"），让模型自己决定怎么处理，而不是崩溃。

**Session 预热（Prewarm）**:
```rust
// session_startup_prewarm.rs
// 新 session 初始化后立刻触发预热任务
// 预热任务向 API 发一个轻量 request，建立 TCP 连接 + 认证
// 用户第一次提交时，consummate_startup_prewarm_for_regular_turn() 直接复用预热好的 client session

pub(crate) enum SessionStartupPrewarmResolution {
    Cancelled,
    Ready(Box<ModelClientSession>),    // 预热成功，直接用
    Unavailable { status, prewarm_duration },  // 超时/失败，新建连接
}
```

用户感知的首 turn 延迟大幅下降。

---

### 维度4：上下文/预算 (Context/Budget)

#### Compaction 的两种注入模式（机制级）

R28 描述了 compaction 的概念，本轮看到了实现细节：

```rust
// codex-rs/core/src/compact.rs
pub(crate) enum InitialContextInjection {
    BeforeLastUserMessage,  // mid-turn compaction
    DoNotInject,            // pre-turn/manual compaction
}

// 为什么有 BeforeLastUserMessage？
// 模型训练时看到的 compaction 后格式是：
// [...压缩后摘要...] [user message]
// 所以 mid-turn 压缩时必须把 initial context 插在最后一条 user message 之前
// 确保格式和训练数据一致
```

**Context 窗口超出时的修剪策略**:
```rust
// compact.rs
Err(e @ CodexErr::ContextWindowExceeded) => {
    if turn_input_len > 1 {
        // 从最老的历史开始删，保留 prefix 利于 KV cache
        history.remove_first_item();
        truncated_count += 1;
        retries = 0;  // 重置重试计数器
        continue;
    }
    // 实在没法压了，标记 context window 满
    sess.set_total_tokens_full(turn_context.as_ref()).await;
}
```

不是随机删，是从最老的删，因为 prefix 共享更有利于 KV cache 命中。

**ContextManager 的 history_version 机制**:
```rust
// context_manager/history.rs
pub(crate) struct ContextManager {
    items: Vec<ResponseItem>,
    history_version: u64,  // 每次 compaction/rollback 都 bump
    token_info: Option<TokenUsageInfo>,
    reference_context_item: Option<TurnContextItem>,
}
```

`reference_context_item` 是 diff 的基准——context updates 只发差值，不是每次都重发全量配置。Guardian transcript cursor 里用到的 `parent_history_version` 就是读这个字段。

**速率限制的多维展示**:
```rust
// tui/src/status/rate_limits.rs
pub(crate) struct RateLimitSnapshotDisplay {
    pub limit_name: String,
    pub captured_at: DateTime<Local>,
    pub primary: Option<RateLimitWindowDisplay>,    // 短时窗口（如 1h）
    pub secondary: Option<RateLimitWindowDisplay>,  // 周窗口
    pub credits: Option<CreditsSnapshotDisplay>,
}

// 分三种状态：Available / Stale(15分钟) / Missing
// 超 15 分钟的数据标为 Stale 不是直接不显示
```

---

### 维度5：失败/恢复 (Failure/Recovery)

#### ToolOrchestrator 的 approval → sandbox → retry 流水线

```rust
// tools/orchestrator.rs
// 核心流程：
// 1. begin_network_approval()      → 网络访问预审
// 2. tool.run(req, attempt, ctx)   → 实际执行
// 3. 如果 sandbox denial：         → retry with SandboxType::None
// 4. DeferredNetworkApproval:      → 执行成功后才最终确认网络访问

pub(crate) struct OrchestratorRunResult<Out> {
    pub output: Out,
    pub deferred_network_approval: Option<DeferredNetworkApproval>,
}
```

`DeferredNetworkApproval` 的设计值得关注：网络权限审批分两段——运行前预审（建立规则），执行成功后最终确认（提交记录）。如果工具执行失败，deferred approval 自动被丢弃，不会留下错误的审计记录。

**UnifiedExec 的进程池限制**:
```rust
// unified_exec/mod.rs
pub(crate) const MAX_UNIFIED_EXEC_PROCESSES: usize = 64;
pub(crate) const WARNING_UNIFIED_EXEC_PROCESSES: usize = 60;  // 到 60 时预警
pub(crate) const MIN_YIELD_TIME_MS: u64 = 250;
pub(crate) const MIN_EMPTY_YIELD_TIME_MS: u64 = 5_000;  // 空 stdin 写的等待时间
pub(crate) const UNIFIED_EXEC_OUTPUT_MAX_BYTES: usize = 1024 * 1024; // 1 MiB 输出上限
```

**MailboxDeliveryPhase 的精细控制**:
```rust
// state/turn.rs
pub(crate) enum MailboxDeliveryPhase {
    CurrentTurn,  // agent 正在 turn 中，子 agent 的消息可以被当前 turn 消费
    NextTurn,     // 当前 turn 已有可见输出，子 agent 消息留给下一个 turn
}
```

这解决了多 agent 协作时"消息到达时机"的问题：如果父 agent 的 turn 已经产生了用户可见的输出，就不再把迟到的子 agent 消息塞进当前 turn，避免用户看到乱序内容。

---

### 维度6：质量/审查 (Quality/Review)

#### 自适应流式渲染（AdaptiveChunkingPolicy）

这是本轮最有价值的工程发现。TUI 渲染管道：

```rust
// tui/src/streaming/chunking.rs
// 关键阈值
const ENTER_QUEUE_DEPTH_LINES: usize = 8;   // 深度超过 8 行 → 进入 CatchUp
const ENTER_OLDEST_AGE: Duration = Duration::from_millis(120); // 最老行超过 120ms → 进入 CatchUp
const EXIT_QUEUE_DEPTH_LINES: usize = 2;    // 深度降到 2 以下 → 可以退出 CatchUp
const EXIT_OLDEST_AGE: Duration = Duration::from_millis(40);   // 最老行 < 40ms → 可以退出
const EXIT_HOLD: Duration = Duration::from_millis(250);  // 要维持 250ms 低压才真正退出
const REENTER_CATCH_UP_HOLD: Duration = Duration::from_millis(250); // 退出后 250ms 内不重进
const SEVERE_QUEUE_DEPTH_LINES: usize = 64; // 严重积压阈值（可绕过 reentry hold）
```

**两档变速原理**:
```rust
pub(crate) enum ChunkingMode {
    Smooth,  // 每 tick 渲染 1 行
    CatchUp, // 每 tick 渲染全部积压行
}

pub(crate) enum DrainPlan {
    Single,       // Smooth 模式
    Batch(usize), // CatchUp 模式，usize = 当前队列深度
}
```

**渲染管道的层级**:
```
token delta → MarkdownStreamCollector → commit_complete_lines() 
           → StreamState.enqueue() → AdaptiveChunkingPolicy.decide()
           → DrainPlan → StreamController.on_commit_tick() / on_commit_tick_batch()
           → HistoryCell
```

关键设计：只有遇到 `\n` 时才 commit（`commit_complete_lines`），不完整的行在收集器里等待。这保证 Markdown 渲染的正确性（不会因为 token 流在 Markdown 语法中间截断而渲染出错）。

**多 agent 的 TUI 展示协议**:
```rust
// tui/src/multi_agents.rs
// 事件层级：
// CollabAgentSpawnEndEvent   → "• Spawned Robie [explorer] (gpt-5 high)"
// CollabAgentInteractionEnd  → "• Sent input to Robie [explorer]"
// CollabWaitingBeginEvent    → "• Waiting for Robie [explorer]"
// CollabWaitingEndEvent      → "• Finished waiting"
//                               └ Robie: Completed - 39916800
//                               └ Bob: Error - tool timeout
// CollabResumeEndEvent       → "• Resumed Robie [explorer]"
//                               └ Interrupted / Completed / Running

pub(crate) fn agent_picker_status_dot_spans(is_closed: bool) -> Vec<Span<'static>> {
    let dot = if is_closed { "•".into() } else { "•".green() };
    // 绿点 = 活跃，灰点 = 已关闭
}
```

**StatusLine 的 shimmer 动画**:
```rust
// tui/src/shimmer.rs
// 基于进程启动时间做时间扫描动画
// 用余弦函数模拟高斯光带
// 检测是否支持 true color（16M 色），支持则用 RGB 插值，否则降级
let t = if dist <= band_half_width {
    let x = std::f32::consts::PI * (dist / band_half_width);
    0.5 * (1.0 + x.cos())
} else { 0.0 };
```

---

## P0/P1/P2 模式清单

### P0 新发现（R28 未覆盖）

| 模式 | 来源 | 核心价值 | 偷法 |
|------|------|----------|------|
| **P0-7: 自适应渲染两档变速** | `tui/src/streaming/chunking.rs` | 解决流式输出画面积压/撕裂 | 在我们的 Python 输出管道中实现队列+批量渲染逻辑 |
| **P0-8: Guardian Transcript Cursor** | `core/src/guardian/prompt.rs` | 重试时只传增量 transcript，节省 80%+ token | Guardian 层的增量 prompt 机制 |
| **P0-9: send_message vs followup_task** | `core/src/tools/handlers/multi_agents_v2/` | 精确区分"入队不触发"和"立即唤醒"两种通信语义 | sub-agent 消息系统中加入 trigger/queue 区分 |
| **P0-10: Session Prewarm** | `core/src/session_startup_prewarm.rs` | 消灭首 turn 延迟 | 在 governor 启动时预热 API 连接 |
| **P0-11: MailboxDeliveryPhase** | `core/src/state/turn.rs` | 防止迟到子 agent 消息污染已完成 turn | agent 消息路由的 phase-aware 入队 |
| **P0-12: DeferredNetworkApproval** | `core/src/tools/orchestrator.rs` | 网络权限审计的两段式提交，防止虚假成功记录 | hook 系统中的"执行前预审+执行后确认"模式 |

### P1 新发现

| 模式 | 来源 | 偷法优先级 |
|------|------|-----------|
| **P1-6: TurnDiffTracker UUID 内部名** | `core/src/turn_diff_tracker.rs` | 用内部标识跟踪 rename，精确生成统一 diff |
| **P1-7: ContextManager reference_context_item** | `core/src/context_manager/history.rs` | context diff 而非全量重传，减少 token |
| **P1-8: 速率限制多维展示+staleness** | `tui/src/status/rate_limits.rs` | 15分钟 stale 标记，而不是简单 missing |
| **P1-9: GhostSnapshot 4分钟警告** | `core/src/tasks/ghost_snapshot.rs` | 慢操作的渐进式用户反馈机制 |
| **P1-10: compaction 修剪从最老开始** | `core/src/compact.rs` | 保 prefix 利于 KV cache 命中 |

### P2 参考

| 模式 | 备注 |
|------|------|
| Shimmer 动画 | 纯 UI，余弦光带扫描，只在有 true color 时启用 |
| AgentNavigationState 稳定 spawn 序 | 多 agent 键盘切换保持 first-seen 顺序，不随 UUID 排序 |
| compose_agents_summary 相对路径 | status 行显示 agent 的 AGENTS.md 路径时用相对路径 |
| SpawnedAgent context XML 块 | `<spawned_agent_context>` 标签隔离子 agent 身份指令 |

---

## P0 模式详解（附代码）

### P0-7: 自适应流式渲染两档变速

**问题**: LLM 输出不均匀，有时一次来一个 token（流畅），有时一次来几十个 token（积压）。如果每次都只渲染 1 行，积压时 TUI 明显落后用户看到 "等待中"；如果每次渲染所有积压，流畅时动画感消失。

**解法**:
```rust
// chunking.rs — 决策函数
pub(crate) fn decide(&mut self, snapshot: QueueSnapshot, now: Instant) -> ChunkingDecision {
    if snapshot.queued_lines == 0 {
        self.mode = ChunkingMode::Smooth;
        return ChunkingDecision { mode: Smooth, drain_plan: Single, .. };
    }
    match self.mode {
        Smooth => self.maybe_enter_catch_up(snapshot, now),
        CatchUp => self.maybe_exit_catch_up(snapshot, now),
    }
    let drain_plan = match self.mode {
        Smooth   => DrainPlan::Single,
        CatchUp  => DrainPlan::Batch(snapshot.queued_lines.max(1)),
    };
    ChunkingDecision { mode: self.mode, drain_plan, .. }
}

// 进入 CatchUp：深度≥8 OR 最老行≥120ms（任一条件触发）
// 退出 CatchUp：深度≤2 AND 最老行≤40ms（必须同时满足）+ 保持 250ms
// 退出后 250ms 内不重新进入（防震荡），除非严重积压（深度≥64）
```

**与我们的差距**: 我们没有 TUI，但这套逻辑对任何流式输出系统都适用（Telegram bot、web streaming、CLI 输出）。两档变速 + 迟滞 = 平滑 + 不落后。

**偷法**: Python 版：维护一个 `queue: deque[Line]`，每个 render tick 根据 `len(queue)` 和 `oldest_item_age` 决定渲染 1 行还是全部。

---

### P0-8: Guardian Transcript Cursor（增量传递）

**问题**: Guardian 每次审查都重传完整对话历史，对话长了成本 + 延迟都高。

**解法**:
```rust
// guardian/prompt.rs
pub(crate) struct GuardianTranscriptCursor {
    pub parent_history_version: u64,   // context_manager 的 history_version
    pub transcript_entry_count: usize,
}

// 重试时：
let prompt_shape = match mode {
    GuardianPromptMode::Delta { cursor } => {
        // 检查版本是否一致 (没有新的 compaction/rollback)
        if cursor.parent_history_version == current_version
            && cursor.transcript_entry_count <= current_count {
            GuardianPromptShape::Delta {
                already_seen_entry_count: cursor.transcript_entry_count,
            }
        } else {
            GuardianPromptShape::Full  // 版本不一致，回退全量
        }
    }
};
```

**与我们的差距**: 我们的 guardian 层（如果有）每次都全量传。

**偷法**: 记录 session history 的版本号，每次调用外部审查 agent 时记录 cursor，重试时只传 cursor 之后的新内容。

---

### P0-9: QueueOnly vs TriggerTurn 通信语义

**核心代码**:
```rust
// message_tool.rs
pub(crate) enum MessageDeliveryMode {
    QueueOnly,   // send_message: 入队，target agent 自己决定何时消费
    TriggerTurn, // followup_task: 立刻给 target 触发一个新的 turn
}

fn apply(self, communication: InterAgentCommunication) -> InterAgentCommunication {
    InterAgentCommunication {
        trigger_turn: matches!(self, Self::TriggerTurn),
        ..communication
    }
}
```

**使用场景区分**:
- orchestrator 向多个 worker 广播任务 → `send_message` × N（各自决定启动时机）
- orchestrator 完成了某个依赖项，立刻推给下一个 worker → `followup_task`（立刻触发）
- worker 向 orchestrator 报告中间结果 → `send_message`（不中断 orchestrator 的 turn）
- 需要立刻打断 worker 执行 → `followup_task` with `interrupt: true`

**与我们的差距**: 我们的 sub-agent dispatch 没有区分这两种语义，所有消息都是隐式的"下次 turn 消费"。

---

### P0-10: Session Prewarm

**问题**: 用户打开工具，输入第一个问题，等 TCP 握手 + auth + 模型路由……感知延迟高。

**解法**:
```rust
// session_startup_prewarm.rs
// Session 初始化完成后立刻触发：
let prewarm_handle = SessionStartupPrewarmHandle::new(
    tokio::spawn(do_prewarm(config.clone(), cancellation_token.child_token())),
    Instant::now(),
    PREWARM_TIMEOUT,
);

// RegularTask.run() 里第一个操作：
let prewarmed_client_session = match sess
    .consume_startup_prewarm_for_regular_turn(&cancellation_token).await
{
    Ready(prewarmed) => Some(*prewarmed),   // 预热好了，直接用
    Unavailable { .. } | Cancelled => None, // 没好，新建一个（不影响功能）
};
```

**与我们的差距**: 我们每次 turn 都是现建连接。如果我们的 governor 有常驻守护进程，这个 prewarm 很容易实现。

---

### P0-11: MailboxDeliveryPhase — 消息时机管控

```rust
// state/turn.rs
// 状态机：
// 初始 = CurrentTurn (可以接受子 agent 消息)
// 当前 turn 有可见输出后 → NextTurn (子 agent 消息留给下个 turn)
// 又有新的 user input 或 tool call → 重开 CurrentTurn

// 解决的问题：
// 场景：orchestrator 问 worker1，worker1 很快回了，orchestrator 开始输出；
// 这时 worker2 也回了（邮件到达）
// 如果 MailboxDeliveryPhase = NextTurn → worker2 的回复在下一个 turn 处理
// 而不是插入到 orchestrator 已经在输出的当前 turn，避免乱序
```

---

### P0-12: DeferredNetworkApproval — 两段式网络权限提交

```rust
// tools/orchestrator.rs
match network_approval.mode() {
    NetworkApprovalMode::Immediate => {
        // 执行前批准 + 执行后立刻确认（同步）
        finish_immediate_network_approval(&tool_ctx.session, network_approval).await;
    }
    NetworkApprovalMode::Deferred => {
        // 执行成功后才确认
        let deferred = network_approval.into_deferred();
        if run_result.is_err() {
            // 工具失败了，不确认网络访问审计记录
            finish_deferred_network_approval(&session, deferred).await;  // 清理
            return (run_result, None);
        }
        (run_result, Some(deferred))  // 成功了，把 deferred 返回给调用方
    }
}
```

**为什么这么设计**: 如果工具执行失败了（比如命令没有成功运行），但网络权限审计说"访问了 api.example.com"——这是虚假记录。Deferred 模式确保审计记录只在实际成功的情况下才落盘。

---

## 比较矩阵

| 能力 | Codex R28 | Codex 当前 | Orchestrator | 差距 | 优先级 |
|------|-----------|------------|--------------|------|--------|
| 流式渲染 | 基础 | 两档变速+迟滞策略 | 无 TUI | - | P0（CLI 输出适用） |
| Guardian | prompt policy | sub-agent+cursor增量 | guard.sh regex | 极大 | P0 |
| Multi-agent 消息 | v1（单工具） | v2（5种工具+语义区分） | 无 | 大 | P0 |
| Session 预热 | 无 | Prewarm handle | 无 | 中 | P0 |
| 消息时机管控 | 无 | MailboxDeliveryPhase | 无 | 中 | P0 |
| 网络权限 | audit log | DeferredApproval 两段式 | 无 | 中 | P1 |
| Context diff | 全量 | reference_context_item | 无 | 小 | P1 |
| 速率限制展示 | 无 | Available/Stale/Missing | 无 | 小 | P2 |
| Compaction KV cache | 截断 | 从最老删起 | Claude 内置 | 小 | P1 |
| Undo/Snapshot | 无 | GhostSnapshot+4min警告 | 无 | 中 | P1 |

---

## 路径依赖分析

### 锁定决策

1. **Rust-only 核心**: codex-rs 的全部核心逻辑都是 Rust，Python SDK 只是薄壳。这意味着我们无法直接复用这些代码，但架构模式可以 Python 化。
2. **OpenAI API first**: guardian 用 gpt-5.4，prewarm 针对 OpenAI routing，与 Anthropic 的模型路由不同。我们要偷模式而不是偷代码。
3. **ratatui TUI 框架**: 整个流式渲染系统是 ratatui 的产物。我们不用 ratatui，但 AdaptiveChunkingPolicy 的状态机逻辑和阈值完全可以用 Python 复现。

### 错过的分叉点

1. 我们没有 session prewarm 机制——每次 governor 被调用都是冷启动。如果我们有一个常驻守护进程，prewarm 可以在用户输入时就开始。
2. 我们的多 agent 消息是"隐式下次 turn"——没有 QueueOnly vs TriggerTurn 的语义区分。这导致需要立刻执行的任务和"有空处理"的任务没有区别。
3. 没有 history_version 的 context diff 机制——每次 turn 都重传全量 context 配置。

### 自我强化效应

Codex 的 registry → cursor → prewarm → MailboxDeliveryPhase 这一组机制相互依赖：
- prewarm 依赖 session 的生命周期管理
- MailboxDeliveryPhase 依赖 turn 级别的状态追踪
- guardian cursor 依赖 history_version

这些是"只能在统一架构中才能优雅实现"的东西。我们做局部偷取时要注意：别硬造依赖关系，选择和我们架构契合的部分先偷。

---

## 邻域发现（Adjacent Discoveries）

### 1. JSON Schema Config（有完整 schema.md）

`codex-rs/core/src/config/schema.md` + `schema.rs` 有完整的 config JSON schema，支持自动验证和 IDE 补全。我们的 channels.yml 没有 schema 验证。

### 2. `<proposed_plan>` 块的解析约定

Plan Mode 的 `<proposed_plan>` 标签有严格约定：
- 开闭标签各占一行
- 内容是 Markdown
- 客户端负责特殊渲染
- 标签名不翻译（即使 plan 内容是中文）

这是一个可直接借鉴的"结构化输出标记"设计模式。我们的 plan template 可以加类似的标记。

### 3. `<truncated />` 标签的语义约定

Guardian policy 里提到：当内容被截断时用 `<truncated />` 标记。这个约定在 guardian 看到时，意味着"缺失数据让你更谨慎，而不是更宽松"（缺失 ≠ 安全）。

### 4. `compose_agents_summary` 的路径显示

status 行显示 AGENTS.md 的路径时，Codex 做了一套相对路径计算，优先显示"相对于 cwd 的路径"，其次才是绝对路径。小细节但提升可读性。

---

## Meta Insights（元洞察）

### 洞察1: 流式渲染是工程而非魔法
TUI 的流畅感不是因为网络快，是因为有精心设计的渲染调度。两档变速+迟滞的核心算法只有约 100 行代码，但需要仔细调参（8行深度/120ms年龄/250ms迟滞），这些数字背后是大量用户观察。

### 洞察2: 多 agent 协调的关键是消息语义，不是并发数量
五个 agent 跑起来乱没有价值。关键是明确每条消息"要不要立刻触发对方"。`send_message` vs `followup_task` 这个区分比"能不能并行"更重要。

### 洞察3: 安全系统的可信计算基（TCB）越小越好
Guardian 的架构设计：policy.md 是唯一可信来源，transcript/args/results 全部是「不可信证据」。这个信任模型清晰。我们的 guard.sh 没有这个区分——规则和证据混在一起。

### 洞察4: Prewarm 是用户体验的杠杆点
首次延迟 500ms 和 50ms，用户感知差异极大。Prewarm 本质上是"把等待时间从用户路径移到后台路径"。任何有固定初始化成本的系统都应该考虑这个模式。

### 洞察5: Fail-closed 的正确姿势
Guardian timeout → 不要说"不安全"，说"没判断完，你重试或问用户"。拒绝 → 说"明确拒绝，不要用 workaround 绕过"。这两种措辞对 agent 行为的影响完全不同。

---

## 实施路线图

### 立即可做（本周）

1. **两档变速渲染**: 用 Python deque 复现 AdaptiveChunkingPolicy，应用到我们的流式输出（Telegram bot 或 CLI）
2. **Guardian cursor**: 在现有的 guardian prompt 系统中加入 history_version 概念，重试时只传增量
3. **send vs trigger 语义**: 在 sub-agent 任务分发中明确区分"入队"和"立即触发"

### 本轮完成

4. **MailboxDeliveryPhase**: 在 governor 的多 agent 场景中，记录"当前 turn 是否已有输出"，用于路由迟到的子 agent 消息
5. **Context 版本号**: 给 session context 加版本号，guardian/外部 agent 调用时传 cursor

### 下一轮

6. **Prewarm**: 如果我们有常驻守护进程，在启动后立即向 API 发一个空请求预热
7. **DeferredNetworkApproval 模式**: 在 hook 系统中实现"执行前预审 + 执行后确认"的两段式审计
8. **TurnDiffTracker**: 实现 Python 版，用于 session 级别的文件变更追踪

---

*R61 by Orchestrator — 2026-04-14*
