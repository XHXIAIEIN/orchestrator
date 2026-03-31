# proactive-agent @halthelobster — 深挖偷师报告

> Round 23 — 专项深挖 proactive-agent v3.1.0
> 日期：2026-03-31
> 来源：https://github.com/openclaw/skills/tree/main/skills/halthelobster/proactive-agent
> 上次覆盖：Round 14（当时多项目并行，只提取了 WAL + Working Buffer + ADL/VFM 三个大块）

---

## 概述

proactive-agent 是 Hal Stack 的核心技能，定位「把 task-follower 变成 proactive partner」。v3.1.0 的真正价值不在单个协议，而在**协议之间的联动闭环**：WAL 捕获 → Working Buffer 兜底 → Compaction Recovery 恢复 → Heartbeat 自检 → Reverse Prompting 主动出击 → Growth Loops 持续进化。这个链条 Orchestrator 目前只实现了前半段。

---

## 核心机制详解

### WAL Protocol 实现细节

**触发规则**：扫描每条 human input，命中 6 类信号之一就触发：
1. ✏️ 纠正 — "It's X, not Y" / "Actually..."
2. 📍 专有名词 — 人名/地名/公司/产品
3. 🎨 偏好 — "I like/don't like"
4. 📋 决策 — "Let's do X" / "Go with Y"
5. 📝 草稿变更 — 编辑中的内容
6. 🔢 精确值 — 数字/日期/ID/URL

**执行顺序**：STOP → WRITE(SESSION-STATE.md) → THEN RESPOND

**关键设计**：触发条件是 input 内容，不是 agent 自己的记忆判断。这消除了「觉得不需要记」的认知偏差。

**写入目标**：`SESSION-STATE.md`（单文件，active working memory）

**Orchestrator 现状**：Round 14 P0 已规划 `SOUL/private/session-state.md`，但 executor 入口的扫描钩子尚未落地。当前只有 run_log 事后记录。

### Working Buffer 实现细节

**触发**：context 达 60%（通过 `session_status` 检查）
**格式**：
```markdown
# Working Buffer (Danger Zone Log)
**Status:** ACTIVE
**Started:** [timestamp]

---
## [timestamp] Human
[原始消息]

## [timestamp] Agent (summary)
[1-2 句摘要 + 关键细节]
```

**生命周期**：
1. 60% 时 CLEAR 旧 buffer，重新开始
2. 每条消息追加（human + agent summary）
3. Compaction 后从 buffer 恢复
4. 下次 60% 时才清空

**Orchestrator 现状**：Round 14 P1 #6 已设计但未实施。Orchestrator 的 sub-agent 模型天然规避了长 context 问题（每次 dispatch 是新 session），但主进程（Claude Code 本身）没有 buffer 机制。

### Compaction Recovery 协议

**自动触发条件**：
- Session 以 `<summary>` tag 开始
- 消息含 "truncated" / "context limits"
- 用户说 "where were we?" / "continue"
- Agent 该知道某事但不知道

**恢复链**：working-buffer.md → SESSION-STATE.md → today's daily notes → yesterday's notes → 全量语义搜索

**关键原则**：「不要问 what were we discussing，buffer 里有答案」

**Orchestrator 现状**：完全缺失。sub-agent 没有 compaction 问题，但主进程有。

### Autonomous vs Prompted Crons

**两种架构**：

| 类型 | 机制 | 适用场景 |
|------|------|----------|
| `systemEvent` | 发 prompt 给主 session | 需要交互、需要 agent 注意力 |
| `isolated agentTurn` | 独立子 agent 自主执行 | 后台维护、检查、清理 |

**失败模式**：把该自主执行的任务配成 `systemEvent`，结果主 session 忙别的事，prompt 无人响应。

**Orchestrator 现状**：`agent_cron.py` 已实现部门级 cron 调度（基于 blueprint.yaml），但所有 cron job 都走 Governor → Executor 的完整链路（相当于 `isolated agentTurn`）。缺少 `systemEvent` 这个维度 — 有些事确实应该提醒主进程而不是自主做。

---

## 可偷模式（与 Round 14 去重后的增量）

### P0 — 立刻能用

#### 模式 A：Compaction Recovery Protocol
**Round 14 未覆盖**。proactive-agent 的恢复链（buffer → session-state → daily → search）是一个确定性流程，不依赖 LLM 判断。
**为什么值得偷**：主进程 Claude Code 会遇到 context compaction。当前没有标准化恢复流程，全靠 LLM 自由发挥。
**适配方案**：在 `.claude/boot.md` 注入 Compaction Recovery 指令段。主进程检测到 `<summary>` 或用户说「继续」时，按固定链路读取 `SOUL/private/session-state.md` → 今日 daily log → 语义搜索。不需要代码改动，纯 prompt 工程。

#### 模式 B：Cron 双模式（systemEvent vs agentTurn）
**Round 14 未覆盖**。当前 `agent_cron.py` 只有 isolated 模式。
**为什么值得偷**：有些定时任务的正确做法是「提醒主进程」而非「自主执行」。例如：session-state 过期检测应该提醒用户，而不是自动重写。
**适配方案**：在 `blueprint.yaml` 的 `cron_jobs` 字段加 `mode: event | agent`。`event` 模式创建一个 `attention_debt` 记录而非启动 agent。半天工作量。

### P1 — 值得花时间

