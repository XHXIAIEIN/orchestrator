# R76 — Karpathy Guidelines Steal Report

**Source**: https://github.com/forrestchang/andrej-karpathy-skills | **Stars**: ~2.5k | **License**: MIT
**Extended**: [rohitg00/pro-workflow gist](https://gist.github.com/rohitg00/b0d629229cbb0f28d05c16662543e633) | [Original tweet](https://x.com/karpathy/status/2015883857489522876)
**Date**: 2026-04-15 | **Category**: Skill-System

## TL;DR

Karpathy 观察到 LLM 编码的四个核心缺陷（假设静默、过度工程、附带修改、目标模糊），forrestchang 把它提炼成四条行为约束做成 Claude Code plugin。rohitg00 的 pro-workflow 在此基础上加了自纠正闭环、hook 系统、和记忆持久化。值得偷的不是原则本身（我们已覆盖），而是**包装哲学**和**缺失的前置简洁门控**。

## Architecture Overview

```
forrestchang/andrej-karpathy-skills
├── Layer 0: Distribution — Claude Code plugin (.claude-plugin/)
│   └── marketplace.json → one-command install via /plugin
├── Layer 1: Entry — CLAUDE.md (66 lines, merge-friendly)
│   └── 4 principles, each ~10 lines, no implementation detail
├── Layer 2: Skill — skills/karpathy-guidelines/SKILL.md
│   └── Same 4 principles, wrapped in skill frontmatter
└── Layer 3: Teaching — EXAMPLES.md (523 lines)
    └── Before/after code pairs for every principle

rohitg00/pro-workflow (extended reading)
├── Self-Correction Loop: [LEARN] tags → SQLite persistence
├── Hook System: 24 events, nudge-first enforcement
├── Three-Layer Orchestration: Commands → Agents → Skills
├── Split Memory: CLAUDE.md / AGENTS.md / SOUL.md / LEARNED.md
└── Compounding Engine: corrections → rules → hooks → better behavior → tighter loop
```

## Six-Dimensional Scan

### Security / Governance
**Status**: Minimal — no permission model, no risk gates, no audit trail.

Karpathy 的原文明确指出 "if you have any code you actually care about I would watch them like a hawk"，但 forrestchang 的实现没有把这个观察转化为任何机械约束。rohitg00 做得更好：LLM gates 在 commit 前验证 secrets/dangerous patterns，PermissionDenied 事件分析 denial patterns。

**我们的状态**: Guardian assessment (0-100 reversibility scoring)、Gate Functions (5 个硬门控)、dispatch-gate hook — 覆盖远超两者。

### Memory / Learning
**Status**: N/A for forrestchang (stateless plugin) | rohitg00 有完整闭环

rohitg00 的 Self-Correction Loop 是核心创新：
- Agent 主动识别错误 → 提出 `[LEARN] [Category]: rule` 格式的规则
- 人工审批后写入 SQLite（从 markdown 升级，30 条后变得不可搜索）
- SessionStart hook 加载累积学习
- **失败经验**: v1 自动捕获无审批 → 一周内产生矛盾规则

**我们的状态**: `.remember/` 目录 + evidence tier system (verbatim > artifact > impression)。有持久化，有冲突解决规则（同 tier 保留两者+时间戳），但缺少 rohitg00 的 `[LEARN]` 格式化提取和 SQLite 后端的全文搜索能力。

### Execution / Orchestration
**Status**: 无编排 — 单一 skill 直接注入 context

forrestchang 的设计哲学是"不编排"：一个 66 行 CLAUDE.md 注入系统 prompt，没有路由、没有阶段、没有条件触发。这是**有意的极简主义** — 降低采用摩擦到零。

rohitg00 有三层编排 (Commands → Agents → Skills) 和 parallel worktrees，但这已经是另一个量级的系统。

**我们的状态**: collaboration_modes (plan/execute/review)、cognitive_modes (4种)、skill_routing 决策树 — 覆盖充分。

### Context / Budget
**Status**: 极度节俭 — CLAUDE.md 66 行 (~100 tokens)，SKILL.md 68 行

这是值得注意的设计选择：4 条原则压缩到 100 token 以内，作为"always-on"指令注入不构成 context 负担。我们的 CLAUDE.md + boot.md + prompts/ 体系更强大但 token 成本也高得多。

rohitg00 提出的 Write/Select/Compress/Isolate 框架（来自 Lance Martin）是有价值的参考：
- Write: 生成研究/规划笔记
- Select: 每步只加载最小需要的 context
- Compress: 将文件摘要为接口
- Isolate: 用 subagent 隔离高量工作

**我们的状态**: 有 context engineering 意识（collaboration_modes 的 research budget），但没有形式化的 Write/Select/Compress/Isolate 四步框架。

### Failure / Recovery
**Status**: N/A for forrestchang | rohitg00 有 hook-based 检测

rohitg00 的 PostToolUse hook 扫描 console.log/secrets/debugger 残留，Stop hook 基于最近操作给出 context-aware 提醒。失败经验：过度阻断导致用户禁用 → 改为 nudge-first + 仅破坏性操作 blocking。

**我们的状态**: systematic-debugging skill (5阶段)、doom loop detection、3-attempt escalation — 远超两者。

### Quality / Review
**Status**: forrestchang 有隐式质量标准 | rohitg00 有 LLM gates

forrestchang 的质量检测方法很聪明 — 不是在生成后检查，而是用四个原则在生成时约束：
- "Would a senior engineer say this is overcomplicated?" — 内置自检问题
- "Every changed line should trace directly to the user's request" — 内置 diff 审计标准
- 但这些是**提示级**约束，不是机械执行

rohitg00 增加了 LLM gates（独立模型验证 commits），但细节不足。

**我们的状态**: verification-gate (5步铁律)、adversarial-dev (NEGOTIATE+EVALUATE)、rationalization-immunity 查找表 — 质量门控体系最完整。

## Path Dependency Speed-Assess

### Locking Decisions
- forrestchang 选择了"单文件 CLAUDE.md"路径 → 极简但不可扩展。四条原则是终态，加第五条就破坏了"Karpathy 四原则"的品牌。
- rohitg00 选择了"SQLite 存学习记忆" → 解决了 markdown 30 条后不可搜索的问题，但引入了 DB 依赖。

### Missed Forks
- forrestchang 可以在 EXAMPLES.md 上做更多：当前是静态文档，如果做成交互式 eval（给 LLM 一个场景，检查它是否遵循原则），就变成了质量测试套件。
- rohitg00 可以把 `[LEARN]` 闭环做成 Claude Code hook 而非手动流程，实现真正的 zero-friction 学习。

### Self-Reinforcement
- forrestchang: 社区 PR + marketplace 分发 → 品牌效应锁定（"Karpathy-inspired" 是强标签）
- rohitg00: 学习闭环本身就是自增强 — 用得越多规则越好，规则越好用得越多

### Lesson for Us
学 forrestchang 的**包装极简主义**（100 token 内传达核心约束），学 rohitg00 的**闭环学习机制**（但要吸取 v1 auto-capture 的教训）。

## Steal Sheet

### P0 — Must Steal (2 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| Simplicity Pre-Gate | 在功能实现前强制回答 "Would a senior engineer say this is overcomplicated?" — 不是 tiebreaker，是 blocker | 简洁性仅作为 Agent Self-Modification 的 tiebreaker 和 methodology_router 的 code review 策略。没有前置门控。 | 在 `plan_template.md` Phase Gate 1 (Spec→Plan) 增加第 4 项检查："Simplicity pre-check: describe the simplest possible implementation. If your plan exceeds this by >2x LOC, justify why." | ~1h |
| Declarative > Imperative Framing | Karpathy 原文: "Don't tell it what to do, give it success criteria and watch it go. Change your approach from imperative to declarative to get the agents looping longer and gain leverage." — 将任务表述从祈使句转为声明式验收标准 | Goal-Driven Execution 已存在但仅在 planning 和 verification 阶段。缺少在 task intake 阶段强制将用户祈使指令转译为声明式标准的机制。adversarial-dev 的 NEGOTIATE 做了这件事，但仅限复杂功能。 | 在 `clarification.md` 增加一条转译规则：当 task 描述为祈使句（"add X", "fix Y", "change Z"）时，自动追加声明式验收标准。模板: `"[imperative] → Done when: [falsifiable condition]"` | ~1h |

**P0 Comparison Matrix:**

| Capability | Karpathy/forrestchang | Our impl | Gap | Action |
|-----------|----------------------|---------|-----|--------|
| Simplicity as generative constraint | "If 200 lines could be 50, rewrite it" — proactive, at creation time | Simplicity as tiebreaker (Self-Modification gate) + Subtraction methodology (review only) | Medium — we enforce simplicity reactively, not proactively | Steal: add pre-gate |
| Imperative→Declarative conversion | "Don't tell it what to do, give it success criteria" — explicit workflow shift | Goal-Driven Execution exists; adversarial-dev has NEGOTIATE; but no universal conversion step | Small — capability exists but isn't triggered at task intake | Steal: universal trigger |

**P0 Triple Validation:**

**Simplicity Pre-Gate:**
- Cross-domain reproduction: ✅ Appears in Karpathy, forrestchang, rohitg00, and Google's code review guidelines ("Could this be simpler?")
- Generative power: ✅ Given any new feature request, the gate predicts: "write simplest version first, then justify additions" — applies to novel scenarios
- Exclusivity: ✅ Not generic "keep it simple" — specific mechanism: quantified comparison (your plan vs simplest possible, >2x LOC requires justification)
- **Score: 3/3**

**Knowledge irreplaceability**: 2 categories hit — Judgment heuristics (the "senior engineer" self-check is experience-derived), Pitfall memory (Karpathy's "1000 lines when 100 would do" is observed failure mode)

**Declarative > Imperative Framing:**
- Cross-domain reproduction: ✅ Karpathy tweet, TDD methodology, BDD (Behavior-Driven Development), declarative infrastructure (Terraform/K8s)
- Generative power: ✅ For any new task "do X", the pattern predicts the transformation: X → "done when [test passes]"
- Exclusivity: ⚠️ Borderline — TDD is well-known. The specific twist: applying it to *natural language task descriptions*, not just code, is the differentiator.
- **Score: 2/3** (exclusivity caveat: the NL→declarative twist is the value, not the TDD aspect)

**Knowledge irreplaceability**: 2 categories — Judgment heuristics (knowing *when* to convert vs when literal execution is fine), Unique behavioral patterns (Karpathy's specific observation that declarative framing makes agents "loop longer and gain leverage")

### P1 — Worth Doing (3 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| Self-Correction Loop with Approval Gate | Agent 识别自身错误 → `[LEARN] [Category]: rule` → 人工审批 → 持久化。关键: 非自动，需审批（v1 自动化一周产生矛盾规则） | 在 `.remember/` 体系中增加 `[LEARN]` 格式标签。当 session 中发生错误修正时，agent 生成 `[LEARN]` 条目，写入 `today-*.md`，owner 在 review 时决定是否升级为 `core-memories.md` | ~4h |
| 100-Token Principle Card | 将核心约束压缩到 ~100 token 的"原则卡片"。forrestchang 证明 66 行 CLAUDE.md 足以改变行为，不需要完整的 gate system 来传达基本纪律 | 为每个 SOUL/public/prompts/ 文件创建 <100 token 的 TL;DR 摘要行。当 context budget 紧张时（subagent dispatch），只注入摘要行而非完整文件 | ~3h |
| Before/After Teaching Pairs | EXAMPLES.md 用"❌ What LLMs Do"和"✅ What Should Happen"的对比格式教学。不是规则声明，是行为示范 — 对 LLM 来说，示例比规则更有效 | 为 rationalization-immunity.md 增加 3-5 个 code-level before/after pairs（当前只有思维模式表格，没有代码示例） | ~2h |

### P2 — Reference Only (3 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| SQLite Learning Store | rohitg00 从 markdown 迁移到 SQLite 存储学习记忆，支持全文搜索 | 我们的 `.remember/` + grep 在当前规模够用。当记忆条目超过 ~100 条时重新评估 |
| Write/Select/Compress/Isolate | Lance Martin 的 context engineering 四步框架 | 概念有价值但我们已有 collaboration_modes 覆盖类似功能。框架的命名比我们的更好记 — 可考虑重命名 |
| Plugin Marketplace Distribution | forrestchang 通过 `.claude-plugin/marketplace.json` 实现 one-command install | 我们的 skills 是内部使用，不需要分发渠道。但如果未来开源任何 skill，这是参考模板 |

## Gaps Identified

| Dimension | Gap | Impact |
|-----------|-----|--------|
| **Quality / Review** | 没有"simplicity pre-gate" — 简洁性仅在 review 阶段检查，不在 plan 阶段阻断 | 复杂方案通过 plan gate 后，在 review 阶段发现过度工程需要返工 |
| **Memory / Learning** | 缺少格式化的学习提取机制 — `.remember/` 是自由文本，没有 `[LEARN]` 类型的结构化标签 | 经验教训混在叙述中，不易检索和去重 |
| **Context / Budget** | 没有"principle card"式的压缩表示 — subagent 要么拿完整 prompt，要么没有 | 大型 dispatch 时 context 浪费或指令缺失 |
| **Execution / Orchestration** | 缺少 task-intake 阶段的 imperative→declarative 自动转译 | 模糊任务直接进入执行，没有在入口就转为可验证标准 |

## Adjacent Discoveries

- **Plugin 结构标准**: `.claude-plugin/plugin.json` + `marketplace.json` 的双文件结构是 Claude Code plugin 的事实标准。如果我们要发布任何 skill 为 plugin，直接复用这个结构。
- **rohitg00 的 hook 失败经验**: 过度阻断 → 用户禁用整个 hook 系统。解决方案: nudge-first（非阻断提醒）+ 仅破坏性操作用 blocking。我们的 guard-rules hook 需要注意这个风险。
- **Cross-Agent Translation (SkillKit)**: rohitg00 提到的 SkillKit 能将 Claude Code patterns 翻译到 Cursor/Codex/Gemini CLI 等 27+ agent。如果我们的 skill 体系要跨平台，这是唯一已知的翻译层。
- **Karpathy 对 LLM 编码的元观察**: "The mistakes are not simple syntax errors anymore, they are subtle conceptual errors that a slightly sloppy, hasty junior dev might do" — 这意味着我们的质量门控应该从"语法检查"转向"概念一致性检查"。
- **Karpathy 的 Starcraft/Factorio 类比**: "What does LLM coding feel like in the future? Is it like playing StarCraft? Playing Factorio?" — 编排多个 agent 工作确实更像 RTS 游戏（资源分配 + 单位调度）而非传统编程。这暗示 agent 编排 UI 可能需要 RTS 式的 command interface。

## Meta Insights

1. **规则的衰减曲线不同**: forrestchang 的 4 条原则在 66 行内完成传达，经过数千用户验证仍然有效。我们的 CLAUDE.md 系统有 200+ 行规则。更多规则不等于更好的遵守 — Karpathy 的观察 "All of this happens despite a few simple attempts to fix it via CLAUDE.md" 暗示 LLM 对 instruction 的遵守存在饱和点。超过这个点，增加规则可能降低整体遵守率。这是我们需要实验验证的假设。

2. **"感受 AGI"的时刻来自韧性，不是智能**: Karpathy: "It's a feel the AGI moment to watch it struggle with something for a long time just to come out victorious 30 minutes later. You realize that stamina is a core bottleneck." 这意味着我们在设计 agent 工作流时，不应该在前几次失败后就升级/切换策略 — 让 agent 在同一策略上坚持更久可能是更好的选择。我们的 3-attempt escalation 是否太激进？

3. **最好的约束是能记住的约束**: forrestchang 证明了一个 naming insight — "Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution" 四个名字本身就是 mnemonic device。我们的等效规则分散在 plan_template.md、rationalization-immunity.md、verification-gate 等文件中，规则更强但**不可记忆**。一个 engineer 能复述 Karpathy 四原则，但不能复述我们的规则体系。这对人机协作有影响 — 人类需要能记住规则才能在 agent 违规时发现。

4. **rohitg00 的 v1 失败是最有价值的数据点**: 自动捕获学习经验（无审批）一周内产生矛盾规则。这验证了我们 evidence tier system 的设计选择 — `impression` 级别记忆不应该自动覆盖 `verbatim` 级别。同时也意味着任何"自我改进"机制必须有人工审批门控，至少在积累足够的 eval baseline 之前。

5. **Karpathy 的 80/20 翻转是定量基准**: "rapidly went from 80% manual 20% agents to 80% agent 20% manual" — 这是我们评估 agent 效能的参考坐标。如果使用 Orchestrator 后用户的比例没有翻转，说明工具链还不够成熟。
