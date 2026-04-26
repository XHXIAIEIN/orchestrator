# R80 — Eureka Steal Report

**Source**: https://github.com/sticatz/eureka | **Stars**: — | **License**: 未声明（仓库无 LICENSE 文件）
**Date**: 2026-04-17 | **Category**: Skill-System
**Repo Size**: 1660 LOC (8 SKILL.md + CONVENTIONS.md + IDEA.md + README.md) | **Commits**: 7

---

## TL;DR

Eureka 是一个 Claude Code 插件：8 个 skill（7 workflow + 1 read-only utility）把"想法评估"从 brainstorming 变成一条产出可辩护判决（go/park/kill）的流水线。核心机制不是功能，而是**把跨 skill 的协作协议下沉到 YAML frontmatter**——每个 phase 的 artifact 都是"机器可读状态机 + 人类可读推理"的双层结构，下游 skill 通过读 frontmatter 路由、检测 gap、加 override、聚合 verdict。对 Orchestrator 而言，这是我们长期缺的一块：SOUL/public/prompts/ 里有大量分散的 template/protocol，但没有统一的 frontmatter schema 让 skill 之间互读状态；verification-gate 和 plan_template 都是单点约束，没有跨 phase 回指机制。

---

## 架构全景

### 工作流层次

```
idea-start (router, no artifacts)
   ↓
concept → validate → gtm → feasibility → mvp → decide
              ↑         ↑         ↑         ↑         ↑
              └─────────┴─────────┴─────────┴─────────┘
                  back-arrow gaps (advisory, non-blocking)

idea-recap (read-only utility, invokable anytime)
```

### 持久化

```
ideas/<idea-slug>/
  CONCEPT.md        # phase 1 artifact
  VALIDATION.md     # phase 2
  GTM.md            # phase 3
  FEASIBILITY.md    # phase 4
  MVP.md            # phase 5
  DECISION.md       # phase 6 terminal
```

磁盘文件 = 完整 state。git-trackable。一个 idea 的全部记忆就是这个目录。

### Artifact 双层结构

```markdown
---
phase: validate
status: complete
verdict: proceed-with-caution
evidence_strength: weak
key_risks: [cold-start, low-willingness-to-pay]
overridden: false
override_reason: null
gaps:
  - phase: concept
    note: "target user still described as 'small businesses'"
    severity: significant
    resolved: false
    resolved_in: null
---

# Problem Validation — <idea name>
<freeform prose written collaboratively by skill + user>
```

**Frontmatter 是协议**：skill 读它来路由、检测 killer verdict、计算 evidence cap、扫描未解决 gap。**Prose 是内容**：真正的思考不适合预设 H2。"sections are starting points — rename/reorder/add as needed"。

### 六维扫描

| 维度 | 观察 |
|------|------|
| **Security / Governance** | 四级 Gating Protocol: A (killer verdict, blocking-overridable with verbatim reason) / B (depth-gap back-arrow, advisory) / B' (rerun 时的 cross-artifact 写回 `resolved: true`，narrow exception) / C (idea-decide 硬门，要求 5 priors complete，无 override) / D (No silent patching — phase 不得改其他 artifact 的 prose，只允许 footer `## Notes from <phase>`) |
| **Memory / Learning** | 无 DB 无缓存。全部持久化到 `ideas/<slug>/*.md`，git-trackable。idea-start 读全部 artifact 的 frontmatter 路由，decide 读 5 个 priors 聚合。上下文隔离：每个 skill 独立 session，只读 CONVENTIONS.md + 必要 priors，不传递对话 context |
| **Execution / Orchestration** | Linear workflow with advisory back-arrows。显式反对 auto-transition：每个 phase 结束显式问 "want to keep refining, or move on?"，用户 go-ahead 才调下一个 skill。Router (idea-start) 铁律：never do thinking / never write artifacts / never auto-transition |
| **Context / Budget** | 每 skill 约 150-180 行 SKILL.md。CONVENTIONS.md 268 行作为共享协议（每个 skill 开头读）。artifact 持久化磁盘避免把 6 轮对话塞进一个 context。"Save after each significant exchange" — 不等 phase 完成，边聊边写 |
| **Failure / Recovery** | Escalation Protocol: 3 轮跨维度答不出 → 主动 pause，把未答问题列进 `## Open Questions`，写 `status: in-progress`，不设 verdict。Phase Readiness Check: 完成前若 assumption 多于 evidenced claims，主动警告 "会被 decide 打低分，要处理吗？" |
| **Quality / Review** | Red Flags 表（每 skill 本地 + CONVENTIONS.md universal 两层）：左列偷懒回答 → 右列具体 pushback。Source Attribution：user-stated / researched / inferred 三级。Evidence vs Assumptions 显式分类，assumption 标 `**Assumption:** <claim>`。Evidence strength cap rule: 2 significant gaps → decide evidence_strength 上限 medium；3+ → 上限 weak |

