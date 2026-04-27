# Worktree Steal Pipeline Closure — 11 topics to main

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前 11 个 `steal/<topic>` worktree 从 "已偷师 / 已有 impl plan 但未实施" 状态推到 "实施完、功能验证通、合回本地 main、推 origin/main、worktree+分支回收"，并保留 archive tag。

**Architecture:** 两档流水线：
1. **Batch A（已实施 DONE，4 个）:** `eureka` / `tlotp-monorepo` / `x1xhlol-system-prompts` / `r38-sandbox-retro`。走 "功能 smoke 验证 → archive tag → `--no-ff` merge → worktree 回收"。
2. **Batch B（IMPL 待执行，7 个）:** `andrej-karpathy-skills` / `flux-enchanted` / `generic-agent` / `loki-skills-cli` / `memto` / `millhouse` / `prompt-language-coach`。每个 topic 派 fresh subagent 以 `superpowers:subagent-driven-development` 执行 `<worktree>/docs/plans/2026-04-18-<topic>-impl.md`（完整 plan 已在各自 worktree 里），subagent 完成 → 主人在 Phase C Owner Review gate 逐个 review → 进入与 Batch A 相同的下游。

Merge 步骤遵循仓库惯例：`merge: steal/<topic> — <one-line subject>`，`--no-ff`，每 topic 独立 commit。Push 是独立 gate，主人不说 "push" 不推。

**Tech Stack:** git worktree/merge/branch/tag、bash for-loop、`superpowers:subagent-driven-development`（Batch B impl 执行）、各 topic 自带的验证命令（smoke test / skill 手动调用）、`.claude/boot.md` 编译校验。

**Scope — 本 plan 覆盖的 11 个 topic:**

| # | Topic | Worktree | Batch |
|---|-------|----------|-------|
| 1 | `andrej-karpathy-skills` | `.claude/worktrees/steal-andrej-karpathy-skills` | B (IMPL) |
| 2 | `eureka` | `.claude/worktrees/steal-eureka` | A (DONE) |
| 3 | `flux-enchanted` | `.claude/worktrees/steal-flux-enchanted` | B (IMPL) |
| 4 | `generic-agent` | `.claude/worktrees/steal-generic-agent` | B (IMPL) |
| 5 | `loki-skills-cli` | `.claude/worktrees/steal-loki-skills-cli` | B (IMPL) |
| 6 | `memto` | `.claude/worktrees/steal-memto` | B (IMPL) |
| 7 | `millhouse` | `.claude/worktrees/steal-millhouse` | B (IMPL) |
| 8 | `prompt-language-coach` | `.claude/worktrees/steal-prompt-language-coach` | B (IMPL) |
| 9 | `r38-sandbox-retro` | `.claude/worktrees/steal-r38-sandbox-retro` | A (DONE) |
| 10 | `tlotp-monorepo` | `.claude/worktrees/steal-tlotp-monorepo` | A (DONE) |
| 11 | `x1xhlol-system-prompts` | `.claude/worktrees/steal-x1xhlol-system-prompts` | A (DONE) |

**Out of scope（明确不碰）:**
- `feature/r83-trust-tagging`（独立功能分支，非 steal 流水线）
- `refactor/worktree-gate-hardening`
- 4 个 `worktree-agent-*`（agent 临时 worktree）
- `steal/*-old` 归档分支（保留）
- 任何已存在的 `archive/steal-*-*` tag
- 主工作树未跟踪文件

**Assumptions:**
- `ASSUMPTION`: Batch A 4 个 topic 的 "已完成" 判据是 "commits ahead main ≥ 4 且含 `feat(...)` / `Phase N` 类 commit + 末尾含 `docs(plan): ... completion log` 或等价"。Phase B1 逐个再校验一次。
- `ASSUMPTION`: Batch B 7 个 topic 的 impl plan (`docs/plans/2026-04-18-<topic>-impl.md`) 已在各自 worktree 内，且符合 `plan_template.md` 格式；Phase C 之前先 Read 校验文件存在且非 placeholder。
- `ASSUMPTION`: 合入顺序按字母序（与上一轮 rescue-steal 保持一致），11 个 topic 之间无代码依赖——每 topic 独立 add 文件，无跨 topic 改写。Phase D 开始前 Task D0 会做 pairwise dry-run merge 校验。
- `ASSUMPTION`: Batch B 用 subagent-driven 执行、每 topic 一个独立 subagent session，避免跨 topic 污染上下文。subagent 被派时通过 prompt 携带 `[STEAL]` tag 和 `isolation: "worktree"`（`dispatch-gate.sh` 要求）。
- `ASSUMPTION`: 遇到 Batch B 某个 topic 实施失败（测试不过 / impl plan 本身有缺陷），**该 topic 退出本轮合并**，进入下一个 topic；最终 Phase D 只合入成功 topic，失败的留在自己 worktree 等主人二轮处理。
- `ASSUMPTION`: 推 origin/main 是独立 gate，Phase E 必须主人明确说 `push` 或等价才执行。
- `ASSUMPTION`: 回收阶段先给每 topic 打 `archive/steal-<topic>-20260419` tag 保底，再删分支与 worktree。不创建 `-old` 第二代。

---

## File Map

**本 plan 分两层：**
- **Meta-plan 本身**（本文件）：不改任何源码。
- **各 topic impl 交付**（Batch B 7 个）：由 subagent 执行 topic 自带的 impl plan 时产生——文件清单在各 topic 的 `2026-04-18-<topic>-impl.md` 的 File Map 里，meta-plan 不复述。

| 状态类别 | 目标 | 变更 |
|---|---|---|
| 文档 | `docs/superpowers/plans/2026-04-19-worktree-pipeline-closure.md` | 创建（本文件） |
| 分支（Batch B 执行结果） | `steal/<7 impl topic>` | 累积 feat commits（各自 impl plan 定义） |
| 分支 | `main` | Phase D 追加 ≤11 个 `--no-ff` merge commit（按 Batch A/B 成功数量） |
| Tag | `archive/steal-<topic>-20260419` | 每个成功合入的 topic 一个 |
| Worktree | `.claude/worktrees/steal-<topic>` | 合入后 `git worktree remove` |
| 分支 | `steal/<topic>` | 合入后 `git branch -D`（tag 已保底） |
| Remote | `origin/main` | Phase E 主人授权后 push |

---

## Phase A — Pre-flight Audit

**目的：在动任何 ref 前，重跑一次分类校验，并确认各 impl plan 文件就位。**

### Task A1：主工作树位置与清洁度

**Files:** none（只读 git）

