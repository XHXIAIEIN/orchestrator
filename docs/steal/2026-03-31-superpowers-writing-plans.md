# Round 23: superpowers/writing-plans @obra — 深挖报告

> 来源：https://github.com/obra/superpowers/tree/main/skills/writing-plans
> 日期：2026-03-31
> 关联 skills：executing-plans, subagent-driven-development, brainstorming
> 许可：MIT

---

## superpowers/writing-plans @obra

**概述**: 一套完整的"从 spec 到可执行计划"的方法论——把需求分解成 2-5 分钟的原子步骤，每步带完整代码、精确文件路径、验证命令和预期输出，然后通过 self-review 三重检查（spec 覆盖 / placeholder 扫描 / 类型一致性）确保计划可直接交给零上下文的 agent 执行。

**核心机制**: Spec → File Map → Bite-sized Tasks (TDD) → Self-Review → Execution Handoff

---

## 可偷模式

### P0 — 立刻能用

#### 模式 1: Bite-Sized Task Granularity（原子步骤粒度）

**描述**: 每个 step 是一个动作（2-5 分钟）：写失败测试 → 运行确认失败 → 写最小实现 → 运行确认通过 → commit。不是"实现 X 功能"这种模糊指令，而是拆到不可再分的原子操作。

**为什么值得偷**: 我们三省六部的派单粒度太粗。一个 Task 可能是"实现 ExamCoach 的路由逻辑"——这对 sub-agent 来说太大了，它会在中间迷路或跳步。obra 的方法保证了每个 step 都是 agent 一次上下文窗口能完成的，失败时回滚成本极低（就一个 step）。

**与 Orchestrator 现状差异**: 我们已经在 `docs/plans/2026-03-30-exam-team-plan.md` 里用了类似格式（从 superpowers 学的），但不是所有计划都这样写。三省六部的日常派单（非正式 plan）仍然是粗粒度的口头指令。

**适配方案**:
1. 在 `SOUL/public/prompts/` 加 `plan_template.md`，把 obra 的 task structure 固化为模板
2. Governor 派单时，对复杂任务（预估 >15 min）自动触发 writing-plans 流程而非直接派
3. 阈值判断可以用 token 预估或文件数量

---

#### 模式 2: No Placeholders 铁律

**描述**: 计划中绝对禁止出现的模式——"TBD"、"TODO"、"implement later"、"similar to Task N"、"add appropriate error handling"。每一步必须包含实际的代码块、实际的命令、实际的预期输出。

**为什么值得偷**: 这是 agent 计划的致命弱点。人类看到"add validation"知道怎么做，agent 看到这个会瞎猜。placeholder 是计划质量的照妖镜——有 placeholder 的计划不是计划，是许愿。

**与 Orchestrator 现状差异**: 我们没有明确的 anti-pattern 清单。CLAUDE.md 里的 "Surgical Changes" 规则只管实现层面，不管计划层面。

**适配方案**:
1. 在 plan_template.md 里列出禁止模式的完整清单（直接搬 obra 的列表）
2. Self-review checklist 加 placeholder scan 步骤
3. 可选：写一个 `hooks/plan_lint.py`，用正则扫描计划文件中的禁止模式

---

#### 模式 3: File Map First（先画文件地图再拆任务）

**描述**: 在定义任何 task 之前，先列出所有要创建/修改的文件及其职责。这不只是文档——它锁定了分解决策，让后续的 task 分割有据可依。

**为什么值得偷**: 文件地图回答了"这个功能的边界在哪"。没有它，不同 task 可能对同一个文件做冲突修改，或者遗漏需要改动的文件。我们的 exam-team-plan 已经有 File Map 表格了（说明已经偷过一次），但不是所有计划都有。

**与 Orchestrator 现状差异**: 已在正式 plan 中使用，但日常小任务不强制。

**适配方案**: 纳入 plan_template.md 的必填字段。对于 <3 文件的小任务可以省略独立 File Map section，但 task 内的 `**Files:**` 字段必须有。

---

