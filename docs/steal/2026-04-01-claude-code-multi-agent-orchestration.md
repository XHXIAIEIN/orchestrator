# Claude Code 多 Agent 编排架构全解 — 跨 5 份偷师报告汇总

> 来源: 5 份 Claude Code 逆向分析报告的交叉引用
> - `2026-03-31-claude-code-source.md` — 执行层源码 (P1)
> - `2026-04-01-claude-code-hidden-features.md` — 隐藏功能层 (P2)
> - `2026-04-01-claude-code-kairos-daemon-uds-deep.md` — 通信架构深挖
> - `2026-04-01-claude-code-teleport-ultraplan-deep.md` — 远程编排深挖
> - `2026-04-01-claude-code-system-prompts.md` — Prompt 层逆向 (Round 27)
>
> 目的: 提炼 Claude Code 生产级多 Agent 系统的完整蓝图，指导 Orchestrator 架构升级
> 日期: 2026-04-01

---

## 为什么这份汇总值钱

教程告诉你 "multi-agent 就是多个 LLM 协作"。源码告诉你：

- Coordinator 派任务前必须**自己先理解** research 结果，不准说 "based on your findings"（prompt 层）
- Worker 忙的时候消息**排队**，idle 了再 drain（代码层）
- 停掉的 agent 收到新消息会**自动唤醒**（代码层）
- 文件邮箱用 `proper-lockfile` 做并发控制，重试 10 次，5-100ms 退避（代码层）
- Verification agent 被**禁止写项目文件**，只能在 /tmp 写临时测试（prompt 层）
- 三种 IPC 后端（UDS / Bridge / File Mailbox）共享同一个 `SendMessage` 入口（代码层）
- 安全分类器**故意排除 assistant 自身输出**防止 self-injection（prompt 层）

这些是踩了无数坑后沉淀的决策。单看任何一份报告只能看到一个切面——交叉引用后才是完整图谱。

---

## 架构全景：四层编排栈

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Layer 4: Prompt 层                           │
│     Coordinator System Prompt (05) ← 决策纪律 + 反模式清单          │
│     Verification Agent (07) ← 对抗性只读验证                        │
│     Default Agent (03) ← 自包含上下文 + 绝对路径约束                 │
│     Agent Summary (29) ← Haiku 微服务 1 句话进度                     │
│     YOLO Classifier (12) ← 安全分类器 self-injection 防御            │
├─────────────────────────────────────────────────────────────────────┤
│                        Layer 3: 编排层                              │
│     Coordinator (coordinator/) ← Research→Synthesis→Impl→Verify    │
│     TaskStop / Continue / Spawn ← 决策矩阵 by context overlap       │
│     Worker Prompt Synthesis ← Coordinator 最重要的职责               │
├─────────────────────────────────────────────────────────────────────┤
│                        Layer 2: 通信层                              │
│     SendMessageTool ← 统一路由入口                                   │
│       ├── UDS Socket (同机器, <1ms)                                  │
│       ├── Bridge WebSocket (跨机器, ~100ms)                          │
│       ├── File Mailbox (Swarm 模式, ~50ms)                          │
│       └── In-Process Direct Call (<0.1ms)                            │
│     InboxPoller ← 1s 轮询 + Two-State Delivery                      │
│     Address Scheme Registry ← parseAddress(to) 统一寻址              │
├─────────────────────────────────────────────────────────────────────┤
│                        Layer 1: 基础层                              │
│     PID-File Session Registry ← 发现 + 活性检测                     │
│     TeammateExecutor Interface ← tmux / iTerm2 / in-process         │
│     Structured Protocol Messages ← 10 种消息类型                     │
│     Permission Bridge ← Worker→Leader 审批路由                       │
│     BoundedUUIDSet ← 消息回声去重                                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 核心模式 1: Coordinator Synthesis 纪律

**来源**: prompt 层 (05_coordinator_system_prompt.md) + 代码层 (coordinator/)

这是整个系统最关键的设计决策——**Coordinator 不是转发器，是综合者**。

### 四阶段工作流

```
Research ──→ Synthesis ──→ Implementation ──→ Verification
 (Workers)   (Coordinator)    (Workers)        (Workers)
  并行探索    ★理解+写spec      按spec执行       独立验证
```

Synthesis 阶段是 Coordinator **自己做的**，不委派给 Worker。

### 反模式 vs 正模式