- [ ] **Step 1：主工作树在 main 且无 staged 改动**

  Run:
  ```bash
  git -C D:/Users/Administrator/Documents/GitHub/orchestrator rev-parse --abbrev-ref HEAD
  git -C D:/Users/Administrator/Documents/GitHub/orchestrator diff --cached --name-only
  ```
  Expected：第一行输出 `main`；第二行空。若非 main 或有 staged → STOP 并询问主人。

- [ ] **Step 2：记录主工作树未跟踪文件基线**

  Run:
  ```bash
  git -C D:/Users/Administrator/Documents/GitHub/orchestrator status --porcelain | grep '^??' | sort
  ```
  Expected：输出记录到 session 里，作为 Phase G 完成后的对比基线。允许存在的 untracked：`.claude/bin/`、`.claude/skills/claude-at/`、`SOUL/public/prompts/session_handoff_rescue_compare.md`、`SOUL/public/prompts/steal_pilot_dispatch.md`、`docs/superpowers/plans/2026-04-19-rescue-steal-main-landing.md`（前一轮）、本 plan 文件、`plans/`。

- [ ] **Step 3：当前 main HEAD 与 origin/main 差距快照**

  Run:
  ```bash
  git -C D:/Users/Administrator/Documents/GitHub/orchestrator fetch origin main
  git -C D:/Users/Administrator/Documents/GitHub/orchestrator log --oneline origin/main..main
  git -C D:/Users/Administrator/Documents/GitHub/orchestrator log --oneline main..origin/main
  ```
  Expected：前者可能非空（主人已合过前一轮 rescue-steal 的 7 topic），后者为空。若 `main..origin/main` 非空 → STOP 询问主人是否先 pull。

### Task A2：11 个 worktree 清洁度 + commits-ahead 分类

**Files:** none

- [ ] **Step 1：逐 worktree 查 `git status` + `main..HEAD`**

  Run：
  ```bash
  cd D:/Users/Administrator/Documents/GitHub/orchestrator
  for T in andrej-karpathy-skills eureka flux-enchanted generic-agent loki-skills-cli memto millhouse prompt-language-coach r38-sandbox-retro tlotp-monorepo x1xhlol-system-prompts; do
    WT=".claude/worktrees/steal-$T"
    [ -d "$WT" ] || { printf "%-30s MISSING worktree\n" "$T"; continue; }
    D=$(git -C "$WT" status --porcelain | wc -l)
    AHEAD=$(git -C "$WT" log --oneline main..HEAD | wc -l)
    LAST=$(git -C "$WT" log -1 --format='%s' HEAD)
    printf "%-30s dirty=%-2s ahead=%-2s last=%s\n" "$T" "$D" "$AHEAD" "${LAST:0:70}"
  done
  ```
  Expected：11 行全部 `dirty=0`；`ahead` 列参照下表预期：

  | Topic | 预期 ahead | 预期 Batch |
  |-------|-----------|-----------|
  | andrej-karpathy-skills | 2 | B |
  | eureka | ≥7 | A |
  | flux-enchanted | 2 | B |
  | generic-agent | 2 | B |
  | loki-skills-cli | 2 | B |
  | memto | 2 | B |
  | millhouse | 3 | B |
  | prompt-language-coach | 2 | B |
  | r38-sandbox-retro | ≥4 | A |
  | tlotp-monorepo | ≥8 | A |
  | x1xhlol-system-prompts | ≥8 | A |

  任何 `dirty≠0` → STOP，不碰该 topic（进入 "Rollback Guide"）。任何 `ahead` 实际数偏离预期 ±1 → 仍继续，但把实际值写进 session 作为 A3 分类依据。

- [ ] **Step 2：分类写入决策表**

  根据 Step 1 实际输出，决定每个 topic 属于：
  - `BATCH_A_DONE`（impl 已完成，只等 merge）
  - `BATCH_B_IMPL_PENDING`（需要 subagent 跑 impl）
  - `SKIP`（dirty 或异常，本轮不合）

  把这三组列表记录到 session，后面 Task 引用。

### Task A3：Batch A 4 topic 的 "完成" 证据验证

**Files:** none（只读）

- [ ] **Step 1：确认每个 Batch A topic 有 completion 类 commit**

  Run：
  ```bash
  for T in eureka r38-sandbox-retro tlotp-monorepo x1xhlol-system-prompts; do
    WT=".claude/worktrees/steal-$T"
    echo "=== $T ==="
    git -C "$WT" log --oneline main..HEAD | grep -iE "completion|phase [0-9]|section [0-9]|feat\(|refactor\(|smoke" | head -6
  done
  ```
  Expected：每个 topic 至少 2 行命中。若某 topic 0 命中 → 降级为 `BATCH_B_IMPL_PENDING`，进入 Phase C。

- [ ] **Step 2：Batch A topic 各自 impl plan 勾选状态（抽样）**

  Run：
  ```bash
  for T in eureka r38-sandbox-retro tlotp-monorepo x1xhlol-system-prompts; do
    WT=".claude/worktrees/steal-$T"
    PLAN="$WT/docs/plans/2026-04-18-$T-impl.md"
    [ -f "$PLAN" ] || { echo "$T: NO PLAN"; continue; }
    DONE=$(grep -c '^- \[x\]' "$PLAN")
    OPEN=$(grep -c '^- \[ \]' "$PLAN")
    printf "%-28s done=%s open=%s\n" "$T" "$DONE" "$OPEN"
  done
  ```
  Expected：`done ≥ open × 3` 视为真 done；若 `open > done` → 该 topic 降级为 Batch B。记录实际值。

### Task A4：Batch B 7 topic 的 impl plan 文件完整性

**Files:** none（只读）

- [ ] **Step 1：逐 topic Read 首 40 行 + 末 20 行**

  对以下 7 topic，在 Bash 里 `head -40` + `tail -20` 各自的 `<WT>/docs/plans/2026-04-18-<topic>-impl.md`：
  - `andrej-karpathy-skills` / `flux-enchanted` / `generic-agent` / `loki-skills-cli` / `memto` / `millhouse` / `prompt-language-coach`

  Run：
  ```bash
  for T in andrej-karpathy-skills flux-enchanted generic-agent loki-skills-cli memto millhouse prompt-language-coach; do
    PLAN=".claude/worktrees/steal-$T/docs/plans/2026-04-18-$T-impl.md"
    echo "=== $T ==="
    [ -f "$PLAN" ] || { echo "MISSING"; continue; }
    head -40 "$PLAN"
    echo "..."
    tail -20 "$PLAN"
    echo
  done
  ```
  Expected：每个文件都有 `**Goal:**`、`**Architecture:**`、`## Phase`、`## Self-Review` 等 plan_template 结构；末尾无 `TBD` / `TODO`。若某 topic 的 plan 含 placeholder → 标记该 topic 为 `BATCH_B_NEEDS_REPLAN`，Phase C 对该 topic 先派 `superpowers:writing-plans` subagent 重写 plan 再执行。

