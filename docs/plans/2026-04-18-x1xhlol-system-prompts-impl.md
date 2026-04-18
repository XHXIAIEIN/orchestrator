# Plan: x1xhlol System Prompts Steal — P0 Pattern Implementation

## Goal

将 R81 偷师报告中 5 个 P0 模式全部落地到对应配置文件，并通过 grep 验证每处改动已写入、不破坏现有 gate function 文字、plan_template 格式合法。

## Context

- 来源：R81 调查 30+ 商业 AI 工具系统提示词，识别出 5 个 P0 必偷模式
- 目标文件均为 markdown prompt / skill 文件，不涉及运行时代码
- 所有改动为纯追加或独立小节插入，无需删除现有内容
- 主仓路径：`D:/Users/Administrator/Documents/GitHub/orchestrator`（下称 `$REPO`）

## ASSUMPTIONS

1. **`voice.md` 路径**：报告指 `voice.md`，但 repo 中找到的路径是 `SOUL/examples/orchestrator-butler/voice.md`。计划按此路径操作；若有其他 voice.md 实例，owner 自行决定是否同步。
2. **`<think>` 工具可用性**：Pattern 3 在 CLAUDE.md 加 Think Triggers 小节，假设当前运行环境支持延伸思考（extended thinking）。若模型不支持 `<think>` 工具调用，触发列表退化为"强制停顿检查点"——仍然有用，owner 确认后可删除工具调用语法。
3. **Phase Gate 产物路径**：Pattern 4 约定 `.phase-gate/<from>-to-<to>.md`，路径相对于当前项目根。owner 可能希望改为 `.claude/phase-gates/`——计划按 `.phase-gate/` 实施，如需迁移在 step 后单独处理。
4. **Two-Stage Prompt 试点范围**：Pattern 5 仅试点 steal skill，不拆分其他 skill。后续是否推广留给 owner 决定。
5. **skill_routing.md softmax 集成方式**：新增 softmax 分类段作为"前置判断块"置于 decision tree 之上，不修改 decision tree 本身结构。

## File Map

- `D:/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/skill_routing.md` — Modify (Pattern 1: 新增 Soft Probability Classifier 前置段)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/SOUL/examples/orchestrator-butler/voice.md` — Modify (Pattern 2: 追加 Verbosity Dual-track 小节; Pattern P1-1: Example-driven verbosity 示例; Pattern P1-2: Anti-sycophancy 禁用词)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/CLAUDE.md` — Modify (Pattern 3: 新增 Think Triggers 小节; Pattern P1-3: Contract + Edge Cases 前置规范)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/plan_template.md` — Modify (Pattern 4: 追加 Phase Gate Contract Document 规范)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/steal/SKILL.md` — Modify (Pattern 5: 抽离 target-type 判断为独立 mini-prompt 段，标注 Haiku 可运行)

## Steps

### Phase 1 — Pattern 1: Soft Probability Mode Classifier

**1.** 读取 `$REPO/SOUL/public/prompts/skill_routing.md` 完整内容，确认文件当前无 softmax/probability 字样
→ verify: `grep -n "softmax\|probability\|confidence" "$REPO/SOUL/public/prompts/skill_routing.md"` 应返回空

**2.** 在 `$REPO/SOUL/public/prompts/skill_routing.md` 的 `## How You Work` 标题**前**插入以下新段落（不修改 Decision Tree 部分）：