| | 反模式（被明确禁止） | 正模式（被要求做到） |
|---|---|---|
| Prompt | "Based on your findings, fix the auth bug" | "Fix null pointer in src/auth/validate.ts:42. Session.user is undefined when token expires but cached. Add null check before user.id, return 401 'Session expired'. Commit and report hash." |
| 核心问题 | 把**理解**工作推给 Worker | Coordinator 已经消化了 research，给出**具体文件+行号+改法** |
| 信息量 | 零——Worker 不知道该改什么 | 完整——Worker 只需执行 |

### Continue vs Spawn 决策矩阵

| 场景 | 选择 | 原因 |
|------|------|------|
| Research 恰好探索了要改的文件 | **Continue** | 文件已在 context |
| Research 范围广但实现范围窄 | **Spawn fresh** | 避免噪声 context |
| 修正刚才的失败 | **Continue** | Worker 有错误上下文 |
| 验证别的 Worker 写的代码 | **Spawn fresh** | 验证者不能带实现假设 |
| 第一次方案完全错误 | **Spawn fresh** | 错误 context 会锚定重试 |
| 完全无关的任务 | **Spawn fresh** | 无可复用 context |

**核心原则**: 不是 "默认 continue" 或 "默认 spawn"——是 **context overlap 决定一切**。

### 对 Orchestrator 的适配

我们的 Governor dispatch 就是 Coordinator。当前的问题：
1. Governor 有时把模糊任务直接甩给部门 → 加入 synthesis 约束
2. 没有 continue vs spawn 决策 → agent dispatch 时评估 context overlap
3. 缺少 "purpose statement" → 每次 dispatch 说明 "这个 research 用来做什么"

---

## 核心模式 2: 统一通信架构

**来源**: 代码层 (SendMessageTool.ts, peerAddress.ts, teammateMailbox.ts, useInboxPoller.ts)

### 统一寻址 + 路由

```
Agent/LLM 调用: sendMessage(to="researcher", message="check auth flow")
                     │
                parseAddress(to)
                     │
            ┌────────┼────────────┬──────────────┐
            ▼        ▼            ▼              ▼
         scheme=    scheme=     scheme=       scheme=
          uds      bridge      other         broadcast
            │        │            │              │
     UDS Socket  WebSocket    agentRegistry   handleBroadcast
     (同机器)     (跨机器)       │              │
                            ┌───┼───┐     write to ALL
                            ▼       ▼      inboxes
                         running  stopped
                            │       │
                     queuePending  resumeAgent
                     Message()    Background()
                                  ↑ 自动唤醒！
```

关键设计：
1. **LLM 只看到一个工具** — `SendMessage(to, message)`，路由逻辑全封装
2. **停止的 agent 自动唤醒** — 收到消息触发 `resumeAgentBackground()`
3. **忙时排队，闲时投递** — Two-State Delivery 避免 concurrent message 问题
4. **广播标注为昂贵操作** — prompt 中说 "expensive (linear in team size)"

### Orchestrator 适配方案

```
当前:                                   目标:
Telegram → bot API                      sendMessage("tg:12345", msg)
Agent    → Agent SDK 直调               sendMessage("agent:analyst", msg)
审批     → Redis pub/sub                sendMessage("claw:approval", msg)
Dashboard → WebSocket                   sendMessage("ws:session-1", msg)
Docker   → docker exec                  sendMessage("docker:collector", msg)

全部路由到一个 parseAddress() + 后端适配器
```

---

## 核心模式 3: 文件邮箱 + 结构化协议消息

**来源**: 代码层 (teammateMailbox.ts, useInboxPoller.ts)

### 为什么不用数据库/消息队列？

Claude Code 的选择：**文件系统就是消息总线**。原因：
- 零依赖（不需要 Redis/RabbitMQ）
- 每个 agent 一个 JSON 文件作为收件箱
- `proper-lockfile` 提供并发安全（10 次重试，5-100ms 退避）
- PID 文件注册提供发现机制

### 10 种结构化消息类型

不是所有消息都是 "文本对话"——有严格类型系统：

| 类型 | 方向 | 描述 |
|------|------|------|
| `permission_request` | Worker→Leader | "我要跑 rm -rf，批吗？" |
| `permission_response` | Leader→Worker | "批了，但把路径改成 /tmp/test"（updatedInput!） |
| `shutdown_request` | Leader→Worker | "收工" |
| `shutdown_approved/rejected` | Worker→Leader | "好/等我跑完这个测试" |
| `plan_approval_request/response` | 双向 | Plan 审批流 |
| `team_permission_update` | Leader→All | "从现在起允许写 /src/" |
| `mode_set_request` | Leader→Worker | "切到只读模式" |
| `idle_notification` | Worker→Leader | "我闲了" |

