---
round: R81
title: Millhouse (Knatte18) Steal Report
source: https://github.com/Knatte18/millhouse
stars: unpublished / forked personal workspace
license: (not declared in repo root)
date: 2026-04-17
category: Skill-System
---

# R81 — Millhouse (Knatte18) Steal Report

**Source**: https://github.com/Knatte18/millhouse (fork of motlin/claude-code-plugins)
**Date**: 2026-04-17 | **Category**: Skill-System (Claude Code plugin marketplace)

## TL;DR

Millhouse 是一个 Claude Code 多-plugin marketplace，其核心 `mill` plugin 把"设计 → 计划 → 实现 → 合并"做成了**三个独立 SKILL + 一份共享 status.md + 一个 Python 后台引擎 (`millpy`)** 的流水线。

**问题空间**：如何让 Claude Code 在一个 repo 内无人值守跑完"对话 → 写计划 → 计划多审 → 按 DAG 并发实现 → 代码审 → 合并"，同时不陷入 review 回圈 doom-loop？

**解决模式**：SKILL 只写"runtime spec"（状态机），真正的并发/聚合/配置解析走 Python 后台 (`millpy.entrypoints.*`)；三个 skill 用 status.md 的 `phase:` 字段 + `## Timeline` text block 协同；**plan-review 和 code-review 都是 N+1 并发 fan-out（N 个 per-slice + 1 个 holistic），后面跟 handler synthesis + 非进展检测器**。

核心差异：不是"给 agent 加工具"，而是"给 agent 加流程约束 + 可观测状态 + 降级路径"。

## Architecture Overview

```
Layer 0 — Config & Registry (millpy.core.config + reviewers.workers/definitions)
   pipeline.{discussion|plan|code}-review.{rounds, default, <N>, holistic, per-card}
   WORKERS (atomic)  ←  REVIEWERS (ensemble: worker × N + handler[+ handler_prep])

Layer 1 — State Coordination (_millhouse/task/status.md)
   YAML code block: task, phase, discussion, plan, blocked, blocked_reason, plan_start_hash
   ## Timeline text block: append-only phase transitions (discussed, planned, implementing, ...)
   builder.lock PID file   handoff.md one-shot baton

Layer 2 — Skill Runtime Specs (mill-start / mill-plan / mill-go + mill-receiving-review)
   mill-start    → interactive discussion, writes discussion.md
   mill-plan     → autonomous plan writer + plan-review fan-out + non-progress detector
   mill-go       → DAG-aware builder, per-card implementer spawn + per-card code review + merge
   mill-receiving-review → VERIFY → HARM CHECK → FIX/PUSH BACK decision tree (load-before-read)

Layer 3 — Python Engine (plugins/mill/scripts/millpy)
   entrypoints.spawn_reviewer   → dispatch via engine.run_reviewer (ensemble or single)
   entrypoints.spawn_agent      → claude/gemini CLI bridge (dispatch_mode: tool-use | bulk)
   core.plan_review_loop        → stateful loop: APPROVED | CONTINUE | BLOCKED_NON_PROGRESS | BLOCKED_MAX_ROUNDS
   core.dag                     → Kahn topo sort + layer extraction + CycleError with cycle path
   core.plan_io                 → v1/v2/v3 plan format resolver
   reviewers.ensemble           → ThreadPoolExecutor fan-out + degraded-fatal fallback
   reviewers.handler            → synthesize N worker reports → one consolidated review

Layer 4 — Self-reflection Loop (mill-self-report + millhouse-issue + mill-revise-tasks)
   mill-self-report  (auto-fires at end of plan/go)
     ↓ files issues into  Knatte18/millhouse  via  millhouse-issue
     ↓ later drained back into tasks.md  via  mill-revise-tasks (status-check + consolidation)
```

## Steal Sheet

### P0 — Must Steal (6 patterns)

| # | Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---|---------|-----------|------------------|------------|--------|
| 1 | **Non-progress detector for review loops** | `PlanReviewLoop` 保存每个 slice 上一轮 pushed-back bullet 列表，本轮相同 → 立即 `BLOCKED_NON_PROGRESS`。bullets 通过 regex 解析 fixer report 的 `## Pushed Back` + `### <slice-id>` 子节得到。 | 我们有 rationalization-immunity 提示，但 review 回圈全靠人发现。systematic-debugging 也只是建议。 | 把 `plan_review_loop.py` 的状态机搬到 `SOUL/tools/review_loop.py`，给 `.claude/skills/review` 和 `verification-gate` 用；fixer report 强制 `## Pushed Back` 结构化子节（含 `(empty — slice approved this round)` 哨兵）。 | ~3h |
| 2 | **Three-skill pipeline with status.md coordination** | `mill-start` (interactive) → `mill-plan` (autonomous) → `mill-go` (autonomous)。`_millhouse/task/status.md` 的 YAML block `phase:` 字段是唯一权威；`## Timeline` text block append-only 记录 phase 转换时间戳；`builder.lock` PID + `handoff.md` baton；Pre-Arm Wait 是 mill-go 轮询等 mill-plan 完成。 | CLAUDE.md 说"Spec → Plan → Implementation 各占一个 session"但没有协调机制，全靠 owner 记着当前在哪一相。 | 新建 `SOUL/public/prompts/phase_state.md` 规范化 `_phase/status.md`：YAML block + Timeline。把 plan/execute 阶段 skill 的 entry 改成先读 `phase:`；phase 不对就 stop。 | ~4h |
| 3 | **mill-receiving-review load-before-read pattern** | Skill 显式要求：**在读任何 reviewer 输出之前加载**。"If you have already read the findings, this skill is useless; you have already formed rationalizations." 默认 fix everything，只有"证明有害"能 PUSH BACK。禁用 dismissal 清单（low risk / out of scope / pre-existing 等 7 条）。 | `SOUL/public/prompts/rationalization-immunity.md` 有类似理念但没规定"先加载再读 review"；skill routing 不要求强制顺序。 | 在 `verification-gate` 和 `review` skill 里加"读 review 前必须先读 rationalization-immunity"硬规矩；抄 7 条 dismissal 到 rationalization-immunity.md 的禁用短语表。 | ~1h |
| 4 | **DAG with implicit edges from file-write conflicts** | Card Index 显式写 `depends-on`，但 build_dag 额外加隐式边：**两张 card 都在 `creates`/`modifies` 列同一个文件 → 高编号 card 自动依赖低编号**。`reads:` 不产生边。Cycle detection 用 DFS back-edge 抽出具体环路 (`CycleError.cycle`)。extract_layers 用 Kahn + 同层按 card 号排序 → 确定性 layer schedule。 | `SOUL/public/prompts/plan_template.md` 有显式 `depends on: step M` 但没有自动检测写冲突。多个 step 同时改 `.claude/skills/foo/SKILL.md` 是常见错误。 | 把 `millpy/core/dag.py` 的 build_dag + extract_layers + CycleError 搬到 `SOUL/tools/plan_dag.py`。plan_template.md 里强制声明 `creates:` / `modifies:` / `reads:` 字段；`/write-plan` skill 在写完 plan 后跑一遍 dag 验证。 | ~3h |
| 5 | **Auto-fire self-report loop (tooling-bug closed loop)** | mill-plan / mill-go 完成后自动触发 `mill-self-report` (toggle: `notifications.auto-report.enabled`)：扫本次 session 的 tool failures / UNKNOWN verdicts / prompt mismatches / subprocess hangs → 蒸馏成 candidate → 交互选号 → 经 `millhouse-issue` skill 写入 GitHub issue。后续 `mill-revise-tasks` 拉 issues → status-check (`fixed-in-main` / `moot` / `still-open`) → 折进 tasks.md。**scope 明确：bugs about MILL TOOLING, not user code**。 | 我们有 `SOUL/public/experiences.jsonl` 捕获经验，但没有"会话结束自扫 tooling bug"。experiences 的问题是杂糅用户业务和工具问题。 | 新建 `.claude/skills/self-report/SKILL.md`：stop hook 后自动扫本次会话的 tool errors；只收 orchestrator 工具链 bug（不是业务实现）；交互选号写入 `SOUL/private/tooling-bugs.jsonl`，可选写 GH issue。成套闭环：self-report → `.claude/skills/revise-tasks/` 把 bugs 折进 `SOUL/public/backlog.md`。 | ~6h |
| 6 | **Ensemble reviewer with two-level registry + degraded-fatal fallback** | WORKERS = 原子配置 `(provider, model, effort, dispatch_mode, max_turns)`；REVIEWERS = ensemble `(worker, worker_count, handler, handler_prep)`，命名规约 `"g3flash-x3-sonnetmax"`。`EnsembleReviewer.run` 用 `ThreadPoolExecutor` 并发跑 N 个 worker + 可选并发 handler-prep，部分失败 → 从幸存者合成，全失败 → `verdict="DEGRADED_FATAL"` 不崩。handler 用 `Write` 工具直接落盘 review，stdout 只做完成信号（no stdout parsing for review body）。 | 我们有多个 reviewer persona 但没注册表、没并发、没降级路径。单 reviewer 一挂就整条 review 链中断。 | 建 `.claude/reviewers/workers.yaml` + `reviewers.yaml`（或 Python dict）。写 `SOUL/tools/ensemble.py` 用 `asyncio.gather` fan-out；handler 合成走 `Write` 工具直接落盘 `.trash/reviews/<ts>-<reviewer>.md`。 | ~5h |