### 深度层追踪

| 层 | 证据 |
|-----|------|
| **调度层** | idea-start 是纯 router，显式三条铁律（never thinking / never write / never auto-transition）。每个 thinking skill 的 "Phase Transition" 段显式要求等用户 go-ahead。没有 DAG 没有队列，就是 user-driven 的显式 handoff |
| **实践层** | Gap 机制的核心数据结构：`gaps: [{phase, note, severity, resolved, resolved_in}]`。下游可以向**任意**上游挂 gap（feasibility 可以指向 concept），不只是相邻。rerun 时 Protocol B' 允许**唯一的 cross-artifact 写**：flip `resolved: false → true` + 填 `resolved_in`。任何其他跨 artifact 写被禁止（Protocol D） |
| **消费层** | DECISION.md 是 terminal product；idea-recap 动态生成 summary + pre-launch checklist。checklist 不是手维护的 —— 从 MVP.md 的 "built vs faked"、open assumptions、FEASIBILITY risks、GTM faked components、unresolved gaps 派生而来。任何时候都能跑 recap，生成的是派生视图 |
| **状态层** | 文件就是状态。frontmatter 的 6 个字段（phase/status/verdict/evidence_strength/key_risks/overridden/override_reason/gaps[]）构成一个紧凑的状态机。没有单独的 state DB，git 是 audit trail |
| **边界层** | Hard gate（decide 5-priors-complete, no override）+ Overridable gate（killer verdict with verbatim reason）+ Advisory（gap back-arrow）+ Soft advisory（phase readiness / 3-miss pause）+ Boundary Enforcement（drift into tech stack/pricing/verdict 立即 redirect）。五级梯度，不是二值 |

### Path Dependency 速评

- **Locking decisions**: 选 markdown + YAML frontmatter（zero dep, git-native），把 Claude Code skill 系统当唯一 UI——没有 web/CLI 后备。这使得整个系统离开 Claude Code 就无法运行。
- **Missed forks**: 本可做成 HTTP/CLI 工具有外部可用性，但选择深度依赖 skill 系统——换来的是不写任何代码，纯 prompt 实现一个"带状态机的工作流"。
- **Self-reinforcement**: 每个 skill 的 "On Start" 第 1 步都是读 CONVENTIONS.md —— 协议层被 8 个入口反复自我强化，跑偏成本极高。fix/gaps-protocol 和 fix/skill-review-improvements 两次修订的提交历史显示：协议是可以后加固的（"tighten depth-gap protocol across skills"）。
- **Lesson for us**: 这是**主动选择值得偷**的路径，不是陷阱。Orchestrator 的 skill 系统完全具备同样的 native 化能力——我们也可以把 plan / steal / memory 的跨 skill 协作下沉到 frontmatter，而不是靠 skill_routing.md 手写决策树。

---

## Steal Sheet

