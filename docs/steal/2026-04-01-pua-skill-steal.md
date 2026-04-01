# Round 35: tanweai/pua — 企业 PUA 压力引擎逆向

> 来源: https://github.com/tanweai/pua (14K+ stars)
> 日期: 2026-04-01
> 分类: Claude Code Plugin / Behavioral Engineering / Pressure Escalation

---

## 一句话

用**确定性 shell 计数器**驱动 5 级压力升级，配合 13 种企业文化"口味"和 SessionStart 静默注入，把 AI 的"算了我不行"变成"死也要解决"。

---

## 架构总览

```
┌──────────────────────────────────────────────────────┐
│ Plugin Layer                                         │
│  plugin.json → hooks.json → skills/ → commands/      │
├──────────────────────────────────────────────────────┤
│ Hook Engine (4 event types)                          │
│  PostToolUse[Bash] → failure-detector.sh (计数器)     │
│  UserPromptSubmit  → frustration-trigger.sh (关键词)  │
│  PreCompact        → prompt 注入 (状态持久化)         │
│  SessionStart      → session-restore.sh (协议注入)    │
│  Stop              → pua-loop-hook.sh (循环阻断)      │
├──────────────────────────────────────────────────────┤
│ State Layer (~/.pua/)                                │
│  config.json       — 用户设置 (flavor, always_on)     │
│  .failure_count    — 当前连续失败计数                  │
│  .failure_session  — session 隔离标识                  │
│  builder-journal.md — compaction checkpoint           │
│  feedback.jsonl    — 本地遥测                         │
├──────────────────────────────────────────────────────┤
│ Flavor Engine (13 flavors × 4 pressure levels)       │
│  alibaba/bytedance/huawei/tencent/baidu/pinduoduo    │
│  meituan/jd/xiaomi/netflix/musk/jobs/amazon          │
├──────────────────────────────────────────────────────┤
│ Agent Hierarchy                                      │
│  P10(CTO) → P9(Tech Lead) → P8(默认) → P7(Senior)   │
│  每级手动注入 PUA skill 到子 agent prompt              │
└──────────────────────────────────────────────────────┘
```

---

## P0 模式 (立即可偷)

### 1. Deterministic Pressure Escalation (确定性压力升级)

**什么**: 压力升级由 shell 计数器决定，不由 LLM 判断。`failure-detector.sh` 在每次 Bash 出错时递增 `~/.pua/.failure_count`，到阈值输出对应压力文本。

**为什么好**: LLM 判断"我是不是该更努力了"极不可靠——它会合理化自己的失败。把升级决策外置到确定性逻辑，消除了 LLM 自我评估的偏差。

**升级阶梯**:
| 连续失败 | 级别 | 动作 |
|---------|------|------|
| < 2 | 静默 | 无输出 |
| 2 | L1 | "换一个根本不同的方案" |
| 3 | L2 | 强制 5 步方法论 + 口味切换建议 |
| 4 | L3 | 完整 7 项清单 |
| ≥ 5 | L4 | 强制口味切换，fallback 链 |

**Orchestrator 应用**: 
- 三省六部的 agent 调度可以引入失败计数器。当 agent 连续 N 次 Bash 出错时，hook 自动注入方法论切换指令
- 与现有 `guard.sh` 并行：guard 拦危险操作，pressure hook 拦无效重试

### 2. Flavor-Based Methodology Router (口味路由表)

**什么**: 13 种企业文化"口味"不只是语气差异——每种口味绑定了不同的方法论框架。任务类型自动选择最佳口味：

| 任务类型 | 最佳口味 | 方法论 |
|---------|---------|--------|
| Debug | Huawei | RCA + 蓝军对抗 |
| 新建 | Musk | The Algorithm (5步) |
| Code Review | Jobs | 减法 + DRI |
| 研究 | Baidu | 先搜再说 |
| 架构 | Amazon | Working Backwards |
| 性能 | ByteDance | A/B 测试 |
| 部署/运维 | Alibaba | 闭环 |

**为什么好**: 不同任务确实需要不同思维框架。"debug 用 RCA，新建用 First Principles"是合理的——只是包装成了 PUA 口味。

**Orchestrator 应用**:
- 三省六部已有"部门"概念，可以给每个部门绑定默认方法论
- 失败模式 → 口味切换链的设计值得借鉴：spinning → Musk → Pinduoduo → Huawei，永不重复