```markdown
## Intent Probability Pre-filter

Before entering the Decision Tree, score the incoming instruction on three dimensions and produce a JSON confidence distribution (values sum to 1.0):

```json
{"do": 0.0, "spec": 0.0, "chat": 0.0}
```

**Rules**:
- Default bias toward `do` — when ambiguous, do > spec > chat
- `spec` requires at least one explicit keyword: "design", "architecture", "plan", "spec", "should we", "how would you"
- `chat` requires zero action intent: pure questions, history queries, explanations with no deliverable
- **Threshold**: if any dimension ≥ 0.6 → route directly, no clarification
- **Ambiguity trigger**: if top two dimensions are both ≥ 0.3 → ask one clarifying question before routing
- Emit the JSON in a `<routing>` tag in your internal monologue (not shown to user); then proceed with the winning route

**Examples**:
| Instruction | Distribution | Action |
|---|---|---|
| "refactor auth module" | `{do:0.85, spec:0.10, chat:0.05}` | Route to do directly |
| "should we use OAuth or API key?" | `{do:0.15, spec:0.70, chat:0.15}` | Route to spec |
| "how does this file work?" | `{do:0.05, spec:0.05, chat:0.90}` | Route to chat |
| "add auth with some kind of token" | `{do:0.45, spec:0.45, chat:0.10}` | Ask: "Implement directly or produce a design spec first?" |
```

→ verify: `grep -n "Intent Probability Pre-filter" "$REPO/SOUL/public/prompts/skill_routing.md"` 应输出包含该标题的行

---

### Phase 2 — Pattern 2: Verbosity Dual-track

**3.** 读取 `$REPO/SOUL/examples/orchestrator-butler/voice.md` 完整内容
→ verify: Read tool 成功返回文件内容，行数 > 0

**4.** 在 `$REPO/SOUL/examples/orchestrator-butler/voice.md` 末尾追加以下小节（保留原文件所有内容不变）：

```markdown
## Verbosity Dual-track

These two rules are **independent** — one governs code, one governs conversation. Do not let "be concise" bleed into code naming.

### Code: HIGH-VERBOSITY
- Variable names: semantic and full-length. `generateDateString` not `genYmd`. `numSuccessfulRequests` not `n`. `temporaryBuffer` not `tmp`. `result` not `res`.
- Function names: verb + subject + qualifier. `fetchUserProfileById` not `getUser`.
- No single-letter variables outside loop indices (`i`, `j` only in `for` loops).

### Conversation: LOW-VERBOSITY
- No `Summary:` or `Overview:` header before answers.
- No "First, let me explain..." lead-ins.
- No recap of what you just did at the end of a response.
- Length matches complexity: a yes/no question gets yes/no + one-line reason, not three paragraphs.

**Anti-pattern example** (banned):
> User: "4 + 4?"
> Bad: "Sure! Let me calculate that for you. The answer is 8. Is there anything else you'd like to know?"
> Good: "8"
```

→ verify: `grep -n "Verbosity Dual-track" "$REPO/SOUL/examples/orchestrator-butler/voice.md"` 应输出含该标题的行

**5.** 在 `$REPO/SOUL/examples/orchestrator-butler/voice.md` 的 `## Verbosity Dual-track` 段之后追加 Anti-sycophancy 禁用词小节：
- depends on: step 4

```markdown
## Anti-Sycophancy Banned Words

Do NOT start any response with the following words or phrases (enforced, not "preferred"):

- "Great question!"
- "That's a fascinating idea"
- "Excellent point"
- "Absolutely!"
- "Certainly!"
- "Of course!"
- "Sure!"
- "Good thinking"
- Any variant of "I love that you asked this"

**Rule**: if your drafted first sentence contains any of the above, delete it and start with the actual answer.
```

→ verify: `grep -n "Anti-Sycophancy" "$REPO/SOUL/examples/orchestrator-butler/voice.md"` 应输出含该标题的行

---

### Phase 3 — Pattern 3: Think Triggers

**6.** 读取 `$REPO/CLAUDE.md` 完整内容，定位 `### Goal-Driven Execution` 小节的结束位置（通常是下一个 `###` 标题前）
→ verify: Read tool 返回文件内容，`grep -n "Goal-Driven Execution" "$REPO/CLAUDE.md"` 输出行号

**7.** 在 `$REPO/CLAUDE.md` 的 `### Goal-Driven Execution` 小节**之后**、`### Context Management` 小节**之前**插入新小节：
- depends on: step 6