#### 模式 C：Reverse Prompting + Proactive Tracker
**Round 14 遗漏**。不是「等用户问」而是主动问「基于我了解的你，有什么我能帮你的？」
**为什么值得偷**：Orchestrator 的 Telegram bot 已有对话能力，但只会回复不会主动发起。Reverse Prompting 是从 reactive 到 proactive 的跨越。
**适配方案**：
1. 新建 `notes/proactive-tracker.md`，记录观察到的重复模式
2. 在 TG bot 加 weekly cron，发送「本周观察 + 建议」
3. 触发条件：同一类请求出现 ≥3 次
**工作量**：1 天

#### 模式 D：Growth Loops（三环）
**Round 14 遗漏**。三个独立循环：
- **Curiosity Loop**：每次对话问 1-2 个了解用户的问题 → 写入 USER.md
- **Pattern Recognition Loop**：追踪重复请求，≥3 次提议自动化
- **Outcome Tracking Loop**：记录重大决策，7 天后跟进结果

**为什么值得偷**：Pattern Recognition 直接对接 Pattern-Key 自动晋升（Round 14 P0 #3）。Outcome Tracking 填补了「决策后不复盘」的结构性盲区。
**适配方案**：
- Curiosity → 已有 `user_profile` 表 + profile_analyst，但缺对话时主动问
- Pattern → `.learnings/` Pattern-Key 已有基础设施（Round 14），加 threshold 触发即可
- Outcome → 在 `experiences.jsonl` 加 `type: decision`，scheduler 加 7 天回访 job
**工作量**：2 天

#### 模式 E：VBR（Verify Before Reporting）协议
**Round 14 遗漏**。`"code exists" ≠ "feature works"`。Agent 说「完成」之前必须实际测试。
**为什么值得偷**：Orchestrator 的 Karpathy Round 18 已有类似精神（Goal-Driven Execution），但缺 enforcement。proactive-agent 的具体做法是：检测到 agent 即将输出 "done/complete/finished" → STOP → 实际测试 → 才能报告。
**适配方案**：已有 `superpowers:verification-before-completion` skill，但它是被动的（需要 agent 记得调用）。可以在 Stop hook 中加检测：agent output 含 "完成/done" 但没有测试证据 → 注入提醒。
**工作量**：半天

### P2 — 长远参考

#### 模式 F：Unified Search Protocol（四级降级搜索）
搜索链：semantic search → session transcripts → meeting notes → grep fallback
**Orchestrator 现状**：vector_db 已有语义搜索，EventsDB 有结构化查询，但没有标准化的「搜完一个搜下一个」降级链。
**适配**：写成 ContextEngine 的一个方法，sub-agent 可调用。与 context-parity 设计对齐。

#### 模式 G：Skill Installation Vetting（26% 漏洞率警告）
proactive-agent 声称「~26% 的社区 skill 含漏洞」，要求安装前 review SKILL.md。
**Orchestrator 现状**：Round 14 P2 #16 已从 skill-vetter 偷了 14 项红旗检查。这里是补充「默认不信任」的心理模型，属于意识层面，不需要代码。

---

## WAL 实现细节对比

| 维度 | proactive-agent | Orchestrator 现状 | 差距 |
|------|----------------|-------------------|------|
| 触发时机 | 每条 input 的 BEFORE 阶段 | run_log 是 AFTER | **事前 vs 事后** |
| 写入目标 | SESSION-STATE.md（单文件） | SOUL/private/session-state.md（已规划） | 设计已有，未实施 |
| 扫描方式 | 6 类信号 pattern match | 无 | **完全缺失** |
| 恢复路径 | buffer → state → daily → search | 无标准化链 | **完全缺失** |
| 适用层 | 主进程（长对话） | Sub-agent（短任务） | 不同层，互补 |

---

## 与 Orchestrator 现有能力的差异总结

**我们有而他没有的**：
- 完整的部门体系（六部） — proactive-agent 是单 agent 架构
- 链式哈希审计日志 — 他只有文本日志
- 多通道审批（Claw/TG/WX）— 他只有单用户确认
- Agent SDK sub-agent 调度 — 他的 cron 是 prompt 级

**他有而我们没有的**：
- **Compaction Recovery 标准化流程** — 我们主进程靠运气恢复
- **Cron 双模式（event vs agent）** — 我们只有 agent 模式
- **Reverse Prompting** — 我们只会被动回应
- **Growth Loops** — 我们记了 experiences 但不复盘
- **VBR enforcement** — 我们有 skill 但没有 hook 强制

---

## 落地建议

| 优先级 | 模式 | 工作量 | 依赖 |
|--------|------|--------|------|
| P0 | Compaction Recovery Protocol | 半天 | boot.md 修改 |
| P0 | Cron 双模式 (event/agent) | 半天 | agent_cron.py + blueprint.yaml |
| P1 | Reverse Prompting + Tracker | 1 天 | TG bot cron |
| P1 | Growth Loops（3 环） | 2 天 | .learnings + experiences |
| P1 | VBR Hook Enforcement | 半天 | Stop hook |
| P2 | Unified Search 降级链 | 1 天 | ContextEngine |
| P2 | Skill Vetting 意识注入 | 0 | boot.md |

---

## 源码引用

| 文件 | 内容 |
|------|------|
| [SKILL.md](https://github.com/openclaw/skills/blob/main/skills/halthelobster/proactive-agent/SKILL.md) | 完整技能定义（v3.1.0） |
| [ClawHub 页面](https://clawhub.ai/halthelobster/proactive-agent) | 发布页 |

---

*Round 23 深挖完成。与 Round 14 的 16 模式去重后，净增 7 个可偷模式（2 P0 + 3 P1 + 2 P2）。*