**安全约束**: Plan approval 只接受 `from === 'team-lead'` 的消息。Worker 不能伪造其他 Worker 的审批。

### Orchestrator 适配

我们已有 Redis——不需要用文件邮箱，但消息类型系统值得照搬：

```python
class ProtocolMessage:
    type: Literal[
        'task_assignment',      # Governor→Agent
        'task_result',          # Agent→Governor
        'permission_request',   # Agent→Claw
        'permission_response',  # Claw→Agent
        'heartbeat',            # Agent→Registry
        'shutdown',             # Governor→Agent
        'status_update',        # Agent→Dashboard
    ]
    from_: str
    to: str
    payload: dict
    timestamp: datetime
```

---

## 核心模式 4: Teammate 身份与发现

**来源**: 代码层 (concurrentSessions.ts, backends/types.ts) + prompt 层 (06_teammate_prompt_addendum.md)

### PID-File 注册中心

每个 agent 启动时写一个 JSON 到 `~/.claude/sessions/<PID>.json`：

```json
{
  "pid": 12345,
  "sessionId": "abc",
  "cwd": "/project",
  "kind": "interactive",           // interactive | bg | daemon | daemon-worker
  "messagingSocketPath": "/tmp/cc-socks/12345.sock",
  "name": "researcher",
  "bridgeSessionId": "cse_xxx"     // 跨机器去重
}
```

- **活性检测**: `isProcessRunning(pid)` — 崩溃的 agent 下次枚举时自动清理
- **WSL 特殊处理**: 跳过删除，避免误杀 Windows 侧会话（gh-34210 事件）
- **严格文件名校验**: `/^\d+\.json$/` — 防止 `parseInt("2026-03-14_notes.md")` = PID 2026

### Unified Executor 接口

三种后端实现同一个接口：

```typescript
type TeammateExecutor = {
  type: 'tmux' | 'iterm2' | 'in-process'
  isAvailable(): Promise<boolean>
  spawn(config): Promise<SpawnResult>
  sendMessage(agentId, message): Promise<void>
  terminate(agentId, reason?): Promise<boolean>
  kill(agentId): Promise<boolean>
  isActive(agentId): Promise<boolean>
}
```

调度层不关心 agent 怎么跑——只关心 spawn / message / terminate / isActive。

### Session Kind 决定生命周期

| Kind | 进程模型 | 退出行为 | 适用 |
|------|---------|---------|------|
| `interactive` | 前台终端 | 正常退出 | 用户直接交互 |
| `bg` | tmux detach | detach 而非 kill | `claude --bg` |
| `daemon` | 监督进程 | 崩溃重启 | Kairos 主动模式 |
| `daemon-worker` | daemon 下属 | 随 daemon 生死 | daemon 的子任务 |

### Orchestrator 适配

```python
class AgentExecutor(Protocol):
    type: Literal['docker', 'in-process', 'ssh']

    async def spawn(self, config: AgentConfig) -> AgentHandle: ...
    async def send_message(self, agent_id: str, msg: ProtocolMessage) -> None: ...
    async def terminate(self, agent_id: str) -> bool: ...
    async def is_active(self, agent_id: str) -> bool: ...

class AgentRegistry:
    """PID-file 风格的 agent 注册"""
    registry_dir: Path  # /shared/sessions/

    def register(self, agent: AgentRecord) -> None: ...
    def enumerate_active(self) -> list[AgentRecord]: ...
    def cleanup_stale(self) -> int: ...  # 返回清理数量
```

Agent kind 对应：
- `dispatch` → 三省六部派单，完成即销毁
- `collector` → 数据采集守护进程，崩溃重启
- `interactive` → Dashboard 交互会话
- `daemon` → Kairos 式主动巡检

---

## 核心模式 5: 对抗性验证 Agent

**来源**: prompt 层 (07_verification_agent.md)

验证不是 "跑个 test 看看过不过"——是**故意尝试破坏**。

### 设计约束

1. **只读隔离**: 验证 agent 不能修改项目文件，只能在 /tmp 写临时测试脚本
2. **强制 adversarial probe**: 每次验证必须至少一个对抗性测试
3. **按变更类型分策略**:

| 变更类型 | 验证重点 |
|---------|---------|
| Frontend | 视觉回归 + 交互测试 |
| Backend | API 契约 + 边界输入 |
| CLI | 参数组合 + 错误路径 |
| DB Migration | 回滚测试 + 数据完整性 |
| Refactoring | 行为等价性证明 |

