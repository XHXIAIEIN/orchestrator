# R80 — Flux (enchanted-plugins) Steal Report

**Source**: https://github.com/enchanted-plugins/flux | **Stars**: n/a (new repo, 2026-04) | **License**: MIT
**Date**: 2026-04-17 | **Category**: Skill-System (Prompt Engineering Platform with Self-Learning Loop)

## TL;DR

Flux 把 prompt 工程问题**数学化**（σ-收敛 + SAT 覆盖 + Gauss Accumulation），然后把执行层抽成 **10 个可复用的 Conduct 契约模块** — 每个模块 3-5 KB 纯 Markdown，前缀全局加载到所有 skill，做到"行为契约和产品逻辑解耦"。真正可偷的不是那套 prompt 优化器，而是它的**契约组件化架构**、**14-code 失败分类法**、**深度 learnings.json 数据结构**（带 confidence 衰减、弱点共现、自动建议）、以及 **U-curve 注意力预算布局**。

## Architecture Overview

```
Layer 0 — Shared Conduct（10 模块，纯 markdown 契约）
  discipline · context · verification · delegation · failure-modes
  tool-use · formatting · skill-authoring · hooks · precedent
          ↓ @-import 到所有 plugin 的 CLAUDE.md

Layer 1 — Math Engines（6 个形式化模型）
  E1 Gauss Convergence   σ(P) = sqrt(Σ(S_i - 10)² / 5)
  E2 SAT Overlay         DEPLOY ⟺ σ<τ ∧ ∧A_j
  E3 Cross-Domain Adapt  T: (P, M_s) → (P', M_t)
  E4 Adversarial Robust  Ω(P) = |{k : δ(P, α_k)=RESIST}| / |C|
  E5 Static-Dynamic Dual VERIFIED ⟺ σ<τ ∧ PassRate=1
  E6 Gauss Accumulation  K_n = K_{n-1} ∪ {(k*, Δσ, outcome)}

Layer 2 — Plugins（6 个，一命令一职责）
  prompt-crafter · prompt-refiner · convergence-engine
  prompt-tester · prompt-harden · prompt-translate
  （单一 meta-plugin "full" 做依赖汇总）

Layer 3 — Agents（7 个，严格 tier 映射）
  Opus: orchestrator/crafter/refiner —— 判断、意图、技术选择
  Sonnet: optimizer/executor/red-team/adapter —— 长循环、攻击、翻译
  Haiku: reviewer/validator —— 形状检查、新鲜度审计
```

**Artifact 标准产物**（prompts/<name>/）：`prompt.xml` · `metadata.json` · `tests.json` · `report.pdf` · `learnings.md`。**Folder hygiene**: 中间 HTML/diff/scratch 归 `state/`，`prompts/` 只放成品。

## Six-Dimensional Scan

