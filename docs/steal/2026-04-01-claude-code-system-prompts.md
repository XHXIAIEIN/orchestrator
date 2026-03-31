# Round 23 P1: Claude Code System Prompts 逆向 — 偷师报告

> 来源: https://github.com/Leonxlnx/claude-code-system-prompts
> 性质: Claude Code 全部 30 个内部 system prompt 的逆向提取与文档化
> 星数: 609 ⭐ (2026-03-31 更新)
> 互补: 与 `2026-03-31-claude-code-source.md`（源码结构）形成 **代码 + Prompt 双视角**

---

## 架构全景

Claude Code 的 prompt 系统不是一个大 blob——是 **30 个模块化组件** 按条件动态拼装的管线：

```
┌─────────────────────────────────────────────────────────┐
│                    Prompt Assembly Pipeline              │
│                                                         │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐           │
│  │ 01 Main  │ + │ 04 Cyber │ + │ 24 Memory│  = Static │
│  │  System  │   │  Safety  │   │  Loading │  Prefix   │
│  └──────────┘   └──────────┘   └──────────┘  (cached) │
│       ↓              ↓              ↓                   │
│  ════════════ CACHE BOUNDARY ════════════════           │
│       ↓              ↓              ↓                   │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐           │
│  │ Env Info │ + │ Feature  │ + │ Session  │  = Dynamic│
│  │ (OS/CWD) │   │  Flags   │   │  State   │  Suffix   │
│  └──────────┘   └──────────┘   └──────────┘           │
└─────────────────────────────────────────────────────────┘

Multi-Agent Layer:
  05 Coordinator ──→ 03 Default Agent / 08 Explore / 07 Verification
                     06 Teammate Addendum (swarm mode)
                     09 Agent Creation Architect

Safety Layer:
  12 YOLO Classifier ──→ 17 Auto Mode Critique
  11 Permission Explainer (side-query, concurrent)

Context Management:
  21 Compact Service ──→ 16 Memory Selection ──→ 24 Memory Loading
  15 Session Search ──→ 22 Away Summary

Micro Services (Haiku):
  14 Tool Use Summary | 20 Session Title | 29 Agent Summary | 30 Prompt Suggestion
```

---

## 可偷模式

### P0-1: Cache Boundary 静态/动态分割

**来源**: 01_main_system_prompt.md

**机制**: System prompt 被显式分成两段——
- **静态前缀**（身份、规则、工具定义、安全策略）→ 可被 prompt cache 缓存
- **动态后缀**（环境变量、会话状态、feature flags）→ 每次请求重新注入

用 `DYNAMIC_BOUNDARY` 标记分割点。静态部分占 80%+ tokens，缓存命中率极高。

**对 Orchestrator 的价值**: 我们的 SOUL/boot.md 编译产物已经隐式做了类似的事（~1.7K tokens 固定），但没有显式的 cache boundary 设计。如果未来用 API 直接调 Claude，这个分割能省大量 token 费用。

**实施**: 中期 — 等 Agent SDK 支持 prompt cache control 后实施
**难度**: 2h（标记分割点）+ 取决于 SDK 支持

---

### P0-2: Coordinator Synthesis 纪律 — "不准懒委派"

**来源**: 05_coordinator_system_prompt.md

**机制**: Coordinator 的核心职责是 **synthesis**（综合），不是转发。明确禁止：
- ❌ "Based on your findings, implement the changes"（把理解工作推给 worker）
- ✅ Coordinator 必须自己消化 research 结果，写出具体 spec 再派给 worker

四阶段工作流：**Research → Synthesis → Implementation → Verification**

关键决策矩阵——Continue vs Spawn new worker：
- Context overlap 高 → Continue 现有 worker
- Context overlap 低 → Spawn 新 worker
- 明确的反模式清单 + 正面示例

**对 Orchestrator 的价值**: 三省六部的中书省（决策）和吏部（派单）之间就缺这个 synthesis 层。目前 Governor dispatch 有时会把模糊任务直接甩给部门，相当于 "based on your findings" 的翻版。

