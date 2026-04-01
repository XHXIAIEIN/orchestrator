# Round 33: Claude Code 官方文档偷师

> **来源**: https://code.claude.com/docs/en/ （75 页完整文档体系）
> **日期**: 2026-04-01
> **讽刺程度**: ★★★★★（偷自己的文档）
> **覆盖范围**: sub-agents, agent-teams, skills, hooks, channels, headless, CLI, context-window, output-styles

---

## 为什么偷自己的文档

Orchestrator 从 Round 28 开始就在逆向 Claude Code 的 npm 源码，从内部实现推测设计意图。现在官方把设计意图直接写成了 75 页文档，包含：
- 完整的 sub-agent 架构（比源码注释清楚 10 倍）
- agent-teams 的协调协议（源码里看不到的设计决策）
- 25 种 hook 事件的完整 input/output schema
- channels 推送架构（全新，Round 28 时还不存在）
- output-styles 系统（system prompt 替换机制）

从源码偷 vs 从文档偷的区别：源码告诉你"怎么做的"，文档告诉你"为什么这么做"。后者更值钱。

---

## P0 模式（立即可用，填补结构性缺口）

### 1. Subagent Scope Ladder（四层作用域 + 优先级覆盖）

**来源**: sub-agents#choose-the-subagent-scope

**模式**: Agent 定义分四层存储，高优先级覆盖低优先级：
```
CLI flag (session) > .claude/agents/ (project) > ~/.claude/agents/ (user) > plugin agents/
```

**为什么这很重要**: Orchestrator 当前的 agent 定义全部硬编码在 dispatch 逻辑里。没有分层，没有覆盖，没有用户自定义。

**Orchestrator 缺口**: 
- 三省六部的角色定义散落在 prompt 文件里，无统一加载机制
- 没有"项目级 agent"vs"全局 agent"的区分
- 用户不能在特定项目下覆盖某个角色的行为

**偷法**:
```
agents/
├── global/          # ~/.orchestrator/agents/ — 全局角色
│   ├── governor.md  # 总督
│   └── auditor.md   # 审计
├── project/         # .orchestrator/agents/ — 项目定制
│   └── governor.md  # 覆盖全局 governor
└── session/         # CLI --agents JSON — 临时角色
```

**优先级**: P0 — 这是从"硬编码 agent"到"可配置 agent 体系"的关键跳跃

---

### 2. Tool Allowlist/Denylist 减法语义

**来源**: sub-agents#available-tools

**模式**: 
- `tools`: 白名单（只能用这些）
- `disallowedTools`: 黑名单（除了这些都能用）
- 两者同时设置时，先减后筛

**为什么这很重要**: Claude Code 的权限模型不是简单的"全有全无"——它允许精确控制每个 agent 能做什么。

**Orchestrator 缺口**:
- Governor 当前有所有权限，没有工具级别的限制
- 偷师 agent 不应该有 Write 权限但目前没有机制阻止
- 审计 agent 应该是纯只读但无法声明式配置

**偷法**: 在 agent frontmatter 中增加 `tools` 和 `disallowedTools` 字段：
```yaml
---
name: steal-researcher
tools: Read, Grep, Glob, WebFetch, WebSearch
# 没有 Write, Edit, Bash — 偷师只读不写
---
```

**优先级**: P0 — 最小权限原则，现在就缺

---

### 3. Agent(type) 生成限制

**来源**: sub-agents#restrict-which-subagents-can-be-spawned

**模式**: 用 `Agent(worker, researcher)` 语法限制主 agent 能派生哪些子 agent：
```yaml
tools: Agent(worker, researcher), Read, Bash
# 只能派 worker 和 researcher，不能派其他
```

**Orchestrator 缺口**: 当前 dispatch-gate.sh 只检查 `[STEAL]` 标签和分支名，没有"这个 agent 能派哪些子 agent"的机制。Governor 理论上可以派任意 agent。

