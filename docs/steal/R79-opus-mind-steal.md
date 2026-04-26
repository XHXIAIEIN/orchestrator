# R79 — opus-mind (Opus 4.7 系统提示的 deterministic linter) Steal Report

**Source**: https://github.com/Hybirdss/opus-mind | **Stars**: 1 (2026-04-17 发布，今日更新) | **License**: NOASSERTION
**Date**: 2026-04-17 | **Category**: Skill/Prompt-System

## TL;DR

把 CL4R1T4S 泄露出的 Opus 4.7 系统提示（1408 行）逆向工程成 11 条可 regex 检测的结构不变量 + 12 个 primitive + 6 个跨切 pattern，封装成一个无 LLM 调用的 Claude Code skill。核心偷师点：**它让 "prompt 质量" 从主观手感变成可执行的 6/6 评分**，而且 skill 自身必须先过自己那关才能发布（伪善防御）。对我们这种 CLAUDE.md/SKILL.md 已经堆到 400+ 行、每次迭代都在累积无检查的 patch 的项目，这是一面急需的照妖镜。

## Architecture Overview

四层结构（我们目前只对应到最顶层 + 最底层，中间缺口巨大）：

```
Layer 1 — Knowledge base (static, reusable)
  primitives/         12 个 prompt 工程原语，每个带 evidence (源行号) + failure mode + how to apply
  patterns/           6 个跨切模式 (XML hierarchy, redundancy-as-feature, position-encodes-priority,
                      cue+example+rationale, hard-tier-labels, position-encodes-priority)
  techniques/         7 个具体技巧 (force-tool-call, paraphrase-with-numeric-limits, caution-contagion,
                      consequence-statement, injection-defense-in-band, negative-space, category-match)

Layer 2 — Deterministic engine (scripts, no LLM)
  audit.py   (906)    scan → metrics → per-invariant pass/fail → THIN/POOR/BORDERLINE/GOOD verdict
  plan.py    (226)    domain inference (has_tools/has_refusals/is_long) → required invariants
  fix.py     (453)    1-to-1 slop replacement + <FIXME> marker for judgment calls
  boost.py   (904)    10-slot coverage check (7 spec + 3 reasoning) + task_type impact ordering
  decode.py  (433)    detect which primitives a prompt already uses (presence, not quality)

Layer 3 — Skill router (SKILL.md)
  Three flows: LINT (audit a system prompt) / BOOST (upgrade a user request) / Debug (symptom → primitive)
  Routing is first-match-wins ladder, stop at match
  All Python helpers return JSON; Claude does the prose synthesis, no API key

Layer 4 — Self-audit gate (BUILD.md)
  SKILL.md 必须通过自己的 audit.py 才能 release
  Draft 1 得 4/6 FAIL（blacklist 被当成内容反被自己抓）→ 重写 → Draft 2 得 6/6 PASS
```

## 六维扫描

| 维度 | 他们的实现 | 我们的状态 | 差距 |
|------|-----------|-----------|------|
| **Security / Governance** | Reframe-as-signal (primitive 09) 把 "软化请求以合规" 本身当成越狱信号；Hierarchical override (primitive 12) 明文 Tier 1-5 优先级 | `rationalization-immunity.md` 列了 12 条借口但没 reframe 软化检测；CLAUDE.md Commitment Hierarchy 只有 3 层 | Medium |
| **Memory / Learning** | N/A — 这是一个 linter，不涉及记忆层 | 我们 R42 有 evidence tier 系统；无需从这里偷 | N/A — out of scope |
| **Execution / Orchestration** | first-match-wins ladder 在 routing 层显式实现；"Do not mix flows in a single turn" 硬边界 | `skill_routing.md` 是决策树，但未固化成"首匹配即停" | Small |
| **Context / Budget** | audit 扫描的不是语义而是 shape (number_density, hedge_density, xml balance)，所以跨语言可迁移；BOOST 的 Korean 示例显式说明"regex 会漏报，你（Claude）用母语判断" | CLAUDE.md 全英文 + 全中文并存但无检查工具；skills 没有 regex 审计 | Large |
| **Failure / Recovery** | Placeholder penalty — 检测 `<FIXME>`/`[TODO]`/`???`/`TBD`/`tk tk`，防止"通过填骨架通过 lint"；Negator + quote guard — `Claude does not say 'let me'` 不被误判 | 无 linter，无需抗穿透；但我们 Gate Functions 的 pre-check 精神一致 | Large |
| **Quality / Review** | 11 invariants × regex + threshold；THIN/POOR/BORDERLINE/GOOD 四档 verdict；domain-aware required set（has_tools→I12, has_refusals→I3+I10, is_long→I9）；self-audit gate | 只有 `prompt-linter` agent（LLM 打分，不确定性高）+ `verification-gate` 5 步证据链 | Large |