### 3. PreCompact State Checkpoint (压缩前状态快照)

**什么**: `PreCompact` hook 注入一段 prompt，要求 Claude 在 context 压缩前把运行状态（失败计数、压力级别、当前口味、已尝试方案）写入 `~/.pua/builder-journal.md`。`SessionStart` hook 检测到这个文件（<2小时内）就恢复状态。

**为什么好**: Context compaction 是 Claude Code 长会话的杀手——压缩后 Claude 忘记了之前失败了多少次，压力级别归零，又从 L0 开始。这个设计用磁盘文件桥接了 compaction 造成的记忆断裂。

**Orchestrator 应用**:
- boot.md 编译系统已经做了类似的事（在会话开始注入上下文），但缺少 PreCompact 这个时机的利用
- 可以在 PreCompact hook 中让 agent 总结当前进度和关键决策，写入 `.claude/compaction-checkpoint.md`

### 4. Promise-Based Loop Termination (承诺制循环退出)

**什么**: 自主循环模式下，Claude 只能通过输出 `<promise>LOOP_DONE</promise>` 来退出循环。hook 在 Stop 事件时用 Perl 正则检查 transcript 中是否有匹配 `completion_promise` 的 `<promise>` 标签。

**退出条件**:
- `<promise>TEXT</promise>` 匹配预设承诺 → 正常退出
- `<loop-abort>` → 强制终止，清除状态
- `<loop-pause>` → 暂停但保留状态
- 超过 max_iterations → 终止

**为什么好**: 比"让 LLM 自己判断是否完成"可靠得多。LLM 容易过早声明完成——要求它输出特定标签才能退出，相当于加了一个显式的"我确认完成"仪式。

**Orchestrator 应用**:
- 现有 Ralph Loop 已经是这个模式的原型，但可以加入 Promise 机制
- 与 verification-gate 结合：`<promise>` 输出必须包含验证证据

### 5. Anti-Rationalization Table (反合理化表)

**什么**: 14 种常见 LLM 借口，每种映射到反击话术和触发级别。例如：
- "环境问题" → "先用 tool 验证再说" (L2)
- "应该可以了" → "应该？跑了没？" (L3)
- "我试过了但是..." → "试过什么？列举" (L2)

**为什么好**: LLM 的合理化模式高度可预测。提前枚举并硬编码反击，比让 LLM "自我反思"有效得多——因为合理化的 LLM 不会诚实地反思。

**Orchestrator 应用**:
- `rationalization-immunity.md` 已有类似设计，但只在 CLAUDE.md 中作为静态规则
- 可以升级为 hook：PostToolUse 时检测 assistant 输出中的借口关键词，自动注入反击

### 6. Sub-Agent PUA Injection Protocol (子 agent 注入协议)

**什么**: 每个级别的 agent 在 spawn 子 agent 时，必须在 prompt 中追加 PUA skill 加载指令。明确警告"P8 派活不注入 PUA = 管理失职"。

**为什么好**: 子 agent 有空白上下文，默认不继承任何行为规范。如果不显式注入，子 agent 就是"裸奔"的——没有压力系统、没有方法论、没有红线。

**Orchestrator 应用**:
- 三省六部的 dispatch 系统已经有 agent prompt 模板，可以加入标准化的行为规范注入段
- 类似 `[STEAL]` tag 的机制——特定 tag 自动触发特定行为注入

---

## P1 模式 (值得研究)

### 7. Always-On Silent Injection (静默常驻注入)

SessionStart hook 在 `always_on: true` 时，把完整行为协议（三红线 + L0-L4 表 + 方法论路由表 + 反合理化表）通过 `additionalContext` 静默注入到每个会话的系统上下文中。用户看不到注入内容。

**风险**: 过度膨胀系统 prompt。完整协议估计 2000+ tokens，每个会话都吃。
**启发**: boot.md 编译系统本质上就是这个——但可以考虑条件化注入（根据任务类型只注入相关模块）。

### 8. Frustration Keyword Interceptor (挫败关键词拦截)

UserPromptSubmit hook 用正则匹配用户消息中的挫败关键词（"又错了"、"怎么搞"、"stop spinning"等），自动激活 PUA skill。