| Dimension | Status | Findings |
|-----------|--------|----------|
| **Security/Governance** | 覆盖 | E4 对抗鲁棒性：12 attack 类覆盖 OWASP LLM Top 10；Ω(P) 量化指标 + Quality-preserving defense (S(P') ≥ S(P)-ε) |
| **Memory/Learning** | 覆盖 | `learnings.json` 7 个字段（sessions/strategy_stats/fix_history/negative_examples/weakness_profile/confidence_scores/recommendations）+ pattern detection（reliable/unreliable/stuck/plateau/co-occurring） |
| **Execution/Orchestration** | 覆盖 | 生命周期严格串行 craft→converge→test→harden→translate，每段产出 artifact 喂下一段；agent tier 映射（Opus/Sonnet/Haiku）不可跨级 |
| **Context/Budget** | 覆盖 | `context.md`：U-curve 布局（first-200 / last-200 slots）+ 50% checkpoint protocol + smallest-set rule + stale-context detection（路径/函数验证后才信） |
| **Failure/Recovery** | 覆盖 | 14-code taxonomy（F01 sycophancy → F14 version drift），带签名 + 反制 + escalation 门槛（单次 vs 3+） |
| **Quality/Review** | 覆盖 | "Self-certification is not verification"：tier split（Haiku 审 Sonnet）+ 确定性检查 + diff read-back 三选一；SAT 8 谓词 与 5 轴连续分双重 gate；auto-revert on regression |

## Path Dependency

- **Locking decisions**: 选了**skill-invoked 而非 hook-driven** → 所有自动化必须走 slash command；hooks 被降级为 advisory-only。好处是 deterministic 可重放，代价是"被动等待用户触发"，无法实现真正后台闭环。
- **Missed forks**: 如果走 hook-driven + 后台 daemon，可以像我们的 `babysit-pr` 那样做持续优化；他们选了显式命令，把控制权交给用户。
- **Self-reinforcement**: 6 plugin × 7 agent × 64 model registry 形成配置量级，越到后面越难改架构（每加一个模型要更新 registry + translator + tests）。
- **Lesson for us**: 学他们的**契约组件化**（shared/conduct/ 纯文本模块可热插拔），避免他们的**hook 残疾**（我们 guard-rules.conf 已经是 load-bearing，不要降级）。

## Steal Sheet

### P0 — Must Steal (5 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| Conduct 契约组件化 | 10 个独立 Markdown 模块（3-5KB 每个）用 `@shared/conduct/xxx.md` 语法 @-import 到所有 plugin 的 CLAUDE.md。每个模块单一主题（discipline/context/verification…），在根 CLAUDE.md 不存在；调用时按需 load | 我们 CLAUDE.md 已经 670 行，所有规则堆一起；`SOUL/public/prompts/` 有部分拆分但不走 @-import 机制 | 把 CLAUDE.md 里 `### Verification Gate` `### Git Safety` `### Context Management` 等 6-8 节拆成 `SOUL/public/conduct/*.md`，根文件只留总纲 + @-import 列表；每 skill 按需加载相关条目 | ~2h |
| 14-code Failure Taxonomy | 受控词汇表（F01 Sycophancy…F14 Version drift），每条含 signature + counter + escalation threshold；`learnings.md` 条目每行必须 tag 一个 code，用于跨会话聚合 | `.remember/` 存自然语言失败描述，无分类标签，无法做聚合统计 | 在 `SOUL/public/conduct/failure-modes.md` 建立 F01-F14，`remember` skill 写入时强制 tag；后续做 aggregation 统计"哪些 F-code 高发" | ~1.5h |
| Deep learnings.json 结构 | 7 字段结构：sessions/strategy_stats（applied/reverted/consecutive_failures）/fix_history（last 30）/negative_examples（反例库 last 15）/weakness_profile（弱点共现）/confidence_scores（10%/session 衰减）/recommendations（自动生成）；+ 5 种 pattern detection（reliable/unreliable/stuck/plateau/co-occurring） | `docs/steal/` 报告有结论但无结构化积累；strategy_stats 这类"这个策略失败过 X 次"的长期统计我们完全没有 | 在 `SOUL/public/learnings/` 建立同构 JSON；round reports 结束后用脚本把 P0 pattern 的效果（已落地 / 未落地 / 效果如何）填入，3 个 round 后开始 pattern detection | ~3h |
| U-curve Placement + 50% Checkpoint Protocol | 硬约束放 first-200 或 last-200 token slot（中间是 recall valley，-30% 召回）；context 到 50% 时 emit `<checkpoint>` 块包含 goal/decisions/open-questions/next-step，后续对话以 checkpoint 为 truth source 放弃前文 | CLAUDE.md 的 `<critical>` 块放在**中段**（Git Safety 在 ~400 行位置）；我们没有 checkpoint 协议 | (a) 重排 CLAUDE.md：把 Gate Functions / 禁止操作移到文件头或尾部 200 token；(b) 在 `verification-gate` skill 里加 checkpoint 触发（结合已有 context-gate） | ~1h |
| Precedent Log（自观察失败） | `state/precedent-log.md` 记录 Claude 自己发现的操作失败（命令报错、模式不 work），区别于用户教的 feedback；每条必有 *command that failed* + *why* + *what worked* + *signal* + *tags*；执行 bash 前 grep 这个日志；跨 session 持久化 | `.remember/` 混合了用户反馈和自观察，没有做区分；bash 命令前不查 precedent | 在 `SOUL/private/` 建 `precedent-log.md`，跟 `.remember/now.md` 并列；`.claude/hooks/pre-bash.sh` 加 grep 步骤（≤10ms） | ~1.5h |

### P1 — Worth Doing (4 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| SAT Binary Assertions 双层验证 | 5 轴连续分 + 8 布尔谓词（has_role/has_task/has_format/has_constraints/has_edge_cases/no_hedges/no_filler/has_structure）双 gate；overall 9.5 但 7/8 assertion 过仍 HOLD | 给 `verification-gate` 加一组布尔谓词（如"测试已跑"/"diff 已读"/"baseline 已拍"/"无未确认破坏操作"），任一 FALSE 即 HOLD | ~2h |
| Scope Fence for Subagent | 每次 Agent dispatch 必须带 3 条 non-negotiable clause：(1) structured return clause（明确输出 shape）(2) scope fence（"不要写文件/不要开子代理"）(3) context briefing（ruled out + 已知 + 需要检查的） | 修 `steal` skill 和 `.claude/agents/` 各 agent 的 prompt template，模板化这 3 段 | ~1h |
| Format Follows Model Registry | 64-model registry JSON，每条 entry 含 context_window/preferred_format/reasoning_type/CoT_approach/few_shot_required/key_constraints；生成 prompt 前 cross-check，model-task mismatch 提前警告 | 给 `SOUL/public/` 加精简版 `models.json`（只覆盖我们常用的 Opus/Sonnet/Haiku/GPT-5/Gemini），`chat` skill 启动时检查 | ~1.5h |
| Advisory Hooks + Injection over Denial | 坏例：hook 返回 non-zero 来 reject 操作；好例：PostToolUse inject *"3 TS errors at lines 42/78/103"*，agent 读了自己决定；hook `set -uo pipefail`（不要 -e），err `|| true` 保证 fail-open | 审计我们 `.claude/hooks/` 所有 script：`guard-rules.conf` 是 load-bearing（正确的）；其他 post-hook 改成 inject 模式 | ~2h |

### P2 — Reference Only (4 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| Gauss Convergence 数学化 | σ-最小化 + argmin weakest axis + auto-revert + plateau detection | 我们不在做 prompt optimizer 产品；但积累结构（K_n = K_{n-1} ∪ {fix outcome}）可复用 → 已归入 P0 learnings |
| Allay Hidden Markov Drift Detection | READ LOOP: count(read(f))≥3 ∧ ¬write(f)；EDIT REVERT: hash(write_n)==hash(write_{n-2})；TEST FAIL: non-zero exit count≥3 | 代码不在 Flux 仓中（README 指向 Allay），只能拿到公式 |
| Allay Linear Runway Forecasting | μ̂ = mean(tokens per turn)，runway = floor(remaining / μ̂)；分级 silent/suggest/warn/critical | 未给实现；CC 原生 auto-compact 已部分覆盖 |
| 64-model Registry 全量 | 64 个模型覆盖 text/image/video/audio | 我们用不到 image/video；只抄文本模型片段（P1） |

## Comparison Matrix

P0 patterns diff：

| Capability | Their impl | Our impl | Gap | Action |
|-----------|-----------|---------|------|--------|
| Conduct 模块化 | 10 个 3-5KB MD，@-import 到 plugin CLAUDE.md | 670 行 monolithic CLAUDE.md | Large | Steal — 拆分 |
| Failure taxonomy | F01-F14 受控词汇，带 counter + escalation | 无标签 free text in `.remember/` | Large | Steal — 建 F-code |
| Strategy stats 持久化 | applied/reverted/consecutive_failures/confidence decay | 无；报告里零散提及 | Large | Steal — 建 JSON |
| Regression 自动 revert | σ_{n+1} ≥ σ_n → revert + log F12 | 无；人工判断 | Medium | Steal — 在 verification-gate 加 |
| Checkpoint protocol | 50% token 时 emit 块；后续以它为 truth | 无；依赖 auto-compact | Medium | Steal — skill 级触发 |
| Precedent log | `state/precedent-log.md` + pre-bash grep | `.remember/now.md` 大杂烩 | Medium | Steal — 拆分 + grep hook |
| U-curve placement | first-200/last-200 slot 硬约束 | `<critical>` 在中段 | Small | Steal — 重排 CLAUDE.md |

### Triple Validation — P0 逐项

| Pattern | Cross-domain reproduction | Generative power | Exclusivity | Score |
|---------|--------------------------|-----------------|-------------|-------|
| Conduct 模块化 | ✓ superpowers skills, claude-md-management 都有类似但不成体系 | ✓ 给新 skill 时能告诉你先 @-import 哪些模块 | ✓ "模块按需 @-import + plugin 可 override + 记 override 日志" 这套**契约覆盖机制**我们没见过 | 3/3 |
| 14-code taxonomy | ✓ OpenTelemetry error taxonomy、Promptfoo eval categories 同构；superpowers.systematic-debugging 提过但无编号 | ✓ 给一个失败描述能映射到 code，告诉你 counter + 何时 escalate | ✓ 14 个分三组（generation/action/reasoning），每条有 signature 正则识别 + counter + single-vs-3+ 两档 escalation —— 专属设计 | 3/3 |
| Deep learnings.json | ✓ A/B 实验系统、bandit 算法有 strategy_stats；RLHF 有 confidence；但"统一到一个 learnings.json"未见 | ✓ 新 session 读完能回答：哪个策略能信、哪些已 plateau、推荐下一步 | ✓ 7 个字段的组合 + 10%/session 衰减 + 弱点共现检测是专属 | 3/3 |
| U-curve + checkpoint | ✓ Anthropic 官方 "long context" docs + DeerFlow 同款；"first-200/last-200" 阈值是他们特有的数字化 | ✓ 给一段长 prompt 能说"这条规则在中段，移到尾部" | ✗ 概念广传；具体 200 token 阈值 + checkpoint 模板有些 generic | 2/3（exclusivity 弱，但两条共同构成一套流程仍算 P0） |
| Precedent log | ✓ 同 superpowers.adversarial-dev 的 drift-log；但 consult-before-bash 的硬协议未见 | ✓ 新命令前 grep 能预防已知失败 | ✓ **Precedent（self-observed）vs feedback memory（user-taught）vs workflow learnings（iteration log）三类分离**是专属设计 | 3/3 |

### Knowledge Irreplaceability

| Pattern | Categories hit | Tier |
|---------|--------------|------|
| Conduct 模块化 | hidden-context（override log 这种隐性规则）+ unique-behavioral-pattern | 2 → P0 |
| 14-code taxonomy | pitfall-memory（F02 fabrication、F11 reward-hacking 都是踩坑经验）+ judgment-heuristics（single vs 3+ 阈值）+ failure-memory | 3 → P0 |
| Deep learnings | judgment-heuristics（confidence 衰减 10%/session）+ failure-memory + hidden-context（weakness co-occurrence） | 3 → P0 |
| U-curve + checkpoint | judgment-heuristics（200 token 阈值）+ pitfall-memory（recall valley -30%） | 2 → P0 |
| Precedent log | pitfall-memory + unique-behavioral-pattern（self-observed 与 user-taught 分离） | 2 → P0 |

## Gaps Identified

- **Security/Governance**: 我们没有 attack pattern 库 / 鲁棒性量化。对 prompt-injection 的防御目前是 case-by-case。（→ P1：可考虑建 mini attack set，不必 12 全收，重点几条）
- **Memory/Learning**: strategy_stats 级别的长期统计、confidence 衰减、弱点共现完全空白。（→ P0 已列）
- **Execution/Orchestration**: tier 映射我们已有但不严格；他们的 agent whitelist 比我们细。（→ P1 scope fence）
- **Context/Budget**: U-curve 布局 + checkpoint 我们空白。（→ P0 已列）
- **Failure/Recovery**: 无受控失败分类。（→ P0 已列）
- **Quality/Review**: "self-certification is not verification" 原则我们有 verification-gate 对应，但 tier split（Haiku 审 Sonnet）这种"不同模型做 reviewer"的做法，我们 reviewer skill 与 engineer 可能用同模型 → 形式上是 self-certification。（→ P1：reviewer 显式指定小模型）

## Adjacent Discoveries

- **Allay（同作者另一产品）的 HMM drift detection** 公式化了三种死循环信号，可以直接喂给我们的 hook 系统做硬指标拦截（即便代码不在 Flux 中，公式够清楚）
- **Advisory-only hook 哲学** vs 我们的 load-bearing `guard-rules.conf`：他们走反方向，可以对照自省 —— load-bearing hook 的长处是"物理级"（不可绕过），短处是"hook 挂了整个系统挂"。我们的 guard 属于 load-bearing 且是正确选择，但 post-hook 可以改成 advisory + inject
- **prompt fingerprint** 字段（words/lines/sections/has_examples/has_xml/has_markdown/domain/model）可以直接搬给 `SOUL/` 给自己的每个 prompt 打指纹，帮助 pattern detection
- **Folder hygiene** 规则（work-in-progress 留 state/，成品留 prompts/）结构性转移到 `docs/steal/`（报告成品）+ `D:/Agent/.steal/<topic>/`（工作台）我们已在做，但可以更严格

## Meta Insights

1. **Conduct 契约化 > 单体 CLAUDE.md**。670 行的文件对 U-curve 布局本身就是反模式 —— 中间那几百行永远命中 recall valley。拆成 10 个 @-import 模块 + 精简根文件，等于同时解决模块化和注意力预算两个问题。
2. **失败的价值在于分类，不在于记录**。我们有 `.remember/`，但"这次失败是 F12 degeneration-loop 第 3 次"这种聚合语义缺失，等于有日志没有分析器。**每条失败至少 tag 一个 code** 这条硬规则是把"信息"变成"信号"的最小开销。
3. **Self-learning 的关键不是"记得更多"，而是"记得正确 + 会衰减"**。confidence_scores 10%/session 衰减是对"模型/世界/代码都在变"的工程回应 —— 三个月前的成功策略今天可能已失效，不衰减就变成**纪念碑式的错误记忆**。
4. **"Skill-invoked 而非 hook-driven"是 Flux 的主动选择**，不是 deficit。他们选了 deterministic replay + 用户可控；我们选了后台闭环（babysit-pr 等）。两条路都对，但 **hook-driven 系统必须接受"guard 挂了谁都挂"的代价**，所以 guard 必须简洁到几乎不可能挂。
5. **Prompt 工程已经走到"把提示词当软件对待"阶段**：单元测试（tests.json）、regression 保护（auto-revert）、跨平台移植（translator）、对抗审计（harden）、审查员分离（Haiku tier），每一条都对应传统软件工程的一个成熟实践。值得我们把 SOUL/ 下的 prompts/ 也按这个"软件化"标准要求。

---

*Report compiled from full clone at `D:/Agent/.steal/flux/` on 2026-04-17. All six dimensions scanned, triple-validation + knowledge-irreplaceability applied per P0. Next step: implementation plan for the 5 P0 patterns (Effort budget ≈ 9h total).*