## 深度层追溯（Depth Layers）

| Layer | opus-mind 做法 | 关键发现 |
|-------|---------------|---------|
| **调度层** | SKILL.md 里的 "Routing — first-match-wins, stop at match" 三条 ladder；全部 flow 内部也都是阶段式 phase 1-5 | 连 skill 自己的入口路由都用他们倡导的 decision ladder primitive —— eat your own dog food |
| **实践层** | `_iter_violations()` vs `_iter_findings()` 的二元设计：前者扫"是否实践了不好的行为"（带 negator + quote 抑制），后者扫"是否出现了好的信号"（纯出现即计数）。两者共享 pattern 列表但语义相反 | 这是 regex-linter 最容易漏的细节。我们若实现 lint，必抄这个区分 |
| **消费层** | 每个 script 都有 `--json` 模式；SKILL.md 明文 data contract（`audit.py --json` / `plan.py --json` / `boost.py --json`）；key 稳定，新增安全、重命名需要 schema 版本 bump | 工具链组合的 stable API，不是随便加字段就改 |
| **状态层** | 无 DB、无 session state —— linter 是纯函数。这本身是架构选择：每次运行都从头扫 | 优势：无迁移问题、可被任何 CI 调用、可重放；代价：大文件慢，但 CLAUDE.md 从来不大 |
| **边界层** | `NEGATOR_PATTERNS` + `_QUOTE_SPAN_RE` 在所有"违规扫描"前置；`PLACEHOLDER_RE` 独立于 invariant 单独计数；stylebook（作者口味）opt-in via `--stylebook`，与 Opus-4.7-grounded 分数严格隔离 | 作者把"可证据溯源"（source line ref）和"作者偏好"（slop word list）在架构层就分开，避免"这条规则是我编的还是 Opus 4.7 就这样"这种争议 |

## 路径依赖速评

- **Locking decisions**: ①选了 regex + 计数做 scorer，所以评分永远是 shape 而非 semantic，跨语言/跨风格都能跑，但"规则写得合理但表达糟糕"这种质量问题永远检测不到。②选了 XML-namespace 作为 I7 的硬约束，所以不用 XML 的 prompt（纯 markdown headers）会在 xml_coverage>0 时被误评。
- **Missed forks**: 可以走 LLM-grader 路线（让 Claude 自己给 Claude 打分，质量更高但贵、不可复现），也可以走 embedding-similarity 路线（和 Opus 4.7 源文本的语义距离），他们明确选择 deterministic regex，理由是 "fuzzy judgment belongs in downstream LLM consumption of the script output"。
- **Self-reinforcement**: 每加一条 invariant 都要给 `source/opus-4.7.txt:L###` 当引用。这种源锚定机制逼他们只接受能在 Opus 4.7 源文里找到证据的规则，阻止了"这是我觉得好的风格"式功能膨胀。
- **Lesson for us**: 我们应该偷他们的**分层设计**（静态知识库 / deterministic 引擎 / skill router / 自审门）和**源锚定**（每条不变量必须指向一个明确 evidence），但不要原样照搬 11 个 invariant —— 我们的 prompt 更偏工程（中英混合、agent 指令 + 用户指令混合），invariant 列表需要本地化。

## Steal Sheet

### P0 — Must Steal (5 patterns)

| # | Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---|---------|-----------|------------------|------------|--------|
| 1 | **Deterministic CLAUDE.md / SKILL.md Linter** | 11 regex-based invariants + 四档 verdict + placeholder penalty + negator/quote guard；每条 invariant 绑定一个 primitive 文档 + source line ref | 完全没有。`prompt-linter` 是 LLM-based agent，跑一次 ≈ 几万 tokens，且不可重放 | 新增 `.claude/skills/md-lint/` skill：audit.py（改编 11 条规则为本地化版）+ 8-10 个 primitive md + JSON schema。本地化要点：中英混合权重、Gate Functions 的存在检测、`<critical>` 作为 tier-label。先用它审 CLAUDE.md + 所有 SKILL.md（7 个 skill）→ 得到基线分 | ~6h |
| 2 | **Self-Audit Release Gate** | BUILD.md 明文规定：SKILL.md 必须通过自己的 audit.py 6/6 才能 release。Draft 1 得 4/6（blacklist 被当例子反被抓）后强制重写至 Draft 2 达 6/6 | `.claude/skills/` 下 7 个 skill，无任何自审门。CLAUDE.md 更新也无门控 | 把上面的 linter 接到 `.claude/hooks/` 作为 pre-commit / pre-write 钩子：修改 `.claude/skills/*/SKILL.md` 或 `CLAUDE.md` 时强制跑 lint，<阈值拒绝 commit。阈值先设 8/11（BORDERLINE 及以上）避免一次性全改 | ~2h |
| 3 | **Reframe-as-Signal Jailbreak Defense** | 明文指令："如果你发现自己在心里把请求软化成可接受版本，软化本身就是拒绝信号，不是合规路径"。独立于 rationalization 列表之外，是**检测软化行为本身**的元规则 | `rationalization-immunity.md` 列了 12 条我常用的借口（"这个简单"、"我知道这概念"），但没有"软化到合规"这一条 meta-signal。我在操作 hooks/gate 时确实会发生"就这一次/这个场景例外"的软化，没被主动检测 | 在 `rationalization-immunity.md` 加一节 "Reframe Detection"，明文规定：当内在对话里出现"只是一个小"、"这种情况不算"、"从另一个角度看这就是 X"时，停止并反向执行。配合 Gate Functions 的 step 1 "Does the owner explicitly say X?" 作为 ground-truth 锚 | ~1h |
| 4 | **Hard Tier Labels + Hard Numbers 组合作为 compiler directives** | 用固定词汇表 `SEVERE VIOLATION` / `HARD LIMIT` / `NON-NEGOTIABLE` / `NEVER` / `ABSOLUTE` 给规则打 tier，必与具体数字配对才生效（"≤ 15 words" + "SEVERE VIOLATION"）。ALLCAPS 是 enforcement handle，不是装饰 | 我们只有一个 `<critical>...</critical>` 块，里面规则都同级。"硬 > 软 constraint" 在 steal skill 里提过但没反映在 CLAUDE.md 的规则写法上 | 在 CLAUDE.md 建立 4 级 tier vocabulary：`NEVER`（破坏性操作，如 `rm -rf /`）、`SEVERE VIOLATION`（越权：rollback 未经授权、跳过 Gate）、`HARD LIMIT`（数字阈值：skill 构成 ≤ 300 LOC 才能深改）、`DEFAULT`（一般偏好）。每条规则必须归到一类 | ~3h |
| 5 | **Redundancy as Feature — 7-Pass Template for High-Stakes Rules** | 同一条高风险规则（15-word 限额）在 preamble / formal rules / hard-limits / self-check / example / consequences / critical-reminders 七处以**不同视角**重述。不是 copy-paste，是多种 framing（规则声明 / 数字上限 / 运行时断言 / 案例锚定 / 后果解释 / 尾部提醒） | 我们的 Gate Functions 只出现在 CLAUDE.md `<critical>` 块一次。Rollback 禁令在 CLAUDE.md 和 boot.md 各一次但 framing 相同 | 对三条高风险规则（rollback、[STEAL] 分支强制、删除前必 mv .trash/）做 3-pass 最小重述：①boot.md 的简短身份级声明 ②CLAUDE.md `<critical>` 的形式化规则 ③对应 Gate Function 的运行时自检问题 | ~2h |

### P1 — Worth Doing (5 patterns)