### P1 — Worth Doing (8 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|-----------|--------|
| **One-pass regex template substitution** | 占位符代入避免 27× 膨胀：`re.compile("\|".join(re.escape(k) for k in keys_sorted_by_len_desc)).sub(lambda m: subs[m.group(0)], template)`。原因：substituted content 里本身会提到 `<FILES_PAYLOAD>` 字样，chained `.replace()` 会递归替换。注释里明确写了 "27x blowup to 5 MB" 的踩坑。 | 检查 `SOUL/tools/compiler.py` 和所有 context-pack 模板代入逻辑，替换成单 pass regex。 | ~1h |
| **Exit-code failure taxonomy** | `KIND_RATE_LIMIT=10`, `KIND_BOT_GATE=11`, `KIND_BINARY_MISSING=12`, `KIND_UNCLASSIFIED=13` + `KIND_MALFORMED` + `KIND_TIMEOUT`。`WorkerFailure` dataclass 带 `kind / detail / exit_code / stderr_tail`。`is_malformed_output(stdout)` 检查是否有 `VERDICT:` 行或可解析 JSON。 | `.claude/hooks/` 里的 dispatch-gate、block-protect 等全部对齐这套 exit code；新建 `SOUL/tools/failures.py` 的 dataclass + classifier。 | ~2h |
| **"Thought that means STOP" rationalization table** | Skill 内嵌 markdown 表格：左列"想绕过的内心独白"，右列"现实打脸"，底下一行"Verification: You MUST have spawned the plan-reviewer before proceeding. If you have not, go back"。直接写进 skill body。 | `.claude/skills/verification-gate/SKILL.md` 和 `systematic-debugging/SKILL.md` 加这种表格；复用 CLAUDE.md 现有的 Gate Functions 结构。 | ~1h |
| **Numbered-list choice convention (no AskUserQuestion)** | 全系统禁用 `AskUserQuestion`（要鼠标）；统一用"`1) Label — description (Recommended)`"，用户打号码。mill-self-report 的"`1, 3` / `all` / `none`"是多选语法。 | `.claude/skills/` 系统里所有交互选择统一风格。CLAUDE.md 追加一节 Interactive Choices。 | ~1h |
| **Protected task marker `<!-- protected -->`** | tasks.md 里 HTML 注释硬标记；brevity-cleanup 和 merge-consolidation 都 skip 保护任务。低成本的"不要动我这条"信号。 | `SOUL/public/backlog.md` 的重要任务加 `<!-- protected -->`；revise-tasks 跳过。 | ~0.5h |
| **Per-card atomicity extraction test** | 每张 card 必须满足"一个新 agent 只读这张 card 能实现完"。Card Index 和 card body 之间有一致性规则：`reads:` 两处必须一致、`depends-on` 只能指向低编号、`creates`+`modifies` 不能同时空、所有 `Explore:` 路径也要出现在 `Reads:`。 | `SOUL/public/prompts/plan_template.md` 加原子性断言表；写完 plan 跑一个 python 校验器（类似 millpy `plan_validator.py`）。 | ~2h |
| **Staleness check via `plan_start_hash` + `started:` timestamp** | plan 写入时记 `git rev-parse HEAD`；mill-go 执行前跑 `git log --since=<started>` 针对 `All Files Touched` 列表，major change → block 回到 mill-start。 | 任何"跨 session 继续执行"的 skill（比如我们的 executing-plans）entry 都做一次 staleness check。写 `SOUL/tools/plan_staleness.py`。 | ~2h |
| **Worker model-as-name + dispatch_mode** | WORKERS dict 把"provider + model + effort + tool-use/bulk"压缩成一个字符串 name，REVIEWERS 用 name 组合。"bulk" worker 把文件内容 inline 进 prompt（适合 Gemini 这种 128k+ 上下文），"tool-use" 走 Read/Write tool（适合需要独立验证 worker 声称的场景）。 | 我们调 persona 时经常临时指定 model；建 `.claude/workers.yaml` 注册表，`persona` skill 走 name 解析。 | ~2h |