- [ ] **Step 2：各 topic steal report 就位**

  Run：
  ```bash
  for T in andrej-karpathy-skills flux-enchanted generic-agent loki-skills-cli memto millhouse prompt-language-coach; do
    WT=".claude/worktrees/steal-$T"
    FOUND=$(git -C "$WT" log --oneline main..HEAD --name-only | grep -iE "docs/steal/.*$T.*\.md|docs/steal/R[0-9]+.*$T" | head -1)
    printf "%-28s report=%s\n" "$T" "${FOUND:-MISSING}"
  done
  ```
  Expected：每 topic 至少一行 report 文件命中。若 `MISSING` → 标记为 `BATCH_B_NEEDS_REPORT`，Phase C 先派 `steal` skill subagent 补 steal report 再进 impl。

--- PHASE GATE: A → B ---
- [ ] Deliverable exists: Phase A 四个 Task 的 verify 输出都已记录
- [ ] Acceptance criteria met: 11 topic 分类决策表写入 session；Batch A 与 Batch B 两组人员确定；无 dirty worktree；无 pull 冲突待解
- [ ] No open questions: 无未确认的 MISSING / 异常 ahead 数
- [ ] Owner review: not required（仅只读审计）

---

## Phase B — Batch A 验证（已 DONE 4 topic 的 smoke test）

**目的：对 `eureka` / `r38-sandbox-retro` / `tlotp-monorepo` / `x1xhlol-system-prompts` 4 个 topic 各跑一轮功能 smoke，保证合入 main 后不炸。每 topic 一个 Task，每 Task 三步（verify impl artefact 存在 → run smoke → read output）。若某 topic smoke fail，标记 SKIP，进入 Phase D 时跳过。**

### Task B1：smoke — eureka（Phase 1-4 artefact + override log）

**Files:** none（只读各 artefact）

- [ ] **Step 1：artefact 存在校验**

  Run：
  ```bash
  WT=.claude/worktrees/steal-eureka
  ls "$WT/SOUL/public/schemas/artifact-frontmatter.md" \
     "$WT/SOUL/public/override-log.md" \
     "$WT/SOUL/public/prompts/plan_template.md"
  ```
  Expected：3 文件全存在。任何一条 `No such file` → 标记 `eureka` 为 SKIP。

- [ ] **Step 2：运行 eureka 自带 smoke**

  Run：
  ```bash
  cd .claude/worktrees/steal-eureka
  git log --oneline main..HEAD | grep -iE "smoke|phase 4"
  cd D:/Users/Administrator/Documents/GitHub/orchestrator
  ```
  Expected：至少一行 `smoke` 或 `Phase 4` commit 命中。若无 → 阅读 eureka impl plan Phase 4 提到的 smoke 命令并照跑；若 impl plan 无 smoke 定义 → SKIP，提醒主人人工验 eureka 再合。

- [ ] **Step 3：commit 记录完成**

  Run：`git -C .claude/worktrees/steal-eureka log -1 --format='%h %s'`
  Expected：最后一个 commit 是 `docs(plan): eureka — completion log`（或含 "completion"）。非此 commit → 把实际 subject 记录进 session，Phase D 的 merge subject 用此 subject 生成。

### Task B2：smoke — r38-sandbox-retro（Section 9/10 + retrospective）

**Files:** none

- [ ] **Step 1：artefact 存在校验**

  Run：
  ```bash
  WT=.claude/worktrees/steal-r38-sandbox-retro
  grep -c "^## Section 9" "$WT/docs/steal/R38-agent-eval-patterns.md" 2>/dev/null || echo 0
  grep -c "^## Section 10" "$WT/docs/steal/R38-agent-eval-patterns.md" 2>/dev/null || echo 0
  ```
  Expected：两行均 `1`（或 ≥1）。若 0 → SKIP。

- [ ] **Step 2：retrospective section 2 存在**

  Run：`grep -n "retrospective\|soften absolute" ".claude/worktrees/steal-r38-sandbox-retro/docs/steal/R38-agent-eval-patterns.md" | head -3`
  Expected：至少 1 行命中。0 行 → SKIP。

- [ ] **Step 3：commit 记录完成**

  Run：`git -C .claude/worktrees/steal-r38-sandbox-retro log -1 --format='%h %s'`
  Expected：记录到 session，供 Phase D merge subject 使用。

### Task B3：smoke — tlotp-monorepo（skill sections refactor + prompt-lint CI）

**Files:** none

- [ ] **Step 1：section 文件 5 个全存在**

  Run：
  ```bash
  WT=.claude/worktrees/steal-tlotp-monorepo
  ls "$WT/.claude/skills/steal/sections/"
  ```
  Expected：`01-preflight.md` / `02-deep-dive.md` / `03-extraction.md` / `04-output.md` / `05-index-update.md` 5 个文件。缺任何一个 → SKIP。

- [ ] **Step 2：steal/SKILL.md 使用 @import 引用 section**

  Run：`grep -n "^@import\|sections/" ".claude/worktrees/steal-tlotp-monorepo/.claude/skills/steal/SKILL.md" | head -8`
  Expected：至少 5 行命中（对应 5 个 section）。<5 → SKIP。

- [ ] **Step 3：prompt-lint workflow 就位**

  Run：`ls ".claude/worktrees/steal-tlotp-monorepo/.github/workflows/prompt-lint.yml"`
  Expected：文件存在。不存在 → SKIP。

- [ ] **Step 4：commit 记录完成**

  Run：`git -C .claude/worktrees/steal-tlotp-monorepo log -1 --format='%h %s'`
  Expected：记录到 session。

### Task B4：smoke — x1xhlol-system-prompts（Phase 2-5 prompts）

**Files:** none

- [ ] **Step 1：Phase 2/3/4/5 commit 全在**

  Run：
  ```bash
  git -C .claude/worktrees/steal-x1xhlol-system-prompts log --oneline main..HEAD | grep -cE "Phase [2-5]"
  ```
  Expected：≥4。<4 → SKIP。

- [ ] **Step 2：Voice.md / skill_routing.md 等 Phase 产物存在**

  Run：
  ```bash
  WT=.claude/worktrees/steal-x1xhlol-system-prompts
  ls "$WT/SOUL/examples/orchestrator-butler/voice.md" \
     "$WT/SOUL/public/prompts/plan_template.md" \
     "$WT/SOUL/public/prompts/skill_routing.md"
  ```
  Expected：3 文件都存在。缺任一 → SKIP。

- [ ] **Step 3：commit 记录完成**

  Run：`git -C .claude/worktrees/steal-x1xhlol-system-prompts log -1 --format='%h %s'`
  Expected：最后 commit subject 含 `completion log` 或 `Phase 5`。记录到 session。