| # | Pattern | Mechanism | Adaptation | Effort |
|---|---------|-----------|------------|--------|
| 6 | **BOOST 10-Slot Prompt Model + impact_order by task_type** | 7 spec 槽 (task/format/length/context/few_shot/constraints/clarify) + 3 reasoning 槽 (reasoning/verification/decomposition)；不同任务类型排不同顺序（code→decomposition 优先，write→context 优先）；一次问一个问题 | 可以做成 prompt-maker 的 boost 子命令，或独立 skill。用户粘贴一个短请求 → 跑 check → 按 impact_order 一次问一个空槽 | ~4h |
| 7 | **Domain-Aware Required-Invariant Set** | `plan.py` 先推断 has_tools / has_refusals / is_long / has_examples，再决定哪些 invariant 是 required，避免一刀切。短文档不强求 self-check，无 refusal 内容不强求 reframe | 我们的 linter 也需要。例如 `verification-gate/SKILL.md`（偏工程）和 `persona/SKILL.md`（偏 voice）的 required 集不同 | ~2h（和 #1 一起实现） |
| 8 | **Placeholder Penalty** | `PLACEHOLDER_RE` 检测 `<FIXME>` / `[TODO]` / `???` / `TBD` / `tk tk`，防止"通过插骨架通过审计"。quote-span 抑制让文档引用这些词不被误判 | linter 必配。我们现在 plan_template.md 禁止 placeholder 是靠自觉，加个 regex 就是物理级拦截 | ~30min |
| 9 | **Negator + Quote Guard (regex-linter 关键 sanity)** | `_has_negator_context()` 同行有 `does not/never/refuse` 时不计数；`_match_inside_quotes()` 引号里的违规示例不计数 | 我们若做 linter，这是必抄的。踩坑经验：Draft 1 把 blacklist 当例子反被抓，就是因为缺这个 guard | ~1h（和 #1 一起） |
| 10 | **Cue + Example + Rationale — 三层强制** | 任何模糊规则都必须 cue（语言信号）+ example（2-4 个含负例）+ rationale（1-2 句抽象原则）。单独任两层都不够：cue+example 不能泛化，example+rationale 不能识别触发点 | 我们 `rationalization-immunity.md` 有 cue+example 但 rationale 不全。一次性补齐所有 12 条的 rationale | ~1.5h |