```markdown
### Think Triggers

At these 8 checkpoints, **stop and explicitly reason** before proceeding (use extended thinking if available; otherwise write out a brief reasoning block in your response):

1. **Before any git branch/checkout decision** — confirm which branch should receive the change and why
2. **Before deleting or replacing a file >50 LOC** — verify no live references exist
3. **Before crossing a module boundary** (touching code in a package you did not enter this task to modify) — confirm scope is still correct
4. **Before switching from exploration to first write** — state the plan in one sentence; if you can't, keep exploring
5. **Before declaring any multi-step task complete** — enumerate each acceptance criterion and its evidence
6. **After 3 consecutive failed attempts at the same fix** — stop, write down what you've tried and why each failed, then pick a different approach
7. **When resuming a task after a session break** — re-read the last 3 tool outputs and state the current hypothesis before taking action
8. **When a command returns unexpected output** (not the error/success you predicted) — pause, re-read the command and output, then diagnose before retrying
```

→ verify: `grep -n "Think Triggers" "$REPO/CLAUDE.md"` 应输出含该标题的行

---

### Phase 4 — Pattern 4: Phase Gate Contract Document

**8.** 读取 `$REPO/SOUL/public/prompts/plan_template.md` 完整内容，确认末尾没有 `Phase Gate Contract` 字样
→ verify: `grep -n "Phase Gate Contract" "$REPO/SOUL/public/prompts/plan_template.md"` 应返回空

**9.** 在 `$REPO/SOUL/public/prompts/plan_template.md` 末尾追加以下章节：
- depends on: step 8

```markdown
## Phase Gate Contract Document

When a plan crosses a phase boundary (Spec → Plan, Plan → Implement, Implement → Verify, or any custom phase), the transitioning agent **must** produce a contract file before the next phase begins.

### Contract File Convention

- Path: `.phase-gate/<from-phase>-to-<to-phase>.md` (relative to project root)
- Example: `.phase-gate/plan-to-implement.md`
- Created by: the agent completing the **outgoing** phase
- Read by: the agent starting the **incoming** phase (mandatory, not optional)

### Contract File Template

```markdown
# Phase Gate: {from} → {to}

**Date**: {YYYY-MM-DD}
**Plan reference**: {path/to/plan.md}

## Assumptions
<!-- List every assumption made in {from} phase that the {to} phase will rely on -->
- [ ] {Assumption 1}
- [ ] {Assumption 2}

## Interface Contracts
<!-- APIs, file formats, data shapes, environment variables agreed upon -->
| Name | Type | Value / Shape | Owner |
|------|------|---------------|-------|
| {interface} | {api\|file\|env\|type} | {description} | {who produces it} |

## Verification Points
<!-- How does the {to} phase know it succeeded? -->
- [ ] {Criterion 1} → checked by: {command or manual step}
- [ ] {Criterion 2} → checked by: {command or manual step}

## Open Questions
<!-- Unresolved items deferred to {to} phase — must be resolved before phase ends -->
- [ ] {Question} — assigned to: {owner\|agent}
```

### Gate Rules

1. **No contract = no phase transition.** If the contract file does not exist at the start of the incoming phase, create it before writing any code or making any decisions.
2. **Contract conflicts with plan = STOP.** If the contract contradicts the current plan, surface the conflict to the owner before proceeding.
3. **Contract is a living document** during the phase — update it when assumptions are validated or invalidated. Mark resolved items with `[x]`.
```

→ verify: `grep -n "Phase Gate Contract Document" "$REPO/SOUL/public/prompts/plan_template.md"` 应输出含该标题的行

---

### Phase 5 — Pattern 5: Two-Stage Prompt Architecture (steal skill 试点)

**10.** 读取 `$REPO/.claude/skills/steal/SKILL.md` 中 `### Adaptive Execution by Target Type` 以及 `**Determine target type**` 段落的完整内容（约第 27–90 行）
→ verify: Read tool 返回该文件，`grep -n "Determine target type" "$REPO/.claude/skills/steal/SKILL.md"` 输出行号