#### 模式 4: Self-Review 三步检查

**描述**: 写完计划后，自己跑三项检查：(1) Spec 覆盖——逐条对照 spec，找缺失的 task；(2) Placeholder 扫描——搜索禁止模式；(3) 类型一致性——检查函数名/类型/参数在不同 task 之间是否一致（clearLayers vs clearFullLayers 这种 bug）。

**为什么值得偷**: 计划里的不一致会在执行时变成 debug 地狱。agent 写的计划天然容易出现"Task 3 里叫 routePrompt，Task 7 里叫 route_prompt"这种命名漂移。Self-review 是零成本的质量门。

**与 Orchestrator 现状差异**: 我们有 code review（偷师 Round 22 的 Review Swarm），但没有 plan review。计划写完就直接执行了。

**适配方案**:
1. plan_template.md 底部加 Self-Review Checklist section
2. 可选：写 `plan-reviewer-prompt.md`（obra 已提供模板），作为 Governor 审计用

---

### P1 — 值得做但不紧急

#### 模式 5: Plan Document Reviewer（独立审计 agent）

**描述**: 写完计划后，dispatch 一个专门的 reviewer subagent，用结构化的 prompt 模板审查计划的完整性、spec 对齐、任务分解质量、可执行性。只标记"会导致实现问题"的 issue，不管风格偏好。

**为什么值得偷**: 自己审自己的计划有盲区。独立 reviewer 的视角能抓到 self-review 漏掉的结构性问题。obra 的 reviewer prompt 很克制——"Approve unless there are serious gaps"——不是吹毛求疵。

**与 Orchestrator 现状差异**: 三省六部有御史台（审计），但只审执行结果，不审计划本身。计划质量是盲区。

**适配方案**:
1. 在 `departments/censorate/` 加 plan-review 职能
2. 用 obra 的 reviewer prompt 模板，适配三省六部的命名
3. Governor 派单流程加一步：复杂计划写完 → dispatch 御史台审计 → 通过后再执行

---

#### 模式 6: Execution Handoff 双轨制

**描述**: 计划完成后，明确提供两种执行路径：(1) Subagent-Driven——每个 task dispatch 一个新 agent，任务间有 spec compliance review + code quality review 双重审查；(2) Inline Execution——同一 session 内批量执行，设置检查点。

**为什么值得偷**: 不同规模的任务适合不同执行策略。3 个 task 的小活没必要 dispatch 6 个 subagent（实现+审查各一个）。但 15 个 task 的大活，inline 执行会导致上下文污染。

**与 Orchestrator 现状差异**: 我们的三省六部只有一种派单模式——Governor dispatch 到部门。没有"这个任务该 subagent 还是 inline"的判断。

**适配方案**:
1. Governor 根据 task 数量/复杂度选择执行策略
2. ≤3 tasks → inline（当前 session）
3. >3 tasks → subagent-driven（per-task dispatch）
4. 关键改动：subagent 执行后加 two-stage review（spec → quality）

---

#### 模式 7: Two-Stage Review（Spec 合规 → 代码质量，顺序不可逆）

**描述**: 每个 task 执行完后，先跑 spec compliance review（做的对不对），通过后再跑 code quality review（做的好不好）。顺序不可逆——代码不符合 spec 就不要谈质量。

**为什么值得偷**: 这解决了一个常见 anti-pattern：reviewer 花大量时间在代码风格上，结果功能根本就是错的。先验 spec 合规，筛掉方向性错误，再精修质量。

**与 Orchestrator 现状差异**: Review Swarm（Round 22）已有并行审查，但没有明确的顺序约束。所有 reviewer 同时看，结果可能是"代码风格很好但功能偏了"。

**适配方案**:
1. Review Swarm 加 phase gate：Phase 1 = spec compliance（must pass），Phase 2 = code quality
2. 修改 `departments/censorate/` 的审计流程，加 sequential 模式

---

### P2 — 理念参考

#### 模式 8: Zero-Context Engineering（假设执行者完全不了解代码库）