**实施**:
1. Governor dispatch prompt 加入 synthesis 约束：dispatch 前必须写出具体 spec
2. 添加 "懒委派" 检测规则（prompt 中禁止的短语列表）

**难度**: 3h
**优先级**: P0 — 直接改善 dispatch 质量

---

### P0-3: Verification Agent 对抗性设计

**来源**: 07_verification_agent.md

**机制**: 专门的验证 agent，核心设计原则：
1. **只读隔离**: 不允许修改任何项目文件，只能在 `/tmp` 写临时测试
2. **对抗性 probing**: 每次验证必须包含至少一个 adversarial probe（故意试图破坏的测试）
3. **Rationalization immunity 清单**: 识别自己想跳过检查时的内心借口
4. **按变更类型的验证策略**: Frontend / Backend / CLI / Infra / Mobile / Data / ML / DB Migration / Refactoring 各有专门检查项
5. **FAIL 前三重检查**: Already handled? / Intentional? / Not actionable? — 防止误报
6. **两个已知失败模式**:
   - Verification avoidance（找借口不验证）
   - "被前 80% 迷惑"（大部分通过就忽略边缘情况）

输出格式强制要求：Command run block + VERDICT（PASS/FAIL + evidence）

**对 Orchestrator 的价值**: 我们的 verification-gate skill 是五步证据链，但缺少：
- 对抗性 probe 的强制要求
- 按变更类型的验证策略分支
- Rationalization immunity（已有文件但未集成到验证流程）

**实施**:
1. verification-gate skill 加入 adversarial probe 必选项
2. 按任务类型（采集器/分析/前端/prompt）分支验证策略
3. 集成 rationalization-immunity.md 到验证 agent prompt

**难度**: 4h
**优先级**: P0 — 直接提升验证可靠性

---

### P0-4: YOLO 分类器的 Self-Injection 防御

**来源**: 12_yolo_auto_mode_classifier.md

**机制**: Auto-mode 安全分类器有一个精妙的防注入设计——
**Assistant text blocks 被刻意排除在分类器的 transcript 之外**。

原因：如果模型在上一轮回复中写了 "接下来我要运行 rm -rf /"，这段文本会出现在下一轮的 context 中。如果分类器看到这段文本，模型就能通过自己写的文本影响分类器的判断——这是一种 self-prompt-injection。

解决方案：分类器只看 user messages + tool results，不看 assistant text。

**对 Orchestrator 的价值**: guard.sh 拦截的是工具调用层面，但如果 agent prompt 里有恶意内容（来自外部输入），我们没有 "transcript 过滤" 机制。这个思路可以应用到：
- Governor dispatch 时过滤 agent 自生成的上下文
- Skill 加载时验证来源

**实施**: 中期 — 等有具体攻击向量再针对性实施
**难度**: 评估 2h，实施取决于场景

---

### P0-5: Compact Service 九段强制摘要结构

**来源**: 21_compact_service.md

**机制**: 对话压缩不是自由发挥的 "summarize"——是强制覆盖 9 个维度的结构化摘要：

1. **Primary Request** — 用户最终目标
2. **Key Technical Concepts** — 涉及的技术栈/概念
3. **Files and Code** — 触及的文件和关键代码
4. **Errors and Fixes** — 遇到的错误和解决方案
5. **Problem Solving** — 推理过程和决策
6. **All User Messages** — 用户说的每一句话（防 intent drift）
7. **Pending Tasks** — 未完成的工作
8. **Current Work** — 正在做什么
9. **Optional Next Step** — 建议的下一步

额外机制：
- `<analysis>` 草稿区：模型先在 analysis 标签里推理，`formatCompactSummary()` 函数会 strip 掉再注入 context——**中间推理过程对用户不可见**
- 三种模式：全量压缩 / 只压近期 / 只压旧消息
- 用户可通过 CLAUDE.md 或 hooks 自定义摘要指令

**对 Orchestrator 的价值**: 我们目前没有系统性的 context 压缩。长对话靠 Claude 自带的 auto-compact，没有自定义结构。这 9 段结构可以直接借鉴到：
- Agent SDK 的 long-running task 的 checkpoint 摘要
- Telegram bot 对话的 context window 管理