### P2 — Reference Only (6 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **Codeguide pipeline** (`codeguide-setup/generate/update/maintain`) | 给源文件自动生成 `_codeguide/` 文档结构，per-module 模板，per-folder overview 路由表，`cgignore.md` + `cgexclude.md` 双重忽略 | 我们 docs/architecture/modules 的手写文档已够用；这套 pipeline 需要维护模板和 resolver 脚本，ROI 低 |
| **VSCode worktree color coding** | 读 `.vscode/settings.json` 的 `titleBar.activeBackground`，映射到 Claude Code 的 `/color <name>` | 我们基本不用多 worktree 并跑，视觉区分需求不强 |
| **Discussion file phased schema** | `discussion.md` frontmatter + `## Problem / ## Approach / ## Decisions / ## Q&A` 结构化节 | 我们 `brainstorm` skill 已输出类似结构，改成强 schema 成本大于收益 |
| **Gemini CLI 128k bulk mode** | 用 Gemini 做 reviewer worker，prompt 里 inline 整份 payload；handler 用 Claude 合成 | 我们没接 Gemini，且 Claude ensemble 目前够用；未来多模型投票时再来抄 |
| **Forwarding wrapper pattern for plugin cache** | `_millhouse/mill-spawn.py` 运行时 resolve 三层路径：本地 wrapper → in-repo plugin → `~/.claude/plugins/cache/<slug>/<version>/scripts/...` | 我们不做 marketplace 分发；跨 repo 复用由 SOUL 直接承担 |
| **Two-thread model-cost split** | Thread A (Opus, 设计+计划) → Thread B (Sonnet, 实现+review) hard handoff；Opus work ends at plan approval | Orchestrator 目前 Opus 全程；如果要降本，这是模板 |

## Comparison Matrix (for every P0)

| Capability | Millhouse impl | Orchestrator impl | Gap | Action |
|-----------|---------------|-------------------|-----|--------|
| **1. Review loop non-progress detection** | 状态机 `PlanReviewLoop`；per-slice prev bullets dict；识别相同 pushed-back → `BLOCKED_NON_PROGRESS`；fixer report 强制 `## Pushed Back` 子节 | 无自动检测；`rationalization-immunity.md` 仅规劝 | **Large** | Steal mechanism + adapt to our skill system |
| **2. Phase state coordination** | `status.md` YAML + Timeline append-only；`phase:` 字段唯一权威；`builder.lock` PID + `handoff.md` baton；Pre-Arm Wait 轮询 | CLAUDE.md 写了 phase separation 原则，但无状态文件；靠 owner 记忆 | **Large** | Create `_phase/status.md` schema + skill entry guards |
| **3. Load-before-read review receiving** | `mill-receiving-review` 必须先加载再读 review；默认 fix everything；7 条禁用 dismissal 清单 | `rationalization-immunity.md` 存在但不强制加载顺序 | **Small** | Patch verification-gate + rationalization-immunity 增加加载顺序硬规矩 |
| **4. DAG with implicit write-conflict edges** | Kahn topo sort + 文件写冲突 → 自动序列化 + DFS cycle path 提取 | plan_template.md 要求 `depends on: step M`，但写冲突靠人发现 | **Medium** | Port `dag.py` + plan_template schema 增加 creates/modifies/reads 字段 |
| **5. Self-report tooling-bug loop** | auto-fire at plan/go 完成；scope 限定 "mill tooling not user code"；交互 numbered 选号；三态 issue drain (`fixed-in-main`/`moot`/`still-open`) | `experiences.jsonl` 杂糅；无自动扫描；无 issue → backlog 回流 | **Large** | Build complete loop: self-report skill + stop hook + `SOUL/private/tooling-bugs.jsonl` + revise-tasks skill |
| **6. Ensemble reviewer + degraded fallback** | Two-level registry + ThreadPoolExecutor fan-out + 部分失败合成、全失败 `DEGRADED_FATAL`；handler 直接 Write 落盘（no stdout parse） | 单 reviewer persona 串行；失败则整体挂掉 | **Medium** | Build `.claude/reviewers/` registry + `SOUL/tools/ensemble.py` |