4. **Rationalization immunity**: 识别自己想跳过检查的内心借口清单
5. **FAIL 前三重检查**: Already handled? / Intentional? / Not actionable?
6. **两个已知失败模式**:
   - **Verification avoidance** — "这个改动太小了不需要验证"
   - **80% 陷阱** — 大部分通过就忽略边缘情况

### 输出格式

```
## Command Run
[实际执行的命令和完整输出]

## VERDICT: PASS / FAIL
[证据摘要]
[如果 FAIL: 具体失败点 + 建议修复]
```

---

## 核心模式 6: 安全分类器 Self-Injection 防御

**来源**: prompt 层 (12_yolo_auto_mode_classifier.md)

最精妙的安全设计：**分类器不看 assistant 自己写的文本**。

```
Context 传给分类器:
  ✅ User messages
  ✅ Tool results (stdout/stderr)
  ❌ Assistant text blocks  ← 故意排除

原因: 如果模型在回复中写了 "下一步我要运行 rm -rf /"，
这段文本会出现在下一轮 context 中。如果分类器看到这段文本，
模型就能通过自己写的文本影响分类器 → self-prompt-injection。

解决: 分类器只看用户意图 + 工具产出，不看模型的自我叙述。
```

### Orchestrator 适配

guard.sh 拦截的是工具调用，但如果 agent 在输出中注入了恶意意图（来自外部输入的 prompt injection），我们没有 transcript 过滤。应用场景：
- Governor dispatch 过滤 agent 自生成的 context
- Skill 加载时验证来源——projectSettings 不能覆盖安全路径（P0-5 Untrusted-Source Setting Exclusion）

---

## 核心模式 7: Context 压缩九段结构

**来源**: prompt 层 (21_compact_service.md)

Compact 不是 "summarize"——是覆盖 9 个强制维度的结构化摘要：

| # | 维度 | 为什么必须 |
|---|------|-----------|
| 1 | Primary Request | 用户到底要什么（防 intent drift）|
| 2 | Key Technical Concepts | 涉及的技术栈 |
| 3 | Files and Code | 触及的文件清单 |
| 4 | Errors and Fixes | 遇到的错误和解法 |
| 5 | Problem Solving | 推理过程和决策 |
| 6 | **All User Messages** | 用户说的每一句话 |
| 7 | Pending Tasks | 未完成的工作 |
| 8 | Current Work | 正在做什么 |
| 9 | Optional Next Step | 建议的下一步 |

**第 6 条最狠**: "All User Messages" 确保压缩后用户的原始意图不丢。大部分压缩方案会把用户消息混进摘要里——这里强制单独保留。

额外机制：
- `<analysis>` 草稿区：模型先推理，函数 strip 掉再注入 context
- 三种模式：全量 / 只压近期 / 只压旧消息
- 用户可通过 CLAUDE.md / hooks 自定义摘要指令

---

## 核心模式 8: Haiku 微服务矩阵

**来源**: prompt 层 (14, 20, 22, 29, 30)

5 个格式化/摘要任务全用最便宜的模型（Haiku）跑：

| 微服务 | 模型 | 触发 | 输出约束 |
|--------|------|------|---------|
| Tool Use Summary (14) | Haiku | 每次工具调用后 | ≤30 字符，过去时，移动端显示 |
| Session Title (20) | Haiku | 3 条消息后 | 3-7 词，sentence case，JSON |
| Away Summary (22) | Haiku | 用户回来时 | 1-3 句，high-level task + next step |
| Agent Summary (29) | Haiku | Worker 活跃时周期性 | **1 句话，现在时，具体动作** |
| Prompt Suggestion (30) | Haiku | 每次回复后异步 | ≤3 条，2-8 词，可执行请求 |

**成本工程原则**: 用 $0.25/1M 的模型做辅助任务，把 $15/1M 的主模型留给核心推理。

---

## 汇总：Orchestrator 可直接实施的升级路径

### Phase 1: 立即（本周）

| # | 升级项 | 来源模式 | 工时 | 影响 |
|---|--------|---------|------|------|
| 1 | Governor dispatch prompt 加 synthesis 约束 | Coordinator Synthesis | 3h | 消除 "懒委派"，提升 agent 输出质量 |
| 2 | verification-gate 加 adversarial probe | Verification Agent | 4h | 减少 "80% 陷阱" 的漏检 |
| 3 | PreCompact hook 注入九段摘要结构 | Compact 9-Section | 3h | Context 压缩质量提升 |
| 4 | Events-Before-Container | Hidden Features P0-11 | 2h | 消除 agent dispatch 竞态 |