--- PHASE GATE: B → C ---
- [ ] Deliverable exists: 4 个 Batch A topic 各自 Task 的 Step 全绿（或被标 SKIP）
- [ ] Acceptance criteria met: smoke 全过的 topic 计入 "ready to merge" 名单；SKIP 的 topic 记录在 session，不进 Phase D
- [ ] No open questions: 无 artefact missing 未决
- [ ] Owner review: not required（smoke 非决策）

---

## Phase C — Batch B 实施（7 个 topic subagent 逐个跑 impl plan）

**目的：Batch B 7 个 topic 各派一个 fresh subagent，在对应 worktree 里以 `superpowers:subagent-driven-development` 执行该 topic 的 `docs/plans/2026-04-18-<topic>-impl.md`。每 topic 执行完 → 主人在 Phase C 末的 Owner Review gate 逐个 review；subagent fail 的 topic 标记 SKIP，主体继续下一个，不阻塞其他 topic 的实施。**

**dispatch 合规性（`.claude/skills/steal/constraints/worktree-isolation.md` + `dispatch-gate.sh`）：**
- 每个 subagent prompt 必须以 `[STEAL]` 开头。
- Agent 工具调用时必须带 `isolation: "worktree"`。
- subagent 自述 "cd 到 `.claude/worktrees/steal-<topic>`" 并 `git branch --show-current` 返回 `steal/<topic>`。

### Task C1：subagent — andrej-karpathy-skills

**Files:** by subagent（遵循 `<worktree>/docs/plans/2026-04-18-andrej-karpathy-skills-impl.md` 的 File Map）

- [ ] **Step 1：派遣 subagent**

  Agent 工具调用（`subagent_type: "engineer"`，`isolation: "worktree"`）：
  - description: `[STEAL] impl andrej-karpathy-skills`
  - prompt（完整 self-contained）：

    ```
    [STEAL] 你在 D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-andrej-karpathy-skills（当前 branch steal/andrej-karpathy-skills）里执行 docs/plans/2026-04-18-andrej-karpathy-skills-impl.md。

    要求：
    1. 先 Read 这个 impl plan 完整内容，用 superpowers:subagent-driven-development 技能逐 task 推进。
    2. 每个 Phase Gate 达标前不要跨 Phase。
    3. 每完成一个可提交单元立刻 git commit（已是 steal 分支，无需 push）。
    4. 若遇到 plan 本身写错或 placeholder，停下来报告（不要自己拍脑袋改 plan）。
    5. 全部完成后，在 session 末尾报告：(a) 已 commit 的 sha 列表，(b) 验证命令实际输出摘要（smoke / test / build），(c) 未完成 task 清单（若有）。

    硬约束：
    - 不改 main 分支。
    - 不删除任何文件（需要替换的放 .trash/ 并报告）。
    - 不 push。
    - 若 impl plan 需要运行耗时 ≥5 分钟的任务（训练/build），先在报告里问主 session 是否跑。
    ```

- [ ] **Step 2：接收 subagent 报告，记录 commits / 验证摘要 / 未完成清单**

  Read subagent 返回的 final message，抽取三项内容到主 session 笔记。若 "未完成 task 清单" 非空 → 标记 `andrej-karpathy-skills` 为 SKIP，暂不进 Phase D。

- [ ] **Step 3：在主工作树抽查 subagent 产物**

  Run：
  ```bash
  git -C .claude/worktrees/steal-andrej-karpathy-skills log --oneline main..HEAD | head -10
  git -C .claude/worktrees/steal-andrej-karpathy-skills status --porcelain | head -5
  ```
  Expected：log 新增 commit ≥2；status 干净（无未提交）。若 status 不干净 → 标记 SKIP 并记录。

### Task C2：subagent — flux-enchanted

**Files:** by subagent（遵循 `<worktree>/docs/plans/2026-04-18-flux-enchanted-impl.md` 的 File Map）

- [ ] **Step 1：派遣 subagent**

  Agent 工具（`subagent_type: "engineer"`，`isolation: "worktree"`），prompt 与 Task C1 Step 1 完全同构，替换三处：
  - worktree 路径 → `.claude/worktrees/steal-flux-enchanted`
  - branch → `steal/flux-enchanted`
  - impl plan → `docs/plans/2026-04-18-flux-enchanted-impl.md`

- [ ] **Step 2：接收报告并记录**（同 Task C1 Step 2）

- [ ] **Step 3：抽查产物**（同 Task C1 Step 3，路径替换为 `flux-enchanted`）

### Task C3：subagent — generic-agent

**Files:** by subagent

- [ ] **Step 1：派遣 subagent**

  Agent 工具（`subagent_type: "engineer"`，`isolation: "worktree"`），prompt 同 Task C1 Step 1，替换三处：
  - worktree → `.claude/worktrees/steal-generic-agent`
  - branch → `steal/generic-agent`
  - impl plan → `docs/plans/2026-04-18-generic-agent-impl.md`

- [ ] **Step 2：接收报告并记录**（同 Task C1 Step 2）

- [ ] **Step 3：抽查产物**（同 Task C1 Step 3，路径替换）

### Task C4：subagent — loki-skills-cli

**Files:** by subagent

- [ ] **Step 1：派遣 subagent**

  Agent 工具（`subagent_type: "engineer"`，`isolation: "worktree"`），prompt 同 Task C1 Step 1，替换三处：
  - worktree → `.claude/worktrees/steal-loki-skills-cli`
  - branch → `steal/loki-skills-cli`
  - impl plan → `docs/plans/2026-04-18-loki-skills-cli-impl.md`

- [ ] **Step 2：接收报告并记录**（同 Task C1 Step 2）

- [ ] **Step 3：抽查产物**（同 Task C1 Step 3，路径替换）

### Task C5：subagent — memto

**Files:** by subagent

- [ ] **Step 1：派遣 subagent**

  Agent 工具（`subagent_type: "engineer"`，`isolation: "worktree"`），prompt 同 Task C1 Step 1，替换三处：
  - worktree → `.claude/worktrees/steal-memto`
  - branch → `steal/memto`
  - impl plan → `docs/plans/2026-04-18-memto-impl.md`

- [ ] **Step 2：接收报告并记录**（同 Task C1 Step 2）

- [ ] **Step 3：抽查产物**（同 Task C1 Step 3，路径替换）

### Task C6：subagent — millhouse

**Files:** by subagent

- [ ] **Step 1：派遣 subagent**

  Agent 工具（`subagent_type: "engineer"`，`isolation: "worktree"`），prompt 同 Task C1 Step 1，替换三处：
  - worktree → `.claude/worktrees/steal-millhouse`
  - branch → `steal/millhouse`
  - impl plan → `docs/plans/2026-04-18-millhouse-impl.md`