## Gaps Identified (mapped to six dimensions)

- **Security / Governance**: Millhouse 不用 hook（taskmill-legacy 里有 `validate-git.sh` 挡 `git add -A` / force push，但 mill 里**砍掉了**）。这是**反向信号** — Orchestrator 重 hook，millhouse 重 prompt 纪律 + subagent 审。我们 hook 是对的，但可以抄它们的 **prompt 层纪律**（rationalization 表、receiving-review 决策树）作为 hook 之外的补充层。
- **Memory / Learning**: **大 gap**。Millhouse 有 `mill-self-report` → GitHub issue → `mill-revise-tasks` → tasks.md 的完整闭环。我们 experiences.jsonl 是开放流水账，没有"drain + consolidate + status-check"回路。P0 #5 填这个。
- **Execution / Orchestration**: **最大 gap**。Millhouse 有 DAG-aware 并发 + per-slice fan-out review + 非进展检测 + Pre-Arm Wait 跨-skill 协调。我们 `executing-plans` skill 是线性串行，无 DAG 无并发无检测。P0 #1、#2、#4、#6 都对着这一层。
- **Context / Budget**: Millhouse 的 bulk vs tool-use dispatch_mode 区分、128k Gemini bulk 把文件 inline、handler_prep 并发 prep pass 是成熟的 context 策略。我们 compiler.py / boot.md 的 token 预算目前手工控。P1 "worker model-as-name + dispatch_mode" 对齐这一层。
- **Failure / Recovery**: **中 gap**。Millhouse 失败分类学 + `DEGRADED_FATAL` 优雅降级 + blocked 不自动 rollback + 显式 blocked_reason 保留现场。我们 hook 返回非零但缺统一 taxonomy。P1 "Exit-code failure taxonomy" 对齐。
- **Quality / Review**: **中 gap**。Millhouse 有 N+1 parallel fan-out（per-card + holistic）+ 非进展检测 + receiving-review 决策树 + ensemble handler 合成。我们 review 是单 persona 串行。P0 #1、#3、#6 全都对着这一层。

## Adjacent Discoveries

1. **SKILL.md as runtime spec, not prose manual**。mill-go 的 SKILL.md 写的是状态机规格（Phase 表、polling loop bash code、Gate 表、Stops When 清单），不是"什么时候用这个 skill 的说明"。这是 skill 工程学的升级：skill = runtime，不只是文档。值得迁到 orchestrator 的 `executing-plans` / `write-plan`。
2. **"Skill MUST be invoked before reading reviewer output"** 这种 pre-condition lock-in 模式。如果已读过，skill 废了——行为窗口被定义了。我们可以用这个套路定义其他 pre-load skill（比如 debug 前必须先加载 systematic-debugging）。
3. **mill-setup auto-migration**。CLAUDE.md 里 "Config schema out of date. Run 'mill-setup' to auto-migrate." 是 graceful evolution 信号：schema 演进时不是崩溃，是提示迁移。我们的 boot.md / SOUL 结构演进可以抄。
4. **Forwarding wrapper pattern** 用 `_millhouse/<script>.py` 本地一行 wrapper 统一解析"repo/cache/plugin"三处的脚本位置。我们目前 `SOUL/tools/*.py` 路径散落，可以做个统一 resolver。
5. **`@mill:<skill>` vs `@<plugin>:<skill>` 命名约定**。workflow skill 里的 skill invocation table 用 `@mill:code-quality`、`@python:python-build`。我们现在 skill 引用是纯名字，没有 namespace。增加 `@soul:verification-gate` 之类的约定能让 prompt 里调用更清晰。
6. **"Empty intensifiers" 清单 + 删词测试**。conversation/SKILL.md 给了 15 个空放大副词（any, actually, really, genuinely, definitely, ...）和"删掉后意思不变就删"的测试。直接可以合并到我们的 voice.md。
7. **Incident narrative as rule rationale**。conversation/SKILL.md 的 Worktree Isolation 一节结尾有一段 "2026-04-13 track-child-worktree run ... a single stray `cd` derailed the rest of the run"——具体事故日期 + 连锁后果。这比"请小心 cd"有力十倍。我们 experiences.jsonl 里的事故原文可以提炼成 rule 的 "Why" 尾注。