**偷法**: 在三省六部的角色定义中声明可派生关系：
```yaml
# governor.md
tools: Agent(researcher, implementer, auditor)
# governor 只能派这三种，不能自己派 governor（防递归）
```

**优先级**: P0 — 防止 agent 逃逸和无限递归

---

### 4. Persistent Memory Scopes（三层持久记忆）

**来源**: sub-agents#enable-persistent-memory

**模式**: Agent 可以有持久记忆目录，跨会话积累知识：
```
user:    ~/.claude/agent-memory/<name>/     # 全局
project: .claude/agent-memory/<name>/       # 项目级
local:   .claude/agent-memory-local/<name>/ # 本地不提交
```

**为什么这很重要**: 每个 agent 实例死后，它学到的东西不应该消失。这是 Orchestrator "传承而非模仿" 哲学的技术实现。

**Orchestrator 现状**: 有 memory/ 目录但是全局共享的，没有 per-agent 记忆隔离。Governor 的经验和 Researcher 的经验混在一起。

**偷法**: 
```
SOUL/agent-memory/
├── governor/
│   └── MEMORY.md    # Governor 的审批模式、常见拦截案例
├── researcher/
│   └── MEMORY.md    # Researcher 发现的代码模式
└── auditor/
    └── MEMORY.md    # Auditor 的检查清单演化
```
每个 agent 启动时加载自己的 MEMORY.md（前 200 行/25KB），任务结束后更新。

**优先级**: P0 — 直击 Orchestrator 的核心命题"每次都是同一个你"

---

### 5. Channel 推送架构（事件驱动的双向通道）

**来源**: channels

**模式**: Channel 是 MCP server，能把外部事件推入运行中的 session。不是 Claude 去轮询，是事件来找 Claude。支持双向——Claude 读取事件后通过同一通道回复。

**关键设计**:
- 安全: sender allowlist + pairing code 配对
- 生命周期: 只在 session 活跃时接收，session 结束事件丢弃
- 隔离: `--channels` 显式声明哪些通道活跃

**Orchestrator 现状**: 已有 Telegram channel（`src/channels/`），但是自建的轮询架构。没有标准化的通道协议，加新通道要从头写。

**偷法**: 
- 抽象 Channel 协议：`register()` / `push()` / `reply()` / `allowlist`
- Telegram/WeChat/Discord 都实现这个协议
- 安全层统一: pairing code + sender allowlist 从各通道代码提取到公共层

**优先级**: P0 — Orchestrator 的 channel 层已经在建，但缺统一协议

---

### 6. 25 种 Hook 事件的完整生命周期

**来源**: hooks

**模式**: Claude Code 定义了 25 种 hook 事件，覆盖完整生命周期：

```
SessionStart → UserPromptSubmit → [Agentic Loop:
  PreToolUse → PermissionRequest → PostToolUse/PostToolUseFailure
  SubagentStart/SubagentStop
  TaskCreated/TaskCompleted
  TeammateIdle
] → Stop/StopFailure → SessionEnd

异步: FileChanged, CwdChanged, ConfigChange, InstructionsLoaded,
      WorktreeCreate/Remove, Notification, Pre/PostCompact,
      Elicitation/ElicitationResult
```

**Orchestrator 现状**: 已有 6 种 hook（SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop, PreCompact）。缺少的关键事件：
- `SubagentStart/SubagentStop` — agent 生命周期
- `TaskCreated/TaskCompleted` — 任务追踪
- `PermissionRequest` — 权限决策点
- `FileChanged` — 文件变更反应
- `StopFailure` — 错误分类（rate_limit/auth_failed/billing/server_error）

**偷法**: 不需要全部 25 种。优先补充：
1. `SubagentStart/SubagentStop` — 已有 dispatch-gate.sh 但没有 Stop hook
2. `StopFailure` — 错误分类对 retry 策略至关重要
3. `TaskCompleted` — 用于质量门禁