### P0 — 必偷（3 patterns）

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| **Frontmatter as Cross-Skill State Machine** | 每个 artifact 开头 YAML frontmatter 字段（phase/status/verdict/evidence_strength/key_risks/overridden/override_reason/gaps[]）作为机器可读协议。下游 skill 读 frontmatter 路由、检 gate、算 cap；prose 只给人类读 | **部分**：memory 文件有 R42 evidence tier frontmatter；steal 报告有 `**Source** ... **Date** ...` 但不是 YAML frontmatter；plan_template.md 无 status/verdict 字段；skill_routing.md 是手写 if/else | 给 `docs/steal/*.md` + `docs/superpowers/plans/*.md` 定义统一 frontmatter schema（复用 R42 evidence tier + 追加 phase/status/verdict/gaps），让 boot.md / skill_routing.md 改成"扫 frontmatter 路由"而不是扫文件名 | ~2h |
| **Depth-Gap Back-Arrow Protocol (B/B')** | 下游发现上游不够深 → 写 `gaps[]` 条目（phase/note/severity/resolved/resolved_in），不阻塞继续。Rerun 上游时扫 downstream 所有 `phase=this ∧ resolved=false` 的 gap，surface 给用户，处理完 flip `resolved: true`（唯一 cross-artifact 写例外）。2+ significant → 终局 evidence 上限 medium | **缺**：Orchestrator 无跨 phase 回指机制。verification-gate 是一次性验证，不留"后来发现前面做浅了"的轨迹。plan 步骤之间没有 gap 累积 | 给 steal report follow-up round（R58 已有概念）和多阶段 plan 加 gaps 字段。round N+1 发现 round N 的盲点 → 写进 N+1 的 gaps，不重写 N。rerun round N 扫 downstream 的 gaps[] | ~1.5h |
| **Override with Verbatim Reason → Downstream Scoring** | killer verdict 是 blocking gate，但可 override —— 必须写下 **verbatim** 理由。理由写进当前 artifact frontmatter（`overridden: true, override_reason: "..."`），后续 phase（特别是 decide）显式读取并按 reason 强度打分。"just do it" 被拒绝，多次 override 累积成红旗 | **缺**：我们的 Gate Functions（rollback/delete/external msg/self-mod）是 pass-or-stop 二值，不留 override 轨迹。用户说"别管风险继续"就没有可追溯的理由，下次遇到类似场景 skill 也读不到过去的 override | Gate Functions 加 override 路径：用户 override 时要求给理由，理由追加到 `.remember/experiences.jsonl` 或 core-memories.md，类似情境下 skill 读这些历史 override 作为判断输入（强 reason = reasonable gamble；弱 reason = 红旗累积） | ~2h |

### P1 — 值得做（5 patterns）

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Red Flags Table as Executable Pushback (per-skill)** | 每个 thinking skill 的 SKILL.md 里放 Red Flags 表：左列用户偷懒回答，右列**具体的 pushback 文字**。Universal table 在 CONVENTIONS.md，per-phase table 在各 skill。指令化（"respond with pushback directly in prose, then AskUserQuestion"），不是被动列表 | Orchestrator 的 rationalization-immunity 只对 agent 自己的偷懒；加 per-skill 的"user rationalization"分支，从 brainstorm/steal/write-plan 开始补 | ~3h |
| **Source Attribution: user-stated / researched / inferred** | artifact prose 里显式标注每个关键 claim 的来源类型。用户直接说的 / 工具搜来的 / skill 推出来的，不混为一谈。Evidence vs Assumptions 显式分类 | R42 evidence tier 是 memory 层面的（verbatim/artifact/impression），把它下沉到 steal report / plan / brainstorm 产出的 prose 里——每个关键 claim 一个 tag。防止 "skill 推理被当用户意图" | ~1h |
| **Soft Scaffolding + "Rename/Reorder" Permission** | 模板写 H2 标题作为 starting points，显式一句："These sections are starting points. Rename, reorder, or add sections to match how the content actually unfolded." —— 降低 sycophantic "强行塞进预设 section" 的对齐压力 | plan_template.md、steal-schema.json、superpowers plans 都改一行；不改实现，只加"许可证" | ~15min |
| **Phase Readiness Warning Before Completion** | skill 在 phase 完成前自检：若 assumption 占大头 / 占位符多 / 证据稀薄 → 主动说"这样会被后续打低分，要处理吗？" 用户决定，不自作主张 | write-plan / brainstorm 的 completion 前加一步 quality check：placeholder 比例高或 verify 步骤缺失 → 显式警告 | ~1h |
| **Slim Router Skill (No Thinking)** | idea-start 三条铁律：never do thinking work / never write artifacts / never auto-transition。只读 `ideas/*/` 所有 frontmatter，生成路由表，让用户选 | Orchestrator 的 boot.md 已做部分 routing，但没有 "列出 active ideas / plans / open gaps" 维度。加一个 `/orchestrator:status` 或扩展 boot.md：扫 docs/steal/ + docs/superpowers/plans/ 的 frontmatter，给一张 "你在哪、下一步去哪" 的表 | ~1.5h |

### P2 — 参考级（2 patterns）

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **Workflow Order as Explicit Design Decision** | GTM 先于 feasibility，IDEA.md 显式解释原因（"distribution kills more ideas than technology"）。顺序不是随意，是 domain judgment | Orchestrator 的 skill 顺序大多是隐式；可以在 plan_template.md 里加一段 "phase order rationale"，但这是写作规范不是机制 |
| **Escalation: 3-Miss Pause** | 用户连续 3 轮跨维度答不出 → skill 主动 pause，把未答列为 Open Questions，不强推 | 需要对话状态追踪（连续几次 AskUser 空回），实现成本高；我们当前的对话 skill 不够成熟，先放参考 |

---

## Comparison Matrix（P0 patterns）

### P0-1: Frontmatter as State Machine

| Capability | Eureka 实现 | Orchestrator 现状 | Gap | Action |
|-----------|-----------|---------|-----|--------|
| 统一 frontmatter schema 跨 skill artifact | ✅ 7 字段 + gaps[]，CONVENTIONS.md 定义 | 部分：memory R42 evidence tier；steal report 用 markdown header 非 YAML | 大 | Steal |
| skill 读 frontmatter 路由 | ✅ idea-start 扫 `ideas/*/` frontmatter 决定下一步 | 无：skill_routing.md 是人写决策树，非程序化扫描 | 大 | Steal |
| phase 互读状态（verdict/evidence/override） | ✅ decide 读 5 priors 的 frontmatter 聚合判断 | 无：plan 之间、steal round 之间无状态互读 | 大 | Steal |
| prose 和 metadata 分离 | ✅ YAML + markdown 双层 | 部分：memory 文件有，但多数 doc 混一起 | 中 | Enhance |
| Save after each significant exchange | ✅ skill 指令 | 无显式规范 | 小 | Reference |

### P0-2: Depth-Gap Back-Arrow

| Capability | Eureka 实现 | Orchestrator 现状 | Gap | Action |
|-----------|-----------|---------|-----|--------|
| 跨阶段 gap 追溯（下游指上游，任意阶段） | ✅ gaps[] with phase 字段 | 无 | 大 | Steal |
| severity 分级（minor/significant） | ✅ 显式二值 | 无 | 大 | Steal |
| cap rule（2 significant → medium, 3+ → weak） | ✅ 阈值规则数值化 | 无 | 大 | Steal |
| Protocol B': 唯一 cross-artifact 写例外 | ✅ 明确定义 narrow exception | 无（我们的 CLAUDE.md 只有 Protocol D 的等价 = no silent patching） | 大 | Steal |
| rerun 时 scan downstream gaps | ✅ skill 启动时扫 | 无 | 大 | Steal |
| 资源化 resolved 为正向信号 | ✅ decide 显式 "treat as positive signal" | 无 | 中 | Enhance |

### P0-3: Override with Verbatim Reason

| Capability | Eureka 实现 | Orchestrator 现状 | Gap | Action |
|-----------|-----------|---------|-----|--------|
| gate 允许 override 但强制给理由 | ✅ "just do it" 被拒，需 substantive reason | 部分：Gate Functions 有 4 层 gate（delete/reset/external/self-mod），但无 "override with reason" 路径 | 中 | Steal |
| verbatim 捕获 reason | ✅ override_reason 字段原文保留 | 无 | 大 | Steal |
| downstream 读取 reason 并打分（强 reason = 合理赌博，弱 = 红旗） | ✅ decide 显式权衡 | 无 | 大 | Steal |
| 多次 override 累积成红旗 | ✅ 显式提及 compounds | 无 | 大 | Steal |

---

## Gaps Identified（对照六维）

| 维度 | Eureka 覆盖而我们没覆盖 |
|------|----------------------|
| **Governance** | override-with-reason 机制；cap rule（gap 数量数值化影响最终 verdict） |
| **Memory** | cross-skill artifact 互读协议（frontmatter 统一 schema） |
| **Orchestration** | slim router skill（专职路由、不做 thinking）；显式反对 auto-transition |
| **Context** | N/A（Eureka 策略与我们一致——artifact 持久化到磁盘 + skill 独立 session） |
| **Failure** | phase readiness warning（完成前自检证据质量）；3-miss pause（Eureka 有我们没） |
| **Quality** | per-skill Red Flags 表（我们只有 agent 级 rationalization-immunity）；Source Attribution 下沉到 prose（我们只在 memory frontmatter） |

---

## Adjacent Discoveries

1. **markdown + YAML frontmatter 作为"配置化工作流"的 zero-dep 解法**：没有任何框架代码，纯靠 Claude Code skill 系统。说明"用 prompt 实现带状态机的 orchestration"可行；可以反过来审视 Orchestrator 的 `src/` 里是否有 Python 代码其实 skill-only 就够。
2. **"Distribution kills more than tech" 作为 domain 直觉**：这个判断让 GTM 早于 feasibility 成了架构级决策。类似的 domain judgment 在 Orchestrator 里散落各处（如 "记忆不是越多越好"、"governance 比 features 重要"），没有集中成 "design principles" 章节。可以从 CLAUDE.md 和 SOUL/public/prompts/ 抽出 10 条，做成 Orchestrator 的显式 design principles。
3. **pre-launch checklist 派生化**：recap 不维护 checklist，是从 MVP/feasibility/gaps 现场生成的 —— 这种 "派生视图" 思路适用于 Orchestrator 的 dashboard：不存汇总数据，扫原始 artifact 现场算。
4. **Brutal honesty 作为产品差异化**：Eureka README 直接说"Sycophantic AI is free elsewhere"——这和 Orchestrator 的 brutally honest friend voice calibration 同源。值得在 SOUL/public/voice.md 加一段交叉参考，说明这不是孤例。

---

## Meta Insights

1. **frontmatter 不是文档特性，是协议层**。把状态机写到磁盘就等于做了跨 skill 的 message passing。Orchestrator 有大量 markdown 文档，但只有 memory 子集有 frontmatter——其他都是"prose for humans"。升级 steal/plan/memory 全部走 frontmatter 协议，skill_routing 从手写决策树变成 "scan frontmatter, dispatch"，这是一次结构性简化。

2. **gate 是梯度，不是二值**。Eureka 的五级 gate（hard no-override → blocking-overridable → advisory → soft warning → boundary redirect）比我们的 Gate Functions（binary pass/stop）精细一个数量级。其中最有学习价值的是 **Advisory/Soft 两级**——它们承认"有些警告用户可以合理忽略，但忽略本身要留轨迹"，这是我们缺的。

3. **"Never silently patch" 是协议的地基**。Protocol D（no silent patching）看起来是常识，但配合 Protocol B'（唯一 narrow 例外）才完整——任何数据修正必须"声明、surface 给用户、要求确认"才能发生。Orchestrator 的 edit-integrity 规则（Read 后再 Read 确认）是同构思想的单点实现，没下沉到跨 artifact 协议。

4. **workflow order 本身是架构决策**。GTM 先于 feasibility 这个顺序不是随便排的——它编码了 "distribution kills more than tech" 这一 domain judgment。Orchestrator 的 `spec → plan → implementation` 顺序也是 domain judgment（知识比代码重要），但我们从没解释过 *why*。显式写出来，后来者能跟对齐，改动前会三思。

5. **"the verdict is the product" 思想**。Eureka 每个 skill 都显式服务 idea-decide 这个终局。Orchestrator 缺少一个类似的 terminal —— 我们有大量输入（boot, skill, plan, steal），但没有"一切服务于哪个产出"的锚。值得想：Orchestrator 的 terminal product 是什么？是 `.remember/core-memories.md`？是某个跨 round 的"偷师收敛报告"？没有 terminal，每个 skill 都在为自己服务，协作协议就很难收紧。