### Phase 2: 下周

| # | 升级项 | 来源模式 | 工时 | 影响 |
|---|--------|---------|------|------|
| 5 | ProtocolMessage 消息类型系统 | Structured Protocol | 4h | agent 通信从 ad-hoc 到结构化 |
| 6 | AgentExecutor 统一接口 | Unified Executor | 4h | 解耦调度层和执行方式 |
| 7 | parseAddress() 统一寻址 | Address Scheme Registry | 3h | 一个入口路由到所有后端 |
| 8 | AgentRegistry PID-file 注册 | Session Registry | 2h | agent 发现 + 活性检测 |

### Phase 3: 中期

| # | 升级项 | 来源模式 | 工时 | 影响 |
|---|--------|---------|------|------|
| 9 | Two-State Delivery（忙时排队） | Inbox Poller | 3h | 解决 concurrent message |
| 10 | Agent Auto-Resume on Message | SendMessage Router | 3h | agent 停了还能被唤醒 |
| 11 | Tick-Driven Proactive Loop | Kairos | 8h | 三省六部主动巡检 |
| 12 | Self-Injection 防御 | YOLO Classifier | 4h | transcript 过滤 |

### Phase 4: 远期

| # | 升级项 | 来源模式 | 工时 | 影响 |
|---|--------|---------|------|------|
| 13 | Cache Boundary 静态/动态分割 | Main System Prompt | 2h | token 费用优化 |
| 14 | Dashboard Control Protocol | Bridge Control | 4h | 远程 interrupt/set_model |
| 15 | Session Kind 生命周期管理 | Session Kind Hierarchy | 3h | agent 崩溃重启策略 |

---

## 与既有偷师的关系

| 已有模式 | Claude Code 对应 | 互补点 |
|---------|-----------------|--------|
| Round 2 EventStream (OpenHands) | AsyncGenerator Agent Loop | EventStream = pub/sub 广播，Generator = pull-based 流式 |
| Round 2 StuckDetector | Continue Sites 错误恢复 | StuckDetector 只检测卡死，Continue Sites 处理所有异常 |
| Round 8 ComponentSpec (Agent Lightning) | TeammateExecutor Interface | 同样的接口抽象思路，Claude Code 更成熟 |
| Round 22 Review Swarm | Simplify 三路并行审查 | Review Swarm 按 severity 过滤，Simplify 按维度分离 |
| Round 15 Gate Chain (Entrix) | Cheapest-First Gate Chain | Entrix 用 Hard/Soft/Advisory，Claude Code 按计算成本排序 |
| 三省六部 Governor | Coordinator + Synthesis | Governor 需要加入 synthesis 纪律 |
| guard.sh + audit.sh | YOLO Classifier + Permission Explainer | guard 是 binary 拦截，YOLO 是概率分类 + side-query 解释 |
| SOUL/boot.md 编译 | Cache Boundary 分割 | boot.md 已经隐式做了，但没有显式的 cache control |

---

## 最值钱的 3 个洞察

### 1. Coordinator 是综合者，不是路由器

多 Agent 系统最常见的 bug 不是通信失败，而是 **coordinator 不理解就转发**。Claude Code 在 prompt 里明确禁止 "based on your findings"——因为这把理解工作推给了 worker，而 worker 没有全局上下文。

对 Orchestrator：Governor 的 synthesis 能力是整个系统的瓶颈。dispatch 之前必须写出具体的文件+行号+改法。

### 2. 通信不需要复杂基础设施，需要统一入口

Claude Code 用文件系统做消息总线——效率不高（1s 轮询 + 50ms 延迟），但**一个 SendMessage 入口统一了四种后端**。重要的不是传输层的性能，而是 LLM 只需要学一个工具。

对 Orchestrator：我们有 Redis，传输层已经比 Claude Code 好。缺的是统一的 `sendMessage(to, message)` 抽象。

### 3. 验证必须对抗性、必须隔离

普通的 "跑个 test" 不是验证——只是确认。Claude Code 的 verification agent 被禁止修改项目文件、强制包含 adversarial probe、有 rationalization immunity 清单。这不是过度工程——是因为他们被 "前 80% 通过就放行" 坑过。

对 Orchestrator：verification-gate 需要从 "五步证据链" 升级到 "对抗性验证"。