- [ ] **Step 2：接收报告并记录**（同 Task C1 Step 2）

- [ ] **Step 3：抽查产物**（同 Task C1 Step 3，路径替换）

### Task C7：subagent — prompt-language-coach

**Files:** by subagent

- [ ] **Step 1：派遣 subagent**

  Agent 工具（`subagent_type: "engineer"`，`isolation: "worktree"`），prompt 同 Task C1 Step 1，替换三处：
  - worktree → `.claude/worktrees/steal-prompt-language-coach`
  - branch → `steal/prompt-language-coach`
  - impl plan → `docs/plans/2026-04-18-prompt-language-coach-impl.md`

- [ ] **Step 2：接收报告并记录**（同 Task C1 Step 2）

- [ ] **Step 3：抽查产物**（同 Task C1 Step 3，路径替换）

### Task C8：Phase C 汇总 + Owner Review gate

**Files:** none

- [ ] **Step 1：产出 Phase C 总结表**

  手动汇总 Task C1-C7 的 status，填表：

  | Topic | subagent 返回 | 新增 commit 数 | smoke/test 摘要 | 结论（MERGE/SKIP） |
  |-------|--------------|---------------|----------------|-------------------|
  | andrej-karpathy-skills | | | | |
  | flux-enchanted | | | | |
  | generic-agent | | | | |
  | loki-skills-cli | | | | |
  | memto | | | | |
  | millhouse | | | | |
  | prompt-language-coach | | | | |

- [ ] **Step 2：把汇总表给主人 review**

  向主人展示汇总表 + 每个 SKIP topic 的原因，等主人回复 "继续" / "重派 X / Y" / "全 SKIP 进 D"。不说 "继续" / "进 D" 之前 **Phase D 不启动**。

--- PHASE GATE: C → D ---
- [ ] Deliverable exists: Phase C 汇总表完成；7 个 topic 各自结论（MERGE / SKIP）已标注
- [ ] Acceptance criteria met: 主人 review 通过；SKIP 列表冻结
- [ ] No open questions: 无 subagent 异常未处理
- [ ] Owner review: **REQUIRED — 主人不确认 Phase C 结果不进 Phase D**

---

## Phase D — 合入本地 main（按字母序 `--no-ff`，仅 ready 列表）

**目的：把 Phase B + Phase C 确认 MERGE 的 topic 逐个 `--no-ff` merge 进本地 main。每个 topic 一个独立 merge commit。全部操作在主工作树 (`D:/Users/Administrator/Documents/GitHub/orchestrator`) 的 `main` 分支上执行。**

Merge message 模板（参考仓库历史）：`merge: steal/<topic> — <subject>`，`<subject>` 来自 Phase A Task A3/A4 或 Phase C Task C1-7 记录的 topic 末 commit subject（去掉前缀 `docs(steal): ` / `feat(...)` 之类），一句话。

### Task D0：Merge 前置校验

**Files:** none

- [ ] **Step 1：确认主工作树仍在 main 且 clean**

  Run：
  ```bash
  git -C D:/Users/Administrator/Documents/GitHub/orchestrator rev-parse --abbrev-ref HEAD
  git -C D:/Users/Administrator/Documents/GitHub/orchestrator status --porcelain | grep -v '^??' | head -5
  ```
  Expected：`main`；status 输出（过滤 `??`）为空。非此 → STOP。

- [ ] **Step 2：确认 ready 列表（按字母序）**

  根据 Phase B/C 记录，把所有结论 = MERGE 的 topic 按字母顺序列出。把这个列表写进 session（后面 D1..D11 按此列表裁剪；SKIP 的跳过）。

- [ ] **Step 3：pairwise dry-run tree 校验**

  Run（仅对 ready 列表内的 topic）：
  ```bash
  READY="<填入 Step 2 的 topic 列表>"
  for T in $READY; do
    git merge-tree $(git merge-base main steal/$T) main steal/$T | grep -E '^<<<<<<<|^=======' | head -1
  done
  ```
  Expected：每 topic 无冲突标记（空输出）。任何 topic 命中 `<<<<<<<` → 该 topic 从 ready 列表移除，标记 SKIP（有冲突需主人介入），Phase D 继续。

### Task D1..D11：逐 topic `--no-ff` merge（按字母序，仅 ready 列表）

**下面的 D1-D11 按字母序列出 11 个 topic 的 merge task。执行时按 Task D0 Step 2 的 ready 列表裁剪—— SKIP 的 topic 整个 Task 跳过。每 Task 三 Step：执行 merge → 验证 merge commit 就位 → 冲突残留校验。每 topic merge 完，立刻打 archive tag（避免 Phase G 前 tag 漏打）。**

#### Task D1：merge steal/andrej-karpathy-skills（若 ready）

**Files:** Modify `main` ref；Create tag `archive/steal-andrej-karpathy-skills-20260419`

- [ ] **Step 1：执行 merge**

  Run：
  ```bash
  git merge --no-ff steal/andrej-karpathy-skills \
    -m "merge: steal/andrej-karpathy-skills — <Phase C 记录的末 commit subject>"
  ```
  Expected：`Merge made by the 'ort' strategy.`。冲突 → `git merge --abort`，把该 topic 降级为 SKIP。

- [ ] **Step 2：验证 + 打 archive tag**

  Run：
  ```bash
  git log --oneline -2
  git tag archive/steal-andrej-karpathy-skills-20260419 steal/andrej-karpathy-skills
  ```
  Expected：第 1 行是新 merge commit；tag 命令无输出。

- [ ] **Step 3：冲突残留校验**

  Run：`git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

#### Task D2：merge steal/eureka（若 ready）

**Files:** Modify `main` ref；Create tag `archive/steal-eureka-20260419`

- [ ] **Step 1：执行 merge**

  Run：
  ```bash
  git merge --no-ff steal/eureka \
    -m "merge: steal/eureka — <Phase A/B 记录的末 commit subject>"
  ```

- [ ] **Step 2：验证 + 打 archive tag**

  Run：
  ```bash
  git log --oneline -2
  git tag archive/steal-eureka-20260419 steal/eureka
  ```

- [ ] **Step 3：冲突残留校验**

  Run：`git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

#### Task D3：merge steal/flux-enchanted（若 ready）

**Files:** Modify `main` ref；Create tag `archive/steal-flux-enchanted-20260419`

- [ ] **Step 1：执行 merge**

  Run：
  ```bash
  git merge --no-ff steal/flux-enchanted \
    -m "merge: steal/flux-enchanted — <Phase C 记录的末 commit subject>"
  ```