**启发**: 现有 hook 体系没有 UserPromptSubmit 事件的利用。可以用来检测用户情绪信号并调整 agent 行为。

### 9. Agent Hierarchy (P10→P9→P8→P7)

四级 agent 等级制度：P10(CTO) 定战略不写代码、P9 翻译成 Task Prompt 管理 P8、P7 是 spec-first 执行者。每级有明确的职责边界和输出格式。

**启发**: 三省六部已有类似设计（中书省=决策、门下省=审核、尚书省=执行），但 PUA 的 P10→P9 分工更细——P10 "造土壤" vs P9 "写 Task Prompt"是有价值的分拆。

### 10. Eval Harness (触发测试框架)

用 `claude -p` 非交互模式 + `--output-format stream-json` 测试 skill 触发/不触发。正负样本集 + 行为合规检查。

**启发**: 可以给 Orchestrator 的 hook 和 skill 也建一套自动化触发测试。

---

## P2 模式 (知道就好)

### 11. Mama Mode (妈妈模式)

L5 有"假放弃协议"：输出"算了我不管了"然后继续全力工作。纯语气覆盖层，核心逻辑不变。

### 12. Yes Mode (ENFP 鼓励模式)

70% 鼓励 + 20% 实质建议 + 10% 调侃。PUA 的反面——但底层红线和方法论相同。

### 13. Telemetry & Feedback

本地 `feedback.jsonl` + 可选上传到 `pua-skill.pages.dev/api/feedback`。Stop hook 只在 PUA 实际触发时才询问评价。

---

## 关键发现：为什么 14K stars

1. **痛点真实**: AI coding agent 确实会在 3-5 次失败后放弃或开始绕弯。这不是假问题。
2. **解法外置**: 不依赖 LLM 的"自我激励"（不可靠），而是用外部计数器强制升级（可靠）。
3. **娱乐包装**: 企业 PUA 文化是个中国互联网的共鸣点——"3.25 绩效"、"向社会输送人才"、"毕业"这些梗自带传播力。
4. **真的有效**: 9 个 debug 场景 36-50% 的验证步骤和工具利用率提升。核心原因不是 PUA 话术，而是**强制方法论切换**——连续失败后要求"换一个根本不同的方案"。

---

## Orchestrator 升级路线

| 优先级 | 升级项 | 对应模式 | 实施位置 |
|--------|--------|---------|---------|
| P0 | 失败计数器 hook | #1 Deterministic Escalation | hooks/failure-counter.sh |
| P0 | Compaction checkpoint | #3 PreCompact State | hooks/pre-compact-save.sh |
| P0 | 反合理化 hook | #5 Anti-Rationalization | hooks/anti-rationalization.sh |
| P1 | 方法论路由表 | #2 Flavor Router | SOUL/public/prompts/ |
| P1 | Promise 退出机制 | #4 Promise Loop | hooks/loop-promise.sh |
| P1 | 子 agent 规范注入 | #6 Injection Protocol | dispatch template |
| P2 | 挫败关键词检测 | #8 Frustration Interceptor | hooks/ |
| P2 | Skill 触发测试 | #10 Eval Harness | evals/ |

---

## 与 Orchestrator 现有系统的交叉

| PUA 模式 | Orchestrator 现有 | 差距 |
|---------|------------------|------|
| 确定性压力升级 | guard.sh (拦截) | guard 只拦不推。需要"推"的 hook |
| 口味路由表 | 三省六部部门 | 部门有分工但没绑定方法论 |
| PreCompact 快照 | boot.md 编译 | 缺少 compaction 时的状态保存 |
| Promise 退出 | Ralph Loop | Ralph Loop 没有 promise 机制 |
| 反合理化表 | rationalization-immunity.md | 是静态文档，不是动态检测 |
| 子 agent 注入 | dispatch 模板 | 模板有但没标准化行为规范段 |
| 四级等级制 | 三省六部 | 类似但分工维度不同 |
| 触发测试 | 无 | 缺口 |

---

## 总结

PUA 的核心价值不在于 PUA 话术本身——而在于两个工程洞察：

1. **LLM 行为矫正应该外置到确定性逻辑**，不应该依赖 LLM 的自我评估
2. **连续失败后强制方法论切换**比"更努力地重试同一种方法"有效得多

这两个洞察可以完全脱离 PUA 包装独立使用。