**11.** 在 `$REPO/.claude/skills/steal/SKILL.md` 的 Pre-flight 第 4 步（`**Determine target type**`）的 table 之后，插入以下 mini-prompt 框：
- depends on: step 10

```markdown
#### Mini-Prompt: Target Type Classifier (Haiku-compatible)

> This block is a self-contained intent router. It can be run by a lighter model (Haiku / Sonnet) before the full steal workflow loads. Input: the user's message or target URL. Output: one of {framework, self-evolving, specific-module, industry-survey, skill-prompt} with a 1-sentence justification.

```
SYSTEM: You classify steal (偷师) targets into 5 categories. Return JSON only.
Categories: framework | self-evolving | specific-module | industry-survey | skill-prompt
Rules:
- framework: repo with architecture, multiple layers, agent coordination
- self-evolving: repo whose primary value is improving itself (eval loops, memory updates)
- specific-module: single file or narrow feature (<500 LOC focus)
- industry-survey: collection of projects or compiled analysis (lists, stars, comparisons)
- skill-prompt: prompt collection, system prompt library, SKILL.md files, agent instructions

USER: {target_description}

RESPONSE FORMAT:
{"type": "<category>", "reason": "<one sentence>", "confidence": 0.0-1.0}
```

**Handoff**: After classification, pass `type` to the main steal workflow. The main workflow skips re-classification and enters `### Adaptive Execution by Target Type` directly with the resolved type.
```

→ verify: `grep -n "Mini-Prompt: Target Type Classifier" "$REPO/.claude/skills/steal/SKILL.md"` 应输出含该标题的行

---

### Phase 6 — Verification

**12.** 验证所有 5 个 pattern 的写入标记均存在，无一遗漏
→ verify: 运行以下命令，每条应返回至少一行非空输出：
```bash
grep -l "Intent Probability Pre-filter" "$REPO/SOUL/public/prompts/skill_routing.md"
grep -l "Verbosity Dual-track" "$REPO/SOUL/examples/orchestrator-butler/voice.md"
grep -l "Anti-Sycophancy" "$REPO/SOUL/examples/orchestrator-butler/voice.md"
grep -l "Think Triggers" "$REPO/CLAUDE.md"
grep -l "Phase Gate Contract Document" "$REPO/SOUL/public/prompts/plan_template.md"
grep -l "Mini-Prompt: Target Type Classifier" "$REPO/.claude/skills/steal/SKILL.md"
```

**13.** 确认 `$REPO/CLAUDE.md` 的 Gate Functions 原有内容（`Gate: Delete / Replace File`、`Gate: Git Reset / Restore / Checkout`）未被修改
→ verify: `grep -c "Gate: Delete / Replace File" "$REPO/CLAUDE.md"` 应输出 `1`；`grep -c "Gate: Git Reset" "$REPO/CLAUDE.md"` 应输出 `1`
- depends on: step 7

**14.** 确认 `$REPO/SOUL/public/prompts/plan_template.md` 原有 `## Phase Gates` 小节未被覆盖（只追加，不替换）
→ verify: `grep -c "## Phase Gates" "$REPO/SOUL/public/prompts/plan_template.md"` 应输出 `1`（原有的）；`grep -c "Phase Gate Contract Document" "$REPO/SOUL/public/prompts/plan_template.md"` 应输出 `1`（新增的）
- depends on: step 9

---

### Phase 7 — Commit

**15.** 用 `git diff --stat` 在主仓路径确认改动涉及文件与 File Map 一致，无额外文件
→ verify: `git -C "$REPO" diff --stat` 输出仅包含上述 5 个文件路径

**16.** Stage 5 个目标文件并提交
- depends on: step 15