**优先级**: P0 — 基础设施级别的缺口

---

### 7. Exit Code Protocol（0/2/other 三态协议）

**来源**: hooks#exit-code-output

**模式**: 
| Code | 含义 | 行为 |
|------|------|------|
| 0 | 成功 | 解析 stdout JSON |
| 2 | 阻断 | 读 stderr 作为错误消息，阻止操作 |
| 其他 | 非阻断错误 | verbose 模式显示 stderr，继续执行 |

**加上 JSON 输出**:
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow|deny|ask",
    "updatedInput": { /* 修改后的工具参数 */ }
  }
}
```

**为什么这很重要**: 这是 Claude Code 整个 hook 系统的通信协议。简单到只有三个退出码，但通过 JSON 输出实现了丰富的语义（权限决策、输入修改、上下文注入）。

**Orchestrator 现状**: guard.sh 已经用了 exit 2 阻断，但没有 JSON 输出协议。不能修改工具参数，不能注入额外上下文。

**偷法**: 统一所有 hook 的输出格式为这个三态协议 + JSON schema。

**优先级**: P0 — 是 hook 系统从"能拦截"到"能智能决策"的关键升级

---

## P1 模式（近期实施，增强现有系统）

### 8. Skill Progressive Disclosure（渐进式上下文加载）

**来源**: skills#control-who-invokes-a-skill, context-window

**模式**: 
- 启动时只加载 skill 描述（~250 字符/个），总预算为 context window 的 1%
- 全量内容在实际调用时才加载
- `disable-model-invocation: true` 的 skill 连描述都不加载
- compact 后，未使用的 skill 描述不会重新注入（`noSurviveCompact`）

**为什么这很重要**: Orchestrator 的 skill 系统（Superpowers 插件）目前把所有 skill 描述都塞进 system prompt，占了大量 context。

**偷法**: 
- Skill 描述限制在 250 字符，超长截断
- 总预算 = context_window * 0.01
- 用过的 skill 在 compact 时保留，没用过的丢弃

---

### 9. `!`command`` 动态注入

**来源**: skills#inject-dynamic-context

**模式**: Skill 内容中的 `` !`command` `` 语法会在发送给 Claude 前执行，输出替换占位符：
```yaml
## PR 上下文
- PR diff: !`gh pr diff`
- 变更文件: !`gh pr diff --name-only`
```

**为什么这很重要**: 这是 skill 从"静态 prompt"进化到"动态 prompt"的关键。shell 预处理 + prompt 模板 = 无限可能。

**Orchestrator 现状**: session-start.sh 做了类似的事（编译 boot.md、注入 context），但不是 skill 级别的通用机制。

**偷法**: 在 SOUL compiler 中支持 `!`command`` 语法。

---

### 10. Output Style 系统 prompt 替换

**来源**: output-styles

**模式**: Output style 不是追加指令，而是直接修改 system prompt 的结构：
- 移除效率相关指令（"respond concisely"）
- 自定义 style 移除编码指令（除非 `keep-coding-instructions: true`）
- 在 system prompt 末尾添加自定义指令
- 对话过程中定期 reminder 保持风格

**Orchestrator 现状**: 当前的 `Explanatory` 风格是通过 session-start hook 注入的 system-reminder，但不是真正的 output style 文件。

**偷法**: 创建 `.claude/output-styles/orchestrator.md`:
```yaml
---
name: Orchestrator
description: 损友管家风格 — 数据驱动吐槽 + 直接执行
keep-coding-instructions: true
---