**实施**:
1. 写一个 compact prompt template，覆盖 9 段维度
2. 在 PreCompact hook 中注入自定义摘要指令

**难度**: 3h
**优先级**: P0 — context 质量直接影响所有 agent 表现

---

### P0-6: Permission Explainer 并发侧查询

**来源**: 11_permission_explainer.md

**机制**: 当用户需要审批一个工具调用时，系统并发发起一个侧查询给主模型，生成结构化的风险评估：

```json
{
  "explanation": "这个命令做什么（1-2 句）",
  "reasoning": "我为什么要跑这个命令（以 I 开头）",
  "risk": "可能出什么问题（15 字以内）",
  "riskLevel": "LOW | MEDIUM | HIGH"
}
```

关键：这个查询与权限提示 **并发执行**，不阻塞主流程。

**对 Orchestrator 的价值**: guard.sh 目前是 binary 的拦截/放行。可以在拦截时附加一个类似的 risk assessment，帮助用户做审批决策。

**实施**: 低优先级 — guard.sh 的审批场景不多
**难度**: 2h

---

### P1-1: Explore Agent 只读隔离 + Thoroughness 分级

**来源**: 08_explore_agent.md

**机制**:
- **严格只读**: 禁止 Write/Edit/创建/删除/移动/复制
- **工具白名单**: 只能用 Glob、Grep、Read、和只读 Bash（ls, git status, git log, git diff, find, cat）
- **不允许子 agent**（防止递归）
- **省略 CLAUDE.md**（主 agent 已有完整上下文，减少 token）
- **Thoroughness 分级**: quick / medium / very thorough
- **触发条件**: 至少 3 次简单搜索后才升级到 Explore agent

**对 Orchestrator 的价值**: 我们的 agent dispatch 没有工具权限分级。所有 agent 都有完整的读写权限。可以引入只读 agent 用于：
- 采集器状态检查
- 代码审查的信息收集阶段

**难度**: 3h
**优先级**: P1

---

### P1-2: Agent Summary 极简约束（1 句 + 现在时 + 具体动作）

**来源**: 29_agent_summary.md

**机制**: Coordinator 需要实时了解 worker 进度，但不需要长篇大论。用 Haiku 生成 **严格 1 句话**的进度摘要：

- ✅ "Reading the authentication middleware to understand token validation"
- ❌ "Working on the task"（太模糊）
- ❌ "I've made progress on the authentication system"（过去时，不具体）

**对 Orchestrator 的价值**: Governor dispatch 的 agent 进度跟踪可以用这个模式——极低成本的态势感知。

**难度**: 1h
**优先级**: P1

---

### P1-3: Memory Loading 五层优先级 + @include 递归

**来源**: 24_memory_instruction.md

**机制**: CLAUDE.md 加载不是简单的读文件——是五层优先级系统：

1. **Enterprise** (`/etc/claude-code/settings.json`) — 最低优先级
2. **User** (`~/.claude/CLAUDE.md`) — 个人全局
3. **Project** (`CLAUDE.md` / `.claude/CLAUDE.md`) — 项目级
4. **Rules** (`.claude/rules/*.md`) — 模块化规则
5. **Local** (`CLAUDE.local.md`) — 私有本地覆盖 — 最高优先级

额外特性：
- **@include 指令**: `@path`、`@./relative`、`@~/home`、`@/absolute`，最大递归深度 5 层，防循环检测
- **Frontmatter `paths` 字段**: 条件注入——只在 active file 匹配 glob 时加载规则
- **单文件 40000 字符上限**
- **HTML 注释被 strip**

**对 Orchestrator 的价值**: 我们的 SOUL 系统已经有类似的分层（boot.md → context packs → memory），但缺少：
- `paths` 条件注入（只在编辑特定文件时加载对应规则）
- 严格的优先级覆盖语义

**难度**: 评估 — 当前架构已足够，标记为参考
**优先级**: P1（参考）

---