- [ ] **Step 2：验证 + 打 archive tag**

  Run：
  ```bash
  git log --oneline -2
  git tag archive/steal-flux-enchanted-20260419 steal/flux-enchanted
  ```

- [ ] **Step 3：冲突残留校验**

  Run：`git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

#### Task D4：merge steal/generic-agent（若 ready）

**Files:** Modify `main` ref；Create tag `archive/steal-generic-agent-20260419`

- [ ] **Step 1：执行 merge**

  Run：
  ```bash
  git merge --no-ff steal/generic-agent \
    -m "merge: steal/generic-agent — <Phase C 记录的末 commit subject>"
  ```

- [ ] **Step 2：验证 + 打 archive tag**

  Run：
  ```bash
  git log --oneline -2
  git tag archive/steal-generic-agent-20260419 steal/generic-agent
  ```

- [ ] **Step 3：冲突残留校验**

  Run：`git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

#### Task D5：merge steal/loki-skills-cli（若 ready）

**Files:** Modify `main` ref；Create tag `archive/steal-loki-skills-cli-20260419`

- [ ] **Step 1：执行 merge**

  Run：
  ```bash
  git merge --no-ff steal/loki-skills-cli \
    -m "merge: steal/loki-skills-cli — <Phase C 记录的末 commit subject>"
  ```

- [ ] **Step 2：验证 + 打 archive tag**

  Run：
  ```bash
  git log --oneline -2
  git tag archive/steal-loki-skills-cli-20260419 steal/loki-skills-cli
  ```

- [ ] **Step 3：冲突残留校验**

  Run：`git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

#### Task D6：merge steal/memto（若 ready）

**Files:** Modify `main` ref；Create tag `archive/steal-memto-20260419`

- [ ] **Step 1：执行 merge**

  Run：
  ```bash
  git merge --no-ff steal/memto \
    -m "merge: steal/memto — <Phase C 记录的末 commit subject>"
  ```

- [ ] **Step 2：验证 + 打 archive tag**

  Run：
  ```bash
  git log --oneline -2
  git tag archive/steal-memto-20260419 steal/memto
  ```

- [ ] **Step 3：冲突残留校验**

  Run：`git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

#### Task D7：merge steal/millhouse（若 ready）

**Files:** Modify `main` ref；Create tag `archive/steal-millhouse-20260419`

- [ ] **Step 1：执行 merge**

  Run：
  ```bash
  git merge --no-ff steal/millhouse \
    -m "merge: steal/millhouse — <Phase C 记录的末 commit subject>"
  ```

- [ ] **Step 2：验证 + 打 archive tag**

  Run：
  ```bash
  git log --oneline -2
  git tag archive/steal-millhouse-20260419 steal/millhouse
  ```

- [ ] **Step 3：冲突残留校验**

  Run：`git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

#### Task D8：merge steal/prompt-language-coach（若 ready）

**Files:** Modify `main` ref；Create tag `archive/steal-prompt-language-coach-20260419`

- [ ] **Step 1：执行 merge**

  Run：
  ```bash
  git merge --no-ff steal/prompt-language-coach \
    -m "merge: steal/prompt-language-coach — <Phase C 记录的末 commit subject>"
  ```

- [ ] **Step 2：验证 + 打 archive tag**

  Run：
  ```bash
  git log --oneline -2
  git tag archive/steal-prompt-language-coach-20260419 steal/prompt-language-coach
  ```

- [ ] **Step 3：冲突残留校验**

  Run：`git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

#### Task D9：merge steal/r38-sandbox-retro（若 ready）

**Files:** Modify `main` ref；Create tag `archive/steal-r38-sandbox-retro-20260419`

- [ ] **Step 1：执行 merge**

  Run：
  ```bash
  git merge --no-ff steal/r38-sandbox-retro \
    -m "merge: steal/r38-sandbox-retro — <Phase A/B 记录的末 commit subject>"
  ```

- [ ] **Step 2：验证 + 打 archive tag**

  Run：
  ```bash
  git log --oneline -2
  git tag archive/steal-r38-sandbox-retro-20260419 steal/r38-sandbox-retro
  ```

- [ ] **Step 3：冲突残留校验**

  Run：`git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

#### Task D10：merge steal/tlotp-monorepo（若 ready）

**Files:** Modify `main` ref；Create tag `archive/steal-tlotp-monorepo-20260419`

- [ ] **Step 1：执行 merge**

  Run：
  ```bash
  git merge --no-ff steal/tlotp-monorepo \
    -m "merge: steal/tlotp-monorepo — <Phase A/B 记录的末 commit subject>"
  ```

- [ ] **Step 2：验证 + 打 archive tag**

  Run：
  ```bash
  git log --oneline -2
  git tag archive/steal-tlotp-monorepo-20260419 steal/tlotp-monorepo
  ```

- [ ] **Step 3：冲突残留校验**

  Run：`git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

#### Task D11：merge steal/x1xhlol-system-prompts（若 ready）

**Files:** Modify `main` ref；Create tag `archive/steal-x1xhlol-system-prompts-20260419`

- [ ] **Step 1：执行 merge**

  Run：
  ```bash
  git merge --no-ff steal/x1xhlol-system-prompts \
    -m "merge: steal/x1xhlol-system-prompts — <Phase A/B 记录的末 commit subject>"
  ```

- [ ] **Step 2：验证 + 打 archive tag**

  Run：
  ```bash
  git log --oneline -2
  git tag archive/steal-x1xhlol-system-prompts-20260419 steal/x1xhlol-system-prompts
  ```