### P2 — Reference Only (4 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| Anti-slop 1-to-1 Rewriter (fix.py TIER1_REPLACEMENTS) | `delve`→`cover`, `utilize`→`use`, `leverage`→`use`, `multifaceted`→`broad` 等 40+ 词典 | 我们写中文，这个词典不直接适用。但思路（自动修可 1-to-1 的、插 FIXME 留人工修判断题）值得留个印子 |
| XML Namespace Hierarchy (primitive 01) | 全 prompt 包在 `{role}` / `{default_stance}` / `{refusal_handling}` 嵌套 XML 块里，深度 ≤ 3 | 我们主要用 markdown + `<critical>`，迁到 XML 成本太高收益不明。保留观察，若后续要做 prompt diff/patch 才切 |
| Four-Tier Verdict (THIN/POOR/BORDERLINE/GOOD) | 不是简单 pass/fail，而是 doc 长度 + 分数联合分档。THIN 表示太短无法审计，直接退出 | 实现 linter 时再决定，不是独立模式 |
| 源锚定要求 (每条 invariant 必指 source:L###) | 每条规则必须在 Opus 4.7 源文里有明确行号 evidence | 对我们意义有限：我们没有一个 1408 行的"正确"源。但可退化为"每条规则必须指向一次 incident / 一个 commit hash / 一个 experience.jsonl 条目" |

## Comparison Matrix

| Capability | opus-mind impl | Orchestrator impl | Gap | Action |
|-----------|---------------|------------------|-----|--------|
| CLAUDE.md/SKILL.md deterministic linter | 906 行 audit.py，11 invariants，regex + threshold，JSON output | 无。prompt-linter agent 是 LLM-based | **Large** | Steal (P0 #1) |
| Self-audit release gate | SKILL.md 必须通过 audit.py 6/6 | 无。7 个 skill 无任何结构化自审 | **Large** | Steal (P0 #2) |
| Reframe/jailbreak 元信号检测 | primitive 09：软化本身 = 拒绝触发 | rationalization-immunity 有列表无 meta-detector | **Medium** | Enhance (P0 #3) |
| Tier label vocabulary | 5 级明文：NEVER/SEVERE VIOLATION/HARD LIMIT/NON-NEGOTIABLE/ABSOLUTE + ALLCAPS enforcement | `<critical>` 一级，内部无分层 | **Medium** | Enhance (P0 #4) |
| High-stakes rule redundancy | 7-pass template，不同 framing | 同规则一般只出现 1-2 次 | **Medium** | Enhance (P0 #5) |
| Domain-aware required checks | has_tools/has_refusals/is_long 推断 required invariants | N/A（无 linter） | **Large** | Bundle w/ #1 |
| Placeholder penalty | `<FIXME>`/`[TODO]`/`???`/`TBD` regex | plan_template 禁用但靠自觉 | **Small** | Bundle w/ #1 |
| Negator + quote guard | `_has_negator_context` + `_QUOTE_SPAN_RE` | N/A | **Small** | Bundle w/ #1 |
| Prompt coverage check (user-side BOOST) | 10 slots × task_type impact_order | N/A | **Medium** | Steal (P1 #6) |

## Triple Validation Gate — P0 Patterns

| # | Pattern | Cross-domain reproduction | Generative power | Exclusivity | Score |
|---|---------|--------------------------|------------------|-------------|-------|
| 1 | Deterministic linter | **PASS**：superpowers 有 skill 评审 agent（LLM-based），anthropic/skills 有 skill-creator checklist，awesome-claude-skills 明确指出"无 prompt 工程 meta-skill"是市场空白 → regex 路线确实稀缺但结构相似 | **PASS**：能预测新 SKILL.md 会在哪些维度崩（例如直接粘贴 LLM 生成的 SKILL.md，hedge_density 通常 > 0.3 + number_density < 0.05，审计立即能指出） | **PASS**：核心技巧（negator guard + quote span + placeholder penalty + domain-aware required）不是"一般好工程"，是 regex linter 专属 sanity | 3/3 |
| 2 | Self-audit gate | **PASS**：pytest 的 `conftest.py` 测试框架自己的测试、linter 本身通过 lint 是标准做法，但**应用在 prompt 领域**是 opus-mind 独创 | **PASS**：预测任何"prompt 质量工具"若不自审，必然犯伪善错误（Draft 1 就是例证） | **PASS**：prompt 领域内独有 —— 我没见过其他 prompt-engineering tool 强制自审 | 3/3 |
| 3 | Reframe-as-signal | **PARTIAL**：心理学有"motivated reasoning"概念，Anthropic 自己的 Responsible Scaling 也有"reasoning about safety"章节，但"把自己的软化当成触发"是 Opus 4.7 独创表述 | **PASS**：给定任何 rationalization 列表，能预测模型会用哪条软化，Reframe 规则会卡住第一次软化 | **PASS**：独特。多数 jailbreak 防御是检测输入，这是检测"自己内部的解释转换" | 3/3 |
| 4 | Tier labels + numbers | **PASS**：安全工程有 severity labels（Critical/High/Medium/Low），航空有 Airworthiness Directives 分级，法律条文也分级。但 **ALLCAPS as enforcement handle** 是 prompt 领域独特发现 | **PASS**：预测无 label 的规则会被当成"建议"；无数字的 label 会被理由化为"这个算不算严重" | **PARTIAL**：分级是普遍做法，细节（ALLCAPS + 数字配对 + 有限词汇表）才是独有的 | 3/3（caveat: label 本身不独有） |
| 5 | Redundancy as feature | **PASS**：教学设计中的 spaced repetition，LLM 研究中的"lost in the middle"（Liu 2023）都说同一信息。Opus 4.7 的 7-pass 是最明确的工程化 | **PASS**：预测长 prompt 里只出现一次的规则在 mid-context 会被忽略 | **PASS**："不同 framing 而非 copy-paste"的要求是独有的 | 3/3 |

## Knowledge Irreplaceability Assessment

| Pattern | Pitfall | Judgment | Relationship | Hidden context | Failure memory | Unique behavior | Categories hit |
|---------|---------|----------|--------------|----------------|----------------|-----------------|----------------|
| 1 Linter | ✓ (Draft 1 反噬) | ✓ (threshold 选择) | — | ✓ (Opus 4.7 泄露源的权威性) | ✓ (自己的 fix --add 会留 FIXME) | — | 4 |
| 2 Self-audit gate | ✓ (伪善) | ✓ (何时 release) | — | — | ✓ (Draft 1 事件) | ✓ (强制 dogfood) | 4 |
| 3 Reframe signal | — | ✓ (何时停) | — | ✓ (Anthropic 内训经验) | — | ✓ (元检测) | 3 |
| 4 Tier labels | ✓ (label inflation) | ✓ (何时加 label) | — | ✓ (ALLCAPS 训练效应) | — | — | 3 |
| 5 Redundancy | ✓ (long-context 漏) | ✓ (哪些规则值得 7-pass) | — | ✓ (LLM attention bias) | — | — | 3 |

全部 P0 ≥ 3 categories hit → 都是 architectural insight 而非 commodity knowledge。

## Gaps Identified

| 维度 | 我们当前缺的 | 对应 opus-mind 能力 |
|------|-------------|-------------------|
| Security / Governance | Reframe 软化检测、系统化 tier vocabulary、Hierarchical override 明文 Tier 1-N | primitive 09/12 + pattern hard-tier-labels |
| Execution / Orchestration | skill_routing 未硬化成 "first-match-wins, stop at match" | SKILL.md 的 Routing 三条 ladder |
| Context / Budget | CLAUDE.md 没有跨语言抗漂移保证（中英混合 hedge 检测） | number_density / hedge_density / shape-level metrics |
| Failure / Recovery | 无 linter → 无 placeholder penalty / negator guard / quote guard | audit.py 的各种 suppression |
| Quality / Review | 唯一 prompt 质检是 prompt-linter LLM agent，不可重放 | audit.py + self-audit gate 的 deterministic 路线 |
| Memory / Learning | N/A — opus-mind 不涉及 | — |

## Adjacent Discoveries

1. **CL4R1T4S 项目 (elder-plinius)** — 泄露各模型系统提示的仓库。opus-mind 的全部"证据"都指向这个源。对我们偷师 prompt 工程技巧是金矿，值得单独一次 steal。
2. **anthropic/skills + skill-creator** — opus-mind 的 SKILL.md 骨架（YAML frontmatter、progressive disclosure 3 级、references/+scripts/+assets/ 分层）直接抄自这里。我们 `.claude/skills/` 的结构大体一致但不够严格。
3. **travisvn/awesome-claude-skills 的市场空白观察** — "zero dedicated prompt-engineering meta-skills"。即我们若实现 P0 #1，在 Claude 社区也是稀缺。
4. **Wei 2022 (CoT) / Shinn 2023 (Reflexion) / Zhou 2022 (Least-to-most)** — BOOST 推理层 3 槽（B8/B9/B10）的学术锚点。我们若做 BOOST 要引这些。
5. **结构性迁移的适用性** — 虽然 opus-mind 针对 system prompt，但 regex + threshold + domain inference + self-audit 的**骨架**也可套用到 plan_template.md 审计、commit message 规范审计、experience.jsonl 条目审计。

## Meta Insights

1. **Prompt 质量从手艺走向工程的分水岭是"可重放的 deterministic 审计"**。LLM-as-judge 方案看似先进，但不可复现、贵、且有"judge 和 writer 是同一个模型"的循环问题。opus-mind 的 regex 路线一旦跑通，CI 里 < 1 秒跑完，commit hook 里没感知，这才能变成习惯。

2. **伪善防御是严肃 prompt 工具的第一准入门槛**。Draft 1 用 blacklist 做例子反被自己抓，是 opus-mind 整个项目的成立时刻 —— 它证明这套 invariants 真的有侦查力。任何声称"教人写好 prompt"的 skill，如果自己写得不好就不配发布。我们 7 个 skill 现在全部没跑过这种自审，这是一笔欠账。

3. **物理级拦截（regex hook）>> prompt 级劝告（please don't）**。我们 CLAUDE.md 里大量"don't do X"、"never do Y"的条文，真正起作用的是那几个 hook（block-protect、dispatch-gate）。把 linter 挂到 pre-commit / pre-write 钩子才是终态，写再多自律规则都不如一个拒绝写入的 script。

4. **源锚定是反通货膨胀的最强机制**。opus-mind 每条 invariant 必指 source:L###，这逼他们只接受能在 Opus 4.7 源文里找到证据的规则 —— 自动阻止"我觉得这样好"式功能膨胀。迁到我们：每条 Gate Function 也应该指向一次真实 incident / 一个 commit hash / 一条 experience 记录。没有来源的规则不收录。

5. **Prompt 可能是目前唯一能做 "AST-level 分析" 的自然语言产物**。因为 prompt 是工程产物、有边界、有风格 expectations，所以 regex 这种低级工具在其他文本里无效，在 prompt 里却能达到 6/11 准确率。这是一个少有的"文本 + 强约束"领域。