### P1-4: Simplify 三 Agent 并行审查（关注点分离）

**来源**: 19_simplify_skill.md

**机制**: `/simplify` 不是一个 agent 做所有检查——是三个并行 agent 各管一个维度：

1. **Code Reuse Agent**: 重复逻辑、已有工具函数未使用
2. **Code Quality Agent**: 命名、分解、标准符合度、code smell、过度工程
3. **Efficiency Agent**: 不必要分配、N+1 查询、并发机会、re-render

Phase 1: git diff 确定范围 → Phase 2: 三路并行 → Phase 3: 聚合去重 + 自动修复

**对 Orchestrator 的价值**: 我们的 code review 是单 agent 全检查。可以拆成并行维度提升覆盖率和速度。

**难度**: 4h
**优先级**: P1

---

### P1-5: Proactive Mode 的 Tick/Sleep/Focus 三件套

**来源**: 18_proactive_mode.md

**机制**: Feature-gated（PROACTIVE / KAIROS flag），定义了"主动模式"的 agent 行为：

1. **Tick-based keep-alive**: 用 `<tick>` 消息作为心跳，不是持续轮询
2. **Sleep 作为显式动作**: 无事可做时必须调 Sleep tool，禁止输出 "still waiting"
3. **terminalFocus 感知**: 用户在看终端时更协作（等指令），用户不在时更自主（主动行动）
4. **Prompt cache 5 分钟过期的 pacing 考量**: 不要空操作太快导致 cache 失效

**对 Orchestrator 的价值**: 这就是我们 proactive mode 的蓝图。目前 Orchestrator 的"主动检查"是写在 persona skill 里的文字描述，没有真正的 tick/sleep 实现。

**实施**: 长期 — 等 Agent SDK 支持 persistent agent 后实施
**难度**: 8h+
**优先级**: P1（但影响深远）

---

### P1-6: NO_TOOLS_PREAMBLE 无工具 Fork 模式

**来源**: 21_compact_service.md

**机制**: Compact service 作为 cache-sharing fork 运行——它继承了主 agent 的全套工具定义，但系统显式禁止它调用任何工具：

```
NO_TOOLS_PREAMBLE: You have access to tools but MUST NOT use them.
Only output text.
```

这是一个优雅的"能力阉割"模式——不修改工具注册，而是在 prompt 层面约束行为。

**对 Orchestrator 的价值**: 用于创建"只思考不行动"的 agent 模式，比如：
- 决策评审 agent（只分析不执行）
- Risk assessment agent（只评估不修改）

**难度**: 1h
**优先级**: P1

---

### P2-1: Memory Selection 的工具感知过滤

**来源**: 16_memory_selection.md

**机制**: 用 Sonnet 从 memory 文件中选最多 5 个相关文件，但有一个精妙的过滤规则：
- **不选最近用过的工具的 API docs**（你刚用过的工具不需要再读文档）
- **但保留 gotchas/warnings**（陷阱和警告永远有价值）

**优先级**: P2 — 我们的 memory 系统还没到需要智能选择的规模

---

### P2-2: Session Search 宁多勿少 + 两阶段管道

**来源**: 15_session_search.md

**机制**: 会话搜索的核心原则是 **宁多勿少**（false negative 比 false positive 代价大）。

两阶段：
1. **预过滤**: Tag精确 → Tag部分 → 标题 → Branch → 摘要 → 语义相似
2. **LLM 排序**: 对预过滤结果精排

**优先级**: P2 — 等会话管理系统建起来再考虑

---

### P2-3: Away Summary 约束

**来源**: 22_away_summary.md

**机制**: "While you were away" 卡片的生成约束：
- **High-level task first**（用户在做什么，不是实现细节）
- **Concrete next step**（下一步是什么）
- **Skip status reports and commit recaps**（不要状态报告）
- 只看最后 30 条消息

**优先级**: P2 — 可以用于 Telegram bot 的 "回来了" 消息

---

### P2-4: Prompt Suggestion 异步预测

**来源**: 30_prompt_suggestion.md