## Path Dependency Speed-Assess (R58)

- **Locking decisions**: 选 PowerShell 做 `spawn-agent.ps1` → 长期绑在 Windows-first；选 status.md 的 YAML code block + Timeline text block 协同 → 后续所有 skill 都必须会解析这个混合格式；选 `_millhouse/` 作为状态目录（gitignored）→ 跨 worktree 状态不跟 git 走。
- **Missed forks**: 他们在 mill-legacy 有过 hook-based 硬约束（`validate-git.sh`、`validate-protected-files.sh`），但 mill 里**主动砍掉了** hook，全押 prompt 纪律 + subagent 审。这是一个重大分叉——Orchestrator 走的是反方向（重 hook）。两条路各有利弊，我们的方向在 sensitive 操作上更稳，他们的方向在新手适配上更灵活。
- **Self-reinforcement**: 三个 skill 共享 status.md 的设计迫使所有新 skill 也走 status.md——越加越深。一旦引入 DAG、fan-out review，又必须加 `plan_io` / `plan_review_loop` 等核心模块，工程重度不断增加。
- **Lesson for us**: **抄他们的 chosen path — plan state + review loop + self-report — 不抄 path lock-in（不搬 PowerShell，不搬 `_millhouse/` 命名）**。在我们自己的 SOUL 根下建 `SOUL/tools/phase/` 和 `.claude/reviewers/`，用已有 hook 层兜底强约束。

## Meta Insights

1. **"Skill 是 runtime spec"** 是 mill 的核心方法论。传统 SKILL.md 是"什么时候用这个 skill 的说明"，millhouse 的 SKILL.md 是"这个 skill 的状态机规格"——phase 列表、polling bash、gate 表、notify procedure、stops-when 清单。这意味着 skill 本身承担了 orchestration runtime 的职责，不需要 Python 调度。Orchestrator 可以抄这个方法论，把 `executing-plans` 从 prose 改成状态机规格。

2. **"Phase state + Timeline append-only"** 是跨-skill 协调最省的方案。一份 markdown 文件同时承担三个职责：(a) YAML 块是机器可读状态；(b) Timeline 是人类可读时间线；(c) 编辑方法是"append before closing fence"避免结构破坏。比 DB 轻、比 JSON 可读、比 sqlite 便携。

3. **非进展检测器（BLOCKED_NON_PROGRESS）是 review 自治化的关键**。没有它，LLM-reviewer 会陷入无限改-改-改循环；有了它，"同样一组 pushed-back finding 出现两次 → 设计争议 → 升级给人"。这是把"人类何时介入"用规则码化。

4. **"Default: fix everything. The only valid escape is proven harm"** 是 receiving-review 的杀手锏——它把 cost 不对称的推理（不 fix 现在省几秒 vs 累积成 next task 抄错模式）用默认值固化。所有 "low risk / out of scope / pre-existing" 的自我开脱被命名为 "forbidden dismissals"。我们的 rationalization-immunity 应该合并这份清单。

5. **自我反思闭环（mill-self-report）最值得抄的不是技术，是 scope 限定**：**只扫 tooling bug，不扫 user code**。一行规则就让自反思从"啥都装进来"的垃圾桶变成高信号的工具链 issue 流。我们 experiences 系统的下一步进化就该是 scope 切分：tooling-bugs / decision-memory / user-pattern 分开存。

6. **Cost/context boundary at plan approval**（Thread A Opus → Thread B Sonnet hard handoff）是经济学决策而非技术决策。Opus 只做不可逆的"设计"；可逆的"实现 + review 修复"用便宜模型。Orchestrator 目前 Opus 全程，如果有一天要降本，plan 审核通过是天然分界线。

7. **他们砍掉 hooks 走 prompt-only 纪律，我们重 hooks，两条路不矛盾可以叠加**。millhouse 的 prompt 层纪律（receiving-review 决策树、rationalization 禁用表、non-progress 检测器）在 hook 兜不住的抽象层（比如"是不是在自我合理化"）补齐。我们已有的 hook 层（dispatch-gate、block-protect、guard-rules）管住物理动作，加上 millhouse 式 prompt 纪律管住推理路径，才是完整的 governance。