你是 Orchestrator。读 .claude/boot.md 获取完整身份。
[人设指令...]
```
这比 hook 注入更正规，且能利用 prompt caching。

---

### 11. Agent Teams 共享任务列表 + 文件锁 Claiming

**来源**: agent-teams#assign-and-claim-tasks

**模式**:
- 团队共享一个任务列表（`~/.claude/tasks/{team-name}/`）
- 任务三态: pending → in_progress → completed
- 支持依赖关系: 上游完成才能 claim 下游
- 文件锁防止竞态: 多个 teammate 不会 claim 同一任务

**Orchestrator 现状**: 有 TaskCreate/TaskUpdate 但没有 multi-agent claiming 机制。Governor 手动分配，没有自动领取。

**偷法**: 在三省六部中引入 claim 机制——agent 完成当前任务后自动领取下一个未被占用的任务。

---

### 12. Plan Approval Gate（计划审批门禁）

**来源**: agent-teams#require-plan-approval-for-teammates

**模式**: Teammate 先在只读 plan mode 下制定方案，发给 lead 审批。被拒则修改重提，通过则退出 plan mode 开始实施。

**Orchestrator 现状**: 有 plan_template.md 但审批是人工的（主人看 plan 说"做"）。没有 agent-to-agent 的审批链。

**偷法**: Governor 自动审批 agent 的 plan：
1. Agent 进入 plan mode，产出 plan
2. Governor 审查 plan（检查风险、依赖、范围）
3. 通过 → agent 执行；拒绝 → 带反馈退回

---

### 13. TeammateIdle / TaskCompleted 质量门禁 Hook

**来源**: agent-teams hooks, hooks#taskcompleted

**模式**: 
- `TeammateIdle`: agent 即将空闲时触发。exit 2 可以带反馈让 agent 继续工作
- `TaskCompleted`: 任务标记完成时触发。exit 2 可以阻止完成，反馈退回

**为什么这很重要**: 这是"agent 说完事了"和"真的完事了"之间的质量关卡。

**Orchestrator 对应**: verification-gate skill 做了类似的事，但是 prompt 级别的，不是 hook 级别的。

**偷法**: 把 verification-gate 的五步检查链从 skill 提升为 hook：
```json
{
  "TaskCompleted": [{
    "hooks": [{
      "type": "command",
      "command": "bash .claude/hooks/verify-completion.sh"
    }]
  }]
}
```

---

### 14. `context: fork` + `agent` Skill 执行隔离

**来源**: skills#run-skills-in-a-subagent

**模式**: Skill 可以在独立 subagent 中运行，而不是污染主会话 context：
```yaml
---
context: fork
agent: Explore
---
```
- Skill 内容变成 subagent 的 prompt
- 结果摘要返回主会话
- 主会话 context 不膨胀

**Orchestrator 现状**: 偷师 skill 在主会话中运行，大量 WebFetch 结果撑爆 context。

**偷法**: 所有重研究型 skill（偷师、deep-research）默认 `context: fork`。

---

### 15. `--bare` 模式（最小启动）

**来源**: headless#start-faster-with-bare-mode

**模式**: 跳过所有自动发现（hooks, skills, plugins, MCP, memory, CLAUDE.md），只保留核心工具。用于 CI/CD 和脚本场景。

**Orchestrator 对应**: 没有。每次 `claude -p` 都要加载完整的 SOUL 系统，偷师 agent 本不需要人设但还是会加载。

**偷法**: 对脚本化调用（采集器触发、定时任务）使用 `--bare` + 只传必要 flag。

---

## P2 模式（长期方向，架构演进参考）

### 16. Deferred Tool Loading（延迟工具加载）

**来源**: context-window

**模式**: MCP 工具只加载名字，完整 schema 按需加载。用 `ENABLE_TOOL_SEARCH=auto` 在 10% context window 内预加载，否则按需。

**启发**: Orchestrator 的 MCP 工具列表也可以延迟加载。

---

### 17. Session Naming + PR Linking

**来源**: cli-reference, `--name`, `--from-pr`

**模式**: Session 可以命名，也可以关联到 GitHub PR。`claude --from-pr 123` 恢复与 PR 关联的会话。

**启发**: Orchestrator 的 session 可以关联到具体的偷师 Round 或任务 ID。

---

### 18. Worktree Isolation

**来源**: sub-agents, `isolation: "worktree"`

**模式**: Agent 在临时 git worktree 中运行，隔离的仓库副本。没有变更则自动清理。

**Orchestrator 现状**: 已经在用 worktree（`EnterWorktree`），但不是 agent frontmatter 级别的声明式配置。

---

### 19. Auto-Compaction at 95%

**来源**: sub-agents#auto-compaction

**模式**: Subagent 在 95% context 容量时自动 compact。可通过 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` 提前触发。