- [ ] **Step 3：冲突残留校验**

  Run：`git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

### Task D12：Phase D 汇总校验（跨 topic 功能检测）

**目的：** 全部合完后跑一次跨 topic 的集成验证，确保没有合并层面互相踩脚（两个 topic 都改了 `CLAUDE.md` 这类文件时，`--no-ff` 不会检测到逻辑冲突）。

**Files:** none

- [ ] **Step 1：main 端 merge commit 数量核对**

  Run：
  ```bash
  git log --oneline --grep='^merge: steal/' origin/main..main | wc -l
  ```
  Expected：= ready 列表长度。偏差 → 查哪个 topic 漏 merge。

- [ ] **Step 2：boot.md 编译校验（Orchestrator 核心流程）**

  Run：
  ```bash
  python SOUL/tools/compiler.py 2>&1 | tail -20
  ```
  Expected：输出含 `boot.md` 编译成功行、context pack 条目。异常（Python 栈）→ 该问题归因到最近一次 merge（`git log --oneline -1`），把该 topic 的 merge commit 用 `git revert -m 1 <sha>` 撤销（**需主人授权**，CLAUDE.md 定义的 revert 也是 rollback 家族），报告给主人。

- [ ] **Step 3：md-lint audit（若 md-lint skill 已就位）**

  Run：
  ```bash
  [ -f .claude/skills/md-lint/scripts/audit.py ] && python .claude/skills/md-lint/scripts/audit.py .claude/skills 2>&1 | tail -20 || echo "md-lint not installed"
  ```
  Expected：`md-lint not installed` 或 audit 输出 `issues: 0`（或与 merge 前基线相同）。新增 issues 数 > 基线 → 报告主人。

- [ ] **Step 4：CLAUDE.md 内容完整性（不少于 merge 前）**

  Run：
  ```bash
  wc -l CLAUDE.md
  grep -c "^#" CLAUDE.md
  ```
  Expected：行数不减少；顶级标题数不减少。减少 → 有 merge 把内容吞掉，查 `git log -p CLAUDE.md origin/main..HEAD` 定位。

- [ ] **Step 5：hooks 文件语法自检**

  Run：
  ```bash
  for H in .claude/hooks/*.sh; do
    bash -n "$H" || echo "SYNTAX ERROR: $H"
  done
  ```
  Expected：无 `SYNTAX ERROR`。

- [ ] **Step 6：dispatch-gate 与 commit-reminder hook 打招呼能跑**

  Run：
  ```bash
  bash .claude/hooks/dispatch-gate.sh </dev/null 2>&1 | head -5 || true
  bash .claude/hooks/commit-reminder.sh </dev/null 2>&1 | head -5 || true
  ```
  Expected：无 `command not found` / Python 异常。若 hook 失败 → 回溯 merge，不自动回滚，报告主人。

- [ ] **Step 7：docker-compose 配置合法（若本地有 docker）**

  Run：`[ -f docker-compose.yml ] && docker compose config --quiet 2>&1 | head -5 || echo "no compose"`
  Expected：`no compose` 或无输出。非法 → 回溯 merge，报告。

--- PHASE GATE: D → E ---
- [ ] Deliverable exists: ready 列表全部 merge 完；每 topic 一个 `--no-ff` merge commit + 一个 archive tag
- [ ] Acceptance criteria met: D12 Step 1-7 全绿（或报告异常并由主人处理）
- [ ] No open questions: 无未解冲突、无 revert 未完成
- [ ] Owner review: **REQUIRED — push 前必须停下来展示 `git log --oneline origin/main..main` 结果并等主人说 "push"**

---

## Phase E — Push 到 origin/main（需主人授权）

**目的：把 Phase D 的 merge commit 推到 origin/main。主人不说 "push"（或等价词），Phase E 不启动。**

### Task E1：Push gate 展示

**Files:** none

- [ ] **Step 1：展示将推的完整 commit 列表**

  Run：
  ```bash
  git log --oneline origin/main..main
  ```
  把输出贴给主人 + Phase D12 Step 2-7 的 smoke 结果，等主人回复。

### Task E2：执行 push

**Files:** none

- [ ] **Step 1：push（主人授权后）**

  Run：`git push origin main`
  Expected：`main -> main` 成功。若被拒（remote 期间有人推过）：
    - Run `git fetch origin main && git log --oneline main..origin/main`
    - STOP 等主人决策（不自动 pull --rebase，会搅乱 merge 顺序）。

- [ ] **Step 2：确认 origin/main 已追上**

  Run：
  ```bash
  git fetch origin main
  git log --oneline origin/main..main
  ```
  Expected：空输出。

--- PHASE GATE: E → F ---
- [ ] Deliverable exists: push 成功；`origin/main..main` 空
- [ ] Acceptance criteria met: remote 已更新
- [ ] No open questions: push 未被拒
- [ ] Owner review: not required（push 已是主人授权）

---

## Phase F — 回收 worktree 与分支

**目的：push 成功后，拆除 ready 列表内 topic 对应的 worktree + 分支。archive tag 已在 Phase D 打好、分支已无数据风险。`-old` 旧归档分支保留不动。SKIP 列表内的 topic **不回收**（留给主人二轮）。**

### Task F1：archive tag 完整性最后校验

**Files:** none

- [ ] **Step 1：ready 列表内每个 topic 都有 archive tag**

  Run（`READY` 填入 ready 列表）：
  ```bash
  READY="<填入 ready 列表>"
  for T in $READY; do
    git rev-parse --verify "archive/steal-$T-20260419" >/dev/null || echo "MISSING $T"
  done
  ```
  Expected：空输出（无 MISSING）。任何 MISSING → STOP，Phase D 那一步 archive tag 漏打，先补。

### Task F2：逐 topic 回收（ready 列表）

**Files:**
- Delete: `.claude/worktrees/steal-<topic>` 目录（每 ready topic 一个）
- Delete: `steal/<topic>` 分支 ref（每 ready topic 一个）

- [ ] **Step 1：批量 remove worktree**

  Run：
  ```bash
  READY="<填入 ready 列表>"
  for T in $READY; do
    git worktree remove ".claude/worktrees/steal-$T" && echo "WT OK $T"
  done
  ```
  Expected：每 topic 一行 `WT OK`。任意 topic 没有 OK → STOP，检查是否 dirty（Phase A 已排除）。

- [ ] **Step 2：批量 delete branch**

  Run：
  ```bash
  READY="<填入 ready 列表>"
  for T in $READY; do
    git branch -D "steal/$T" && echo "BR OK $T"
  done
  ```
  Expected：每 topic 一行 `BR OK`（前面会有 `Deleted branch steal/<topic> (was <sha>).`）。任意 not fully merged → 查 archive tag 是否在、merge 是否真完成，再决定是否强删。

- [ ] **Step 3：确认 ready 列表 topic 的 ref / worktree 全消失**

  Run：
  ```bash
  READY="<填入 ready 列表>"
  for T in $READY; do
    H=$(git rev-parse --verify "steal/$T" 2>/dev/null && echo EXIST || echo GONE)
    W=$([ -d ".claude/worktrees/steal-$T" ] && echo EXIST || echo GONE)
    A=$(git rev-parse --verify "archive/steal-$T-20260419" >/dev/null 2>&1 && echo KEPT || echo MISSING)
    printf "%-30s head=%s wt=%s archive=%s\n" "$T" "$H" "$W" "$A"
  done
  ```
  Expected：每 topic `head=GONE wt=GONE archive=KEPT`。任意偏差 → 报告主人。

--- PHASE GATE: F → G ---
- [ ] Deliverable exists: ready 列表内 topic 的 worktree + 分支全回收；archive tag 全在
- [ ] Acceptance criteria met: Task F2 Step 3 表格全绿
- [ ] No open questions: 无删除失败
- [ ] Owner review: not required

---

## Phase G — 终态快照 & Receipt

**目的：生成主人一眼可扫的终态。**

### Task G1：终态快照

**Files:** none

- [ ] **Step 1：剩余 worktree 清单**

  Run：`git worktree list`
  Expected：
  - 主工作树
  - `.claude/worktrees/r83-trust-tagging`（out of scope）
  - `.claude/worktrees/wgh-refactor`（out of scope）
  - 4 个 `worktree-agent-*`（out of scope，locked）
  - SKIP 列表内未回收的 `steal-*` worktree（若有）

- [ ] **Step 2：ref 状态一览**

  Run：
  ```bash
  echo "== archive tag (本轮应全在) =="
  git tag -l 'archive/steal-*-20260419' | sort
  echo "== 本轮 ready steal head (应全 GONE) =="
  READY="<填入 ready 列表>"
  for T in $READY; do
    git rev-parse --verify "steal/$T" 2>/dev/null && echo "  LEAK $T" || true
  done
  echo "== 保留的 -old 分支 =="
  git branch --list 'steal/*-old' | sort
  echo "== main vs origin/main =="
  git log --oneline origin/main..main
  echo "== SKIP 列表（未合并） =="
  echo "<填入 SKIP 列表>"
  ```
  Expected：
  - archive tag：前一轮 7 个 + 本轮 ready 列表长度个
  - LEAK：无
  - `-old` 分支：前一轮 7 个（原样）
  - `origin/main..main`：空（push 成功后）
  - SKIP 列表：显式列出未合并的 topic

### Task G2：交付 receipt

**Files:** none

- [ ] **Step 1：输出 Orchestrator 标准 receipt**

  展示给主人：
  ```
  Phase D merged commits（按字母序）：
  | Commit | Topic | Batch |
  |--------|-------|-------|
  | <sha>  | merge: steal/<t1>  | A 或 B |
  | <sha>  | merge: steal/<t2>  | ... |
  | ...    | ...                | ... |

  Phase E pushed: origin/main
  Phase F removed: <N> worktree + <N> branch
  Phase F preserved: <N> archive/steal-*-20260419 tag + 前一轮 7 个 steal/*-old
  SKIP 列表（本轮未合，留给二轮）：
  | Topic | 原因 |
  |-------|------|
  | ...   | ...  |
  ```

--- PHASE GATE: G → Done ---
- [ ] Deliverable exists: Phase G Step 1-2 快照与 receipt 已给主人
- [ ] Acceptance criteria met: 终态匹配 Goal
- [ ] No open questions
- [ ] Owner review: not required（receipt 已交付）

---

## Rollback Guide（仅参考，不在 plan 默认流程内）

**Batch B subagent 失败（Phase C）：**
- subagent 报告失败 → 标记该 topic 为 SKIP，进入下一个。不删 worktree、不 reset 分支。主人二轮决定是否重派 / 重写 plan / 丢弃。

**Phase D 某个 merge 后发现不对，尚未 push（Phase E 前）：**
- 撤销最后一个 merge + 它的 archive tag：`git diff HEAD~1..HEAD > /tmp/merge-rollback-<topic>.patch && git reset --hard HEAD~1 && git tag -d archive/steal-<topic>-20260419`。**CLAUDE.md 定义的 rollback 需主人授权**，即便在 plan 内也必须先备份再执行，并在 session 里告知主人备份位置。

**Phase E push 后发现不对：**
- 不 force push。按仓库惯例 revert：`git revert -m 1 <merge-sha>`，推新 commit。archive tag 保留。

**Phase F 删错分支（有 archive tag 兜底）：**
- `git branch steal/<topic> archive/steal-<topic>-20260419`
- `git worktree add .claude/worktrees/steal-<topic> steal/<topic>`

---

## Self-Review 结果

**1. Spec coverage（对照主人原话"偷师 -> spec -> plan -> 实施 ... 检测功能后，最后再合并到 main"）：**
- 偷师/spec/plan 已经在各 worktree 内完成（Phase A Task A3/A4 验证）。Batch A 4 个已含完成的 impl；Batch B 7 个各自 impl plan 就绪 → Phase C subagent 执行 ✓
- "各自的分支推进" → Phase C 每 topic 独立 subagent + isolation=worktree ✓
- "确保他们全部完成" → Phase B/C 给每 topic 结论 MERGE / SKIP；SKIP 不硬推，留二轮 ✓
- "落实闭环" → Phase D 每 topic merge + archive tag；Phase F worktree/branch 回收 ✓
- "检测功能" → Phase B（每 topic 单独 smoke）+ Phase D12（跨 topic 集成验证）✓
- "最后再合并到 main" → Phase D + Phase E（需主人授权 push）✓

**2. Placeholder scan:** 搜索 `TBD` / `TODO` / `fill in` / `etc` / `similar to` 单独出现 / `refactor` 单独出现 / `clean up` 单独出现 / `optimize` 单独出现 —— plan 中无命中。每个 topic 的 Task Cn 都写出独立 prompt 模板，非 "same as above"；11 个 Merge task 各自有完整 `git merge` 命令与 tag 命令。`<subject>` 与 `<填入 ready 列表>` 是 **执行时替换** 占位，不是 plan-placeholder（在 Phase A/B/C Step 里明确规定如何采集 subject 与 ready 列表）。

**3. Type/名称一致性：** 11 个 topic 名字在 Phase A/B/C/D/F/G 完全一致；`archive/steal-<topic>-20260419` 格式统一；`.claude/worktrees/steal-<topic>` 路径统一；`docs/plans/2026-04-18-<topic>-impl.md` 格式统一。

**4. Step count：** A1-A4=11 步、B1-B4=13 步、C1-C8=23 步、D0+D1-D12=36 步、E1-E2=3 步、F1-F2=5 步、G1-G2=3 步。总计 **94 步**，超过 plan_template 建议的 30 步上限。理由：11 个 topic 的 Merge task 不可合并（每 topic 一个独立 merge commit + 独立 verify + 独立 archive tag + 独立冲突检查，Phase D 的 36 步全是必要原子操作），Phase C 7 个 subagent 任务不可合并（独立 dispatch + 独立接收 + 独立抽查）。Phase D12 的 7 步跨 topic 集成验证是合入后唯一一次保底，不可压。接受超标。

---

## 下一步

Plan 已完成。**本 plan 涉及多轮 subagent dispatch 与不可逆 `git push origin main`（Gate 2: Plan → Implement 需 Owner review），按 CLAUDE.md 约定不自动启动。主人 review 这份 plan，说 "开干" / "按这个执行" 之后，由主 session 以 `superpowers:executing-plans` 技能从 Phase A 开始逐 Task 推。Batch B 7 个 subagent 在 Phase C 由主 session 顺序派（不并发——并发会让 Phase C8 汇总表混乱）。**