**描述**: 整个方法论的核心假设——写计划时假设执行者对代码库一无所知。所以每一步都要写：精确文件路径、完整代码、运行命令、预期输出。"假设他们品味可疑"（questionable taste）是刻意的——不信任默认行为，一切显式化。

**为什么值得偷**: 这不是悲观，是工程。agent 确实对代码库"一无所知"——它只知道你告诉它的。人类工程师至少还能 grep、问同事。agent 拿到模糊指令就只能幻觉。

**与 Orchestrator 现状差异**: 我们的 CLAUDE.md 已经有 "Goal-Driven Execution" 规则，但那是给 agent 自己看的行为准则，不是给计划编写者的约束。计划编写时没有"假设读者是白纸"的强制心态。

**适配方案**: 这更多是心智模型的改变。在 plan_template.md 的 header 加一句提醒："Write as if the implementer has never seen this codebase."

---

## 计划模板（从 obra 提炼）

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** Execute task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** [一句话]
**Architecture:** [2-3 句]
**Tech Stack:** [关键技术]
**Spec:** [spec 文件路径]

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `path/to/file.py` | Create/Modify | 一句话职责 |

---

### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

- [ ] **Step 1: Write failing test**
  ```python
  # 完整测试代码
  ```

- [ ] **Step 2: Run test, verify failure**
  Run: `pytest tests/path/test.py::test_name -v`
  Expected: FAIL — "function not defined"

- [ ] **Step 3: Write minimal implementation**
  ```python
  # 完整实现代码
  ```

- [ ] **Step 4: Run test, verify pass**
  Run: `pytest tests/path/test.py::test_name -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git add tests/path/test.py src/path/file.py
  git commit -m "feat: add specific feature"
  ```

---

## Self-Review Checklist

- [ ] **Spec 覆盖**: 逐条对照 spec，每条需求都有对应 task
- [ ] **Placeholder 扫描**: 无 TBD/TODO/implement later/"similar to Task N"/无代码的代码步骤
- [ ] **类型一致性**: 函数名、参数名、类型在所有 task 间一致
```

---

## 与 Orchestrator 三省六部的差异

| 维度 | obra/superpowers | Orchestrator 三省六部 | 差距 |
|------|-----------------|---------------------|------|
| **计划粒度** | 2-5 分钟原子步骤 | 粗粒度功能点 | 🔴 大 |
| **计划质量门** | Self-review + reviewer agent | 无（计划直接执行） | 🔴 大 |
| **执行策略** | 双轨制（subagent/inline） | 单一 Governor dispatch | 🟡 中 |
| **审查顺序** | Spec → Quality（顺序不可逆） | 并行审查 | 🟡 中 |
| **Placeholder 管控** | 明确禁止清单 | 无 | 🔴 大 |
| **File Map** | 强制前置 | 部分计划有 | 🟢 小 |
| **Zero-Context 假设** | 核心设计原则 | 有但不系统 | 🟡 中 |
| **TDD 内嵌** | 每个 task 都是 red-green-commit 循环 | 靠 CLAUDE.md 规则提醒 | 🟡 中 |

**最大差距**: 计划质量没有守门人。我们的体系重在执行层审计（御史台审执行结果），但计划本身是"谁写谁说了算"。一个烂计划 + 完美执行 = 完美地做错事。

---

## 实施建议（优先级排序）

1. **P0-立刻做**: 把计划模板固化到 `SOUL/public/prompts/plan_template.md`，包含 bite-sized 粒度、no-placeholder 清单、self-review checklist
2. **P0-立刻做**: CLAUDE.md 的 Goal-Driven Execution 规则里加一条："Complex tasks (>15min / >3 files) require a written plan before implementation"
3. **P1-下轮做**: 御史台加 plan-review 职能，用 obra 的 reviewer prompt 模板
4. **P1-下轮做**: Governor 加执行策略选择器（task 数 → subagent/inline）
5. **P2-观察**: Two-stage review 顺序约束（等 Review Swarm 跑一段时间再决定是否改）