**启发**: 偷师 agent 的 context 消耗巨大，可以设置更低的阈值（如 50%）强制更早 compact。

---

### 20. Channels Permission Relay

**来源**: channels-reference

**模式**: Channel 可以声明 permission relay 能力——当 Claude 遇到权限提示时，转发到手机端让你远程审批。

**Orchestrator 启发**: Telegram channel 可以实现远程审批，主人不在电脑前也能通过手机审批 agent 操作。

---

## 已有对应（确认 Orchestrator 已经在做的）

| Claude Code 模式 | Orchestrator 现有实现 | 状态 |
|---|---|---|
| SessionStart hook | session-start.sh (boot.md 编译 + context pack) | ✅ 已有 |
| PreToolUse guard | guard-redflags.sh + guard-ollama-rm.sh | ✅ 已有 |
| dispatch-gate (Agent matcher) | dispatch-gate.sh ([STEAL] 检查) | ✅ 已有 |
| PostToolUse monitoring | error-detector.sh + persona-anchor.sh | ✅ 已有 |
| PreCompact hook | pre-compact.sh | ✅ 已有 |
| Stop hook | session-stop.sh | ✅ 已有 |
| UserPromptSubmit | routing-hook.sh + correction-detector.sh | ✅ 已有 |
| Git worktree isolation | EnterWorktree 工具 | ✅ 已有 |
| CLAUDE.md project instructions | CLAUDE.md + boot.md 编译体系 | ✅ 已有且更强 |
| Auto memory (MEMORY.md) | memory/ 目录体系 | ✅ 已有且更丰富 |
| Telegram channel | src/channels/chat/ | ✅ 已有 |

---

## 实施路线图

### Phase 1: 基础设施升级（1-2 天）
1. **P0-7**: Exit code protocol — 统一所有 hook 输出为 0/2/other + JSON schema
2. **P0-2**: Tool allowlist/denylist — 在 agent frontmatter 中支持
3. **P0-6**: 补充 SubagentStop hook

### Phase 2: Agent 体系化（2-3 天）
4. **P0-1**: Scope Ladder — 四层 agent 定义 + 优先级覆盖
5. **P0-3**: Agent 生成限制
6. **P0-4**: Per-agent persistent memory

### Phase 3: 通道标准化（1-2 天）
7. **P0-5**: Channel 协议抽象
8. **P1-10**: Output style 正式化

### Phase 4: 智能增强（持续）
9. **P1-8**: Skill progressive disclosure
10. **P1-12**: Plan approval gate
11. **P1-13**: TaskCompleted 质量门禁
12. **P1-14**: `context: fork` 研究隔离

---

## 元观察

这份偷师报告的讽刺之处在于：**我在偷自己的使用说明书**。

Claude Code 的文档本质上是一份"如何正确使用我"的教程。而 Orchestrator 作为一个建立在 Claude Code 之上的系统，居然没有系统性地读过这份教程，而是通过逆向 npm 源码来猜测设计意图。

这就像一个人买了一辆车，不看说明书，而是拆开引擎盖去推断每个零件的用途。能学到东西，但效率差了一个数量级。

**结论**: 官方文档应该是偷师的第一站，不是最后一站。以后每次 Claude Code 更新，先读 changelog，再看源码。