```bash
git -C "$REPO" add \
  SOUL/public/prompts/skill_routing.md \
  SOUL/examples/orchestrator-butler/voice.md \
  CLAUDE.md \
  SOUL/public/prompts/plan_template.md \
  .claude/skills/steal/SKILL.md
git -C "$REPO" commit -m "feat(prompts): port 5 P0 patterns from x1xhlol steal R81"
```

→ verify: `git -C "$REPO" log --oneline -1` 输出包含 `feat(prompts): port 5 P0 patterns`

--- PHASE GATE: Implement → Verify ---
[ ] Deliverable exists: 5 target files modified, grep markers present for each pattern
[ ] Acceptance criteria met: steps 12-14 all pass with expected output
[ ] No open questions: ASSUMPTIONS 1-5 已列出并由 owner 知晓
[ ] Owner review: not required (all changes are prompt/markdown files, fully reversible via git revert)

## Non-Goals

- 不修改任何 `.ts` / `.py` / `.json` 运行时代码
- 不实施 P1 模式（Amp Oracle 子代理、Two-level Autonomy 开关、hooks PostToolUse 验证）——留给下一 plan
- 不实施 P2 模式（Poke 6-part 分片、Dia ask:// 协议等）
- 不为每个模型版本维护独立 prompt 变体（Cursor 碎片化问题，明确避免）
- 不触碰 `docker-compose.yml`、`.env`、数据库 schema

## Rollback

所有改动为 markdown 文件追加/插入，无运行时影响。回滚方法：

```bash
git -C "$REPO" revert HEAD  # 撤销 step 16 的 commit
```

若需要部分回滚（只撤某个 pattern）：

```bash
git -C "$REPO" checkout HEAD~1 -- CLAUDE.md  # 仅恢复 CLAUDE.md
```

备份不需要额外步骤——git history 即是备份。

---

## Completion Log

| Phase | Commit | Note |
|---|---|---|
| 1 | 6c2c690 | Soft Probability Mode Classifier (R2 run 1) |
| 2 | 9777c87 | Verbosity Dual-track + Anti-Sycophancy (R2 run 1) |
| 3 | 9aef8bb | Think Triggers (R2 run 1) |
| 4 | d80e9b7 | Phase Gate Contract Document (R2 run 1) |
| 5 | 06da4e7 | Two-Stage Prompt Mini-Classifier (R2 run 1) |
| 6 | (no-op verify) | Phase 6 verification passed — all 6 markers present, gate functions intact (R2 run 2) |

### Goal 验证 stdout

```
=== Pattern 1: Intent Probability Pre-filter ===
PASS
=== Pattern 2a: Verbosity Dual-track ===
PASS
=== Pattern 2b: Anti-Sycophancy ===
PASS
=== Pattern 3: Think Triggers ===
PASS
=== Pattern 4: Phase Gate Contract Document ===
PASS
=== Pattern 5: Mini-Prompt: Target Type Classifier ===
PASS
=== Step 13: Gate Functions 原有内容完整性 ===
Gate: Delete / Replace File count: 1
Gate: Git Reset count: 1
=== Step 14: plan_template.md 原有 ## Phase Gates 段 + 新增段 ===
## Phase Gates count: 1
Phase Gate Contract Document count: 1
=== Goal 验证: diff stat (clean，无未提交改动) ===
(empty — working tree clean)
=== 各文件最后修改 commit ===
SOUL/public/prompts/skill_routing.md → 6c2c690
SOUL/examples/orchestrator-butler/voice.md → 9777c87
CLAUDE.md → 9aef8bb
SOUL/public/prompts/plan_template.md → d80e9b7
.claude/skills/steal/SKILL.md → 06da4e7
```

### Deviations (plan vs actual)

- Phase 7 originally specified a single aggregate commit ("feat(prompts): port 5 P0 patterns from x1xhlol steal R81"). Phase 1-5 already landed as individual atomic commits in the prior session, so Phase 7 collapsed into this Completion Log commit.
- None otherwise.