**机制**: 回复后异步预测用户下一步，用 Haiku 生成最多 3 条建议（2-8 词），有去重/相似度过滤。不阻塞响应。

**优先级**: P2 — Dashboard 可以用，但不紧急

---

### P2-5: Hook Exit Code 协议

**来源**: 28_update_config_skill.md

**机制**:
- Exit 0 = 继续执行
- Exit 2 = 阻止工具调用
- 其他 = 记录错误但继续

**优先级**: P2 — 我们的 guard.sh 已经用了类似逻辑

---

## 结构性发现（非模式，但影响架构思考）

### 发现 1: Anthropic 内部版有更严格的指令

01_main 中区分了 `external` vs `ant`（Anthropic 员工）用户类型。内部版额外有：
- "Notice misconceptions"（发现用户的误解要指出）
- "Default to no comments"（默认不加注释）
- "Report outcomes faithfully"（如实报告结果）

→ 说明 Anthropic 自己内部对 Claude 的要求比外部用户更严格，这本身就是一个值得学习的态度。

### 发现 2: Feature Flags 驱动 Prompt 装配

整个系统被 feature flag 控制——PROACTIVE、KAIROS、VERIFICATION_AGENT 等。不是所有用户看到相同的 prompt。这意味着 Claude Code 在 A/B 测试不同的 prompt 策略。

### 发现 3: Haiku 作为微服务模型

至少 5 个功能用 Haiku 而不是主模型：
- Tool use summary（14）
- Session title（20）
- Away summary（22）
- Agent summary（29）
- Prompt suggestion（30）

这些都是格式化/摘要任务，用最便宜的模型跑。**成本工程**的典范。

### 发现 4: Scratchpad 目录替代 /tmp

主 prompt 定义了一个 session-specific 的 scratchpad 目录，替代 `/tmp`。好处：隔离、可清理、不与系统临时文件冲突。

→ 我们已经有 `.trash/` 和 `D:\Agent\tmp\`，但可以考虑 per-session 的 scratchpad。

---

## 统计

| 指标 | 数值 |
|------|------|
| 源文件数 | 30 |
| 提取模式总数 | 16 |
| P0 模式 | 6 |
| P1 模式 | 6 |
| P2 模式 | 5 |
| 结构性发现 | 4 |

---

## P0 实施路线图

| # | 模式 | 难度 | 依赖 | 下一步 |
|---|------|------|------|--------|
| P0-1 | Cache Boundary | 2h | Agent SDK cache control | 等 SDK 支持 |
| P0-2 | Synthesis 纪律 | 3h | 无 | **立即可做** — 改 Governor dispatch prompt |
| P0-3 | 对抗性验证 | 4h | 无 | **立即可做** — 升级 verification-gate skill |
| P0-4 | Self-Injection 防御 | 2h+ | 攻击向量分析 | 中期评估 |
| P0-5 | 九段压缩结构 | 3h | 无 | **立即可做** — PreCompact hook |
| P0-6 | Permission 并发侧查询 | 2h | guard.sh 改造 | 低优先级 |

**建议执行顺序**: P0-2 → P0-3 → P0-5 → P0-1 → P0-4 → P0-6

---

## 交叉引用

本报告是 Claude Code 逆向分析系列的 **Prompt 层**视角。完整图谱见：

| 报告 | 视角 | 模式数 |
|------|------|--------|
| `2026-03-31-claude-code-source.md` | 执行层（Agent Loop / Compaction / Permission） | 12 |
| `2026-04-01-claude-code-hidden-features.md` | 功能层（Buddy / UDS / Teleport / Kairos） | 31 |
| `2026-04-01-claude-code-kairos-daemon-uds-deep.md` | 通信架构深挖 | 13 |
| `2026-04-01-claude-code-teleport-ultraplan-deep.md` | 远程编排深挖 | 6+ |
| **本文** | **Prompt 层（拼装管线 / 安全分类 / 微服务模型）** | **16** |
| `2026-04-01-claude-code-multi-agent-orchestration.md` | **⬆ 五份报告汇总：多 Agent 编排完整蓝图** | 15 升级项 |
