# Rescue/Steal 7 Topics — 合回 main + 回收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 7 个 steal/<topic> 分支以 `--no-ff` merge 方式合入本地 main、由主人手动授权后 push origin/main、然后拆除 7 对 rescue/steal worktree 与分支；archive tag 与 `steal/<topic>-old` 分支原样保留。

**Architecture:** 以 `docs/superpowers/plans/2026-04-19-rescue-vs-steal-compare.md` 的判定（7 对 tree hash 等价、range-diff 全 `=`）为前提，选择 steal 侧为正式合入源。仓库历史惯例为 `merge: <branch> — <subject>` 风格的 merge commit（非 FF），因此每个 topic 一个 merge commit，保留原有内部 commit 链供 bisect。push 是独立 gate，需要主人明确授权。回收阶段采用「tag 已是 archive，分支可删」的原则，不再创建 `-old` 第二代（旧 `-old` 名字已被前一轮占用）。

**Tech Stack:** git (worktree, merge --no-ff, branch -D, worktree remove), bash for-loops for batch ops。无代码改动、无测试执行，纯 git 运维。

**Scope — 本轮操作的 7 个 topic（字母序）:**

1. `ai-customer-support-agent`
2. `freeclaude`
3. `learn-likecc`
4. `opus-mind`
5. `prompt-engineering-models`
6. `steering-log`
7. `zubayer-multi-agent-research`

**Out of scope（明确不碰）:**

- 其他 `steal/*` 分支（`andrej-karpathy-skills`, `eureka`, `flux-enchanted`, `generic-agent`, `loki-skills-cli`, `memto`, `millhouse`, `prompt-language-coach`, `r38-sandbox-retro`, `tlotp-monorepo`, `x1xhlol-system-prompts`）
- `steal/<topic>-old` 归档分支（保留）
- `archive/steal-<topic>-20260419` tag（保留）
- `refactor/worktree-gate-hardening` 分支 & 其 worktree（不在本 plan 范围）
- 主工作树的未跟踪文件（`.claude/bin/`, `.claude/skills/claude-at/`, `SOUL/public/prompts/*.md`, `docs/superpowers/plans/R83-dia-trust-tagging.md`, `plans/`）—— 继续存留

**Assumptions:**

- `ASSUMPTION`: 合入顺序选字母序。理由：7 个 topic 之间无代码依赖（报告里 rescue..steal 文件差都是 ∅，每 topic 独立 add 若干 doc/新 skill 文件），顺序无所谓；字母序便于循环脚本与 review。
- `ASSUMPTION`: 使用 `git merge --no-ff`。理由：本地 main head (`6afc8d6`) 比 steal 分叉点 (`265492a`) 领先 2 个 commit，FF 不可能；仓库历史显示 `merge: steal/... — ...` 风格即 `--no-ff`（见 `merge: steal/hermes-agent-r77`、`merge: steal/round-deep-rescan-r60` 等）。
- `ASSUMPTION`: push 合并成果时一起推送本地 main 已累积的前置 3 个 commit（`3c18723`, `265492a`, `6afc8d6`）—— 主人在 push gate 复核这份 commit 列表后授权。
- `ASSUMPTION`: 回收阶段删除 `steal/<topic>` 分支（不再创建 `-old` 第二代）。理由：`archive/steal-<topic>-20260419` tag 已保存 tip，分支删除零丢失；旧的 `steal/<topic>-old` 名字被上一轮占用，起 `-old-r2` 只会污染 refspec。

---

## File Map

**本 plan 不修改源码文件，仅产生 git 状态变更。**

| 状态类别 | 目标 | 变更 |
|---|---|---|
| 分支 | `main` | 追加 7 个 `--no-ff` merge commit |
| 分支 | `steal/<7 topics>` | push 后删除 |
| 分支 | `rescue/<7 topics>` | push 后删除 |
| Worktree | `.claude/worktrees/steal-<6 topics>` | push 后 `git worktree remove`（freeclaude 无对应 worktree，跳过） |
| Worktree | `.claude/worktrees/rescue-<7 topics>` | push 后 `git worktree remove` |
| Tag | `archive/steal-<7 topics>-20260419` | 不动 |
| 分支 | `steal/<7 topics>-old` | 不动 |
| Remote | `origin/main` | Phase C 推进 (本地 main + 7 merge commits) |

---

## Phase A — Pre-flight Gate

**目的：在动任何 ref 之前，确认报告前提仍然成立。**

### Task A1：主工作树状态与位置校验

**Files:** none（只读 git）

- [ ] **Step 1：确认主工作树在 main 且无 staged 改动**

  Run:
  ```bash
  git -C D:/Users/Administrator/Documents/GitHub/orchestrator rev-parse --abbrev-ref HEAD
  git -C D:/Users/Administrator/Documents/GitHub/orchestrator diff --cached --name-only
  ```
  Expected: `main` / 空输出。若非 main 或有 staged 改动，STOP。

- [ ] **Step 2：列出当前未跟踪文件，确认与 plan 声明一致**

  Run:
  ```bash
  git -C D:/Users/Administrator/Documents/GitHub/orchestrator status --porcelain | grep '^??'
  ```
  Expected: 仅 `.claude/bin/`, `.claude/skills/claude-at/`, `SOUL/public/prompts/session_handoff_rescue_compare.md`, `SOUL/public/prompts/steal_pilot_dispatch.md`, `docs/superpowers/plans/R83-dia-trust-tagging.md`, `plans/`（加上本 plan 本身）。若出现其他 tracked-but-modified，STOP 并询问。

### Task A2：tree hash 与 archive tag 等价性重验

**Files:** none

- [ ] **Step 1：逐对校验 rescue/<T> 与 steal/<T> 的 tree hash 等价**

  Run:
  ```bash
  for T in ai-customer-support-agent freeclaude learn-likecc opus-mind prompt-engineering-models steering-log zubayer-multi-agent-research; do
    R=$(git rev-parse rescue/$T^{tree})
    S=$(git rev-parse steal/$T^{tree})
    if [ "$R" = "$S" ]; then
      printf "%-40s OK  %s\n" "$T" "${R:0:12}"
    else
      printf "%-40s MISMATCH rescue=%s steal=%s\n" "$T" "${R:0:12}" "${S:0:12}"
    fi
  done
  ```
  Expected: 7 行全部 `OK`，与 compare 报告中列出的 tree hash (`194f91504583`, `2750cfba7007`, `380171db16bc`, `e02d7a32deb9`, `797ec0e9362e`, `ef6ae706c270`, `baaedeccea24`) 逐一对上。任何 MISMATCH → STOP，触发二轮 compare。

- [ ] **Step 2：7 个 archive tag 都存在且指向 rescue 侧 tip**

  Run:
  ```bash
  for T in ai-customer-support-agent freeclaude learn-likecc opus-mind prompt-engineering-models steering-log zubayer-multi-agent-research; do
    TAG=$(git rev-parse --verify "archive/steal-$T-20260419" 2>/dev/null || echo MISSING)
    RESCUE=$(git rev-parse rescue/$T)
    printf "%-40s tag=%.10s rescue=%.10s\n" "$T" "$TAG" "$RESCUE"
  done
  ```
  Expected: 7 行 `tag=...` 均非 `MISSING`（tag 是否等于 rescue tip 不重要，只要 tag 存在即代表归档已锁定）。任何 `MISSING` → STOP。

- [ ] **Step 3：所有 worktree clean (dirty=0)**

  Run:
  ```bash
  for T in ai-customer-support-agent freeclaude learn-likecc opus-mind prompt-engineering-models steering-log zubayer-multi-agent-research; do
    for SIDE in rescue steal; do
      WT=".claude/worktrees/$SIDE-$T"
      if [ -d "$WT" ]; then
        D=$(git -C "$WT" status --porcelain | wc -l)
        [ "$D" -ne 0 ] && printf "%-8s %-40s DIRTY %s\n" "$SIDE" "$T" "$D"
      fi
    done
  done
  ```
  Expected: 空输出（没有任何 dirty 行）。有 dirty → STOP。

### Task A3：main 与 origin/main 差异快照

**Files:** none

- [ ] **Step 1：记录 push 前 main 领先的 commit（供 Phase C gate 展示）**

  Run:
  ```bash
  git -C D:/Users/Administrator/Documents/GitHub/orchestrator fetch origin main
  git -C D:/Users/Administrator/Documents/GitHub/orchestrator log --oneline origin/main..main
  ```
  Expected：3 行（`6afc8d6`, `265492a`, `3c18723`）。若数量不同，记录实际结果在 Phase C gate 里，不阻断（可能主人期间又 commit 了）。

--- PHASE GATE: A → B ---
- [ ] Deliverable exists: Phase A 三个 task 的所有 verify 命令输出都记录在 session 里
- [ ] Acceptance criteria met: 7 pairs tree-hash OK / 7 archive tag present / 0 dirty worktree / main 位置确认
- [ ] No open questions: 无 MISMATCH、无 MISSING、无 DIRTY
- [ ] Owner review: not required（只读校验）

---

## Phase B — Merge 7 个 steal/<topic> 到 main

**目的：按字母序逐个 `--no-ff` merge，每个 topic 一个独立 merge commit。每个 Task 完成后 `git log --oneline -3` 确认新 merge commit 就位，`git status` 清洁后再进入下一个。所有操作都在主工作树 (`D:/Users/Administrator/Documents/GitHub/orchestrator`) 执行。**

每个 merge 的 commit message 规则（参考仓库历史格式 `merge: steal/hermes-agent-r77 — R77 condenser...`）：

```
merge: steal/<topic> — <一句话总结>
```

`<一句话总结>` 取自该 topic 在 compare 报告里列出的 steal report commit subject，去掉 `docs(steal): ` 前缀。

### Task B1：merge steal/ai-customer-support-agent

**Files:**
- Modify: `main` branch ref（追加 merge commit）

- [ ] **Step 1：执行 merge**

  Run:
  ```bash
  git merge --no-ff steal/ai-customer-support-agent \
    -m "merge: steal/ai-customer-support-agent — R79 ai-customer-support-agent steal report"
  ```
  Expected：`Merge made by the 'ort' strategy.` 加若干 `create mode ... ` 文件行。若冲突，STOP 并报告冲突文件（理论上不会冲突，两侧都只 add 新文件）。

- [ ] **Step 2：验证 merge commit 就位**

  Run:
  ```bash
  git log --oneline -3
  ```
  Expected：第 1 行是新的 merge commit，subject 匹配 Step 1 的 -m；第 2/3 行是被合入的 `docs(plan): implementation plan for ai-customer-support-agent steal` 和 `docs(steal): R79 ai-customer-support-agent steal report`（顺序取决于 git merge 的 parent 排列，但这两个 subject 都应该可见）。

- [ ] **Step 3：验证无冲突残留**

  Run: `git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空输出（没有未解决冲突标记）。非空 → STOP。

### Task B2：merge steal/freeclaude

**Files:**
- Modify: `main` branch ref

- [ ] **Step 1：执行 merge**

  Run:
  ```bash
  git merge --no-ff steal/freeclaude \
    -m "merge: steal/freeclaude — R78 freeclaude steal report"
  ```
  Expected：Merge made.

- [ ] **Step 2：验证**

  Run: `git log --oneline -3`
  Expected：顶 commit 是 merge: steal/freeclaude ...；接下来可见 `docs(plans): R78 FreeClaude P0 implementation plan` / `docs(steal): R78 freeclaude steal report`。

- [ ] **Step 3：冲突残留校验**

  Run: `git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

### Task B3：merge steal/learn-likecc

**Files:**
- Modify: `main` branch ref

- [ ] **Step 1：执行 merge**

  Run:
  ```bash
  git merge --no-ff steal/learn-likecc \
    -m "merge: steal/learn-likecc — R82 learn-likecc steal report"
  ```
  Expected：Merge made.

- [ ] **Step 2：验证**

  Run: `git log --oneline -3`
  Expected：顶 commit 是 merge: steal/learn-likecc ...。

- [ ] **Step 3：冲突残留校验**

  Run: `git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

### Task B4：merge steal/opus-mind

**Files:**
- Modify: `main` branch ref（`.claude/skills/md-lint/scripts/audit.py` 是 WIP 二期要打磨的，本次以 WIP 形态随 merge 落地——compare 报告标注"确认一致"）

- [ ] **Step 1：执行 merge**

  Run:
  ```bash
  git merge --no-ff steal/opus-mind \
    -m "merge: steal/opus-mind — R79 opus-mind steal report + md-lint WIP"
  ```
  Expected：Merge made.

- [ ] **Step 2：验证 WIP 文件落地**

  Run: `git show HEAD --stat | grep 'md-lint'`
  Expected：`.claude/skills/md-lint/scripts/__init__.py` 与 `.claude/skills/md-lint/scripts/audit.py`（383 行）出现在 stat 里。未出现 → STOP 审 merge 结果。

- [ ] **Step 3：冲突残留校验**

  Run: `git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

### Task B5：merge steal/prompt-engineering-models

**Files:**
- Modify: `main` branch ref（引入 `.claude/skills/steal/constraints/unaudited-attachment-triage.md` — compare 报告标注"确认一致"）

- [ ] **Step 1：执行 merge**

  Run:
  ```bash
  git merge --no-ff steal/prompt-engineering-models \
    -m "merge: steal/prompt-engineering-models — R80 prompt-engineering-models steal + unaudited-attachment-triage constraint"
  ```
  Expected：Merge made.

- [ ] **Step 2：验证 constraint 文件落地**

  Run: `git show HEAD --stat | grep 'unaudited-attachment-triage'`
  Expected：`.claude/skills/steal/constraints/unaudited-attachment-triage.md` 出现。未出现 → STOP。

- [ ] **Step 3：冲突残留校验**

  Run: `git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

### Task B6：merge steal/steering-log

**Files:**
- Modify: `main` branch ref

- [ ] **Step 1：执行 merge**

  Run:
  ```bash
  git merge --no-ff steal/steering-log \
    -m "merge: steal/steering-log — R78 steering-log steal report"
  ```
  Expected：Merge made.

- [ ] **Step 2：验证**

  Run: `git log --oneline -3`
  Expected：顶 commit 是 merge: steal/steering-log ...。

- [ ] **Step 3：冲突残留校验**

  Run: `git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

### Task B7：merge steal/zubayer-multi-agent-research

**Files:**
- Modify: `main` branch ref

- [ ] **Step 1：执行 merge**

  Run:
  ```bash
  git merge --no-ff steal/zubayer-multi-agent-research \
    -m "merge: steal/zubayer-multi-agent-research — R79 zubayer multi-agent research skill steal report"
  ```
  Expected：Merge made.

- [ ] **Step 2：验证**

  Run: `git log --oneline -3`
  Expected：顶 commit 是 merge: steal/zubayer-multi-agent-research ...。

- [ ] **Step 3：冲突残留校验**

  Run: `git status --porcelain | grep -E '^(UU|AA|DD)' | head -1`
  Expected：空。

### Task B8：Phase B 整体汇总校验

**Files:** none

- [ ] **Step 1：确认 main 在 push 前的 commit 链**

  Run: `git log --oneline origin/main..main`
  Expected：14 行（3 个原 main 领先 commit + 7 个 merge commit + 其中含 7 个 steal 分支被合并时引入的 16 个内部 commit）。实际行数可能浮动（因为 --no-ff 把 steal 的内部 commit 也暴露在一等历史上），关键看 7 个 `merge: steal/...` 均存在。若缺任何一个，STOP 查对应 Task。

- [ ] **Step 2：确认 7 个 merge commit 逐一就位**

  Run: `git log --oneline --grep='^merge: steal/' origin/main..main | wc -l`
  Expected：`7`。非 7 → STOP。

- [ ] **Step 3：main 工作树 clean**

  Run: `git status --porcelain | grep -v '^??' | head -1`
  Expected：空（未跟踪文件 `??` 不计入）。

--- PHASE GATE: B → C ---
- [ ] Deliverable exists: main 本地领先 origin/main ≥10 commit，含 7 个 `merge: steal/...` merge commit
- [ ] Acceptance criteria met: Phase B 全部 7 个 Task 完成、Step 3 冲突检查全通过、B8 统计 = 7
- [ ] No open questions: 无冲突、无 dirty、无缺失文件
- [ ] Owner review: **REQUIRED — push 前必须停下来展示 `git log --oneline origin/main..main` 结果并等主人说 "push"**

---

## Phase C — Push 到 origin/main

**目的：在主人明确授权后，把本地 main 推到 origin/main。主人不说 "push"（或等价词），Phase C 不启动。**

### Task C1：Push gate 展示

**Files:** none

- [ ] **Step 1：展示将推的完整 commit 列表**

  Run: `git log --oneline origin/main..main`
  Present to owner。等主人回复。

### Task C2：执行 push

**Files:** none

- [ ] **Step 1：push（仅在主人授权后执行）**

  Run:
  ```bash
  git push origin main
  ```
  Expected：`To ...orchestrator.git\n   <sha>..<sha>  main -> main`。无 rejected。若被 remote 拒（因为 remote 移动了），跑 `git fetch origin main && git log --oneline main..origin/main` 展示 remote 新 commit，STOP 等主人决策（不自动 pull --rebase，以免搅乱 7 个 merge commit 顺序）。

- [ ] **Step 2：确认 origin/main 已追上**

  Run:
  ```bash
  git fetch origin main
  git log --oneline origin/main..main
  ```
  Expected：空输出（本地与 remote 同步）。

--- PHASE GATE: C → D ---
- [ ] Deliverable exists: `git push` 返回成功，`origin/main..main` 为空
- [ ] Acceptance criteria met: remote 已更新；archive tag 仍在（Phase D 开头会再查一次）
- [ ] No open questions: push 未被拒
- [ ] Owner review: not required（push 已是主人授权，后续回收是清扫）

---

## Phase D — 回收 7 对 rescue/steal worktree 与分支

**目的：push 成功后拆除本次的 14 条分支 + 13 个 worktree（steal/freeclaude 无 worktree，跳过那一个）。archive tag 与 `-old` 分支保留。每次操作前都先走 Gate: Delete 的前置检查（已全部在 Phase A 通过：内容在 tag 里、无 dirty、无引用）。**

### Task D1：再次确认 archive tag 与 -old 分支完好（回收前的最后一道 gate）

**Files:** none

- [ ] **Step 1：archive tag 全在**

  Run:
  ```bash
  for T in ai-customer-support-agent freeclaude learn-likecc opus-mind prompt-engineering-models steering-log zubayer-multi-agent-research; do
    git rev-parse --verify "archive/steal-$T-20260419" >/dev/null || echo "MISSING archive/steal-$T-20260419"
  done
  ```
  Expected：空输出。任何 MISSING → STOP，不能删分支。

- [ ] **Step 2：`-old` 分支全在**

  Run:
  ```bash
  for T in ai-customer-support-agent freeclaude learn-likecc opus-mind prompt-engineering-models steering-log zubayer-multi-agent-research; do
    git rev-parse --verify "steal/$T-old" >/dev/null || echo "MISSING steal/$T-old"
  done
  ```
  Expected：空输出。任何 MISSING → 报告给主人，由主人决定要不要在删 `steal/<T>` 前补归档（不自动做）。

### Task D2：移除 7 个 rescue worktree + 删 7 条 rescue 分支

**Files:**
- Delete: `.claude/worktrees/rescue-<7 topics>`（目录）
- Delete: `rescue/<7 topics>`（分支 ref）

- [ ] **Step 1：批量 remove worktree + delete branch**

  Run:
  ```bash
  for T in ai-customer-support-agent freeclaude learn-likecc opus-mind prompt-engineering-models steering-log zubayer-multi-agent-research; do
    git worktree remove ".claude/worktrees/rescue-$T" && \
      git branch -D "rescue/$T" && \
      echo "OK $T"
  done
  ```
  Expected：7 行 `OK <topic>`。任意一行没出现 `OK` → STOP，检查该 topic（可能 worktree 有 dirty；理论上 Phase A Step 3 已排除）。

- [ ] **Step 2：确认 rescue/* 全数消失**

  Run: `git branch --list 'rescue/*'`
  Expected：空输出。

- [ ] **Step 3：确认 rescue worktree 目录全清**

  Run: `git worktree list | grep -c 'rescue-'`
  Expected：`0`。

### Task D3：移除 6 个 steal worktree + 删 7 条 steal 分支

**注意：** `steal/freeclaude` 分支存在但**没有对应 worktree**（仅 6 个 worktree 而非 7 个，`.claude/worktrees/steal-freeclaude/` 不存在）。分支依然要删。

**Files:**
- Delete: `.claude/worktrees/steal-<6 topics>`（排除 freeclaude）
- Delete: `steal/<7 topics>`（全部 7 条，含 freeclaude）

- [ ] **Step 1：批量 remove worktree（6 个，跳过 freeclaude）**

  Run:
  ```bash
  for T in ai-customer-support-agent learn-likecc opus-mind prompt-engineering-models steering-log zubayer-multi-agent-research; do
    git worktree remove ".claude/worktrees/steal-$T" && echo "OK $T"
  done
  ```
  Expected：6 行 `OK <topic>`。

- [ ] **Step 2：删除 7 条 steal/<topic> 分支（含 freeclaude）**

  Run:
  ```bash
  for T in ai-customer-support-agent freeclaude learn-likecc opus-mind prompt-engineering-models steering-log zubayer-multi-agent-research; do
    git branch -D "steal/$T" && echo "OK $T"
  done
  ```
  Expected：7 行 `OK <topic>`，每行前会有 `Deleted branch steal/<topic> (was <sha>).`。若 git 反对删除（"not fully merged"），检查是否 push 未完成（Phase C 遗漏）。archive tag 在的情况下可用 `git branch -D` 强删（已是 `-D` 不是 `-d`，强制）。

- [ ] **Step 3：确认本次范围内的 steal/* 消失、-old 仍在**

  Run:
  ```bash
  for T in ai-customer-support-agent freeclaude learn-likecc opus-mind prompt-engineering-models steering-log zubayer-multi-agent-research; do
    E=$(git rev-parse --verify "steal/$T" 2>/dev/null && echo EXIST || echo GONE)
    O=$(git rev-parse --verify "steal/$T-old" 2>/dev/null >/dev/null && echo KEPT || echo MISSING)
    printf "%-40s head=%s old=%s\n" "$T" "$E" "$O"
  done
  ```
  Expected：7 行 `head=GONE old=KEPT`。任何 `head=EXIST` → 该 topic 分支删除失败；任何 `old=MISSING` → 报给主人（不回滚）。

- [ ] **Step 4：确认 steal-<本 7 topic> worktree 全清**

  Run:
  ```bash
  git worktree list | grep -E 'steal-(ai-customer-support-agent|freeclaude|learn-likecc|opus-mind|prompt-engineering-models|steering-log|zubayer-multi-agent-research)$'
  ```
  Expected：空输出。

--- PHASE GATE: D → E ---
- [ ] Deliverable exists: 14 条分支删除、13 个 worktree 移除
- [ ] Acceptance criteria met: rescue/* 全空、本范围 steal/<T> 全空、-old 全在、archive tag 全在
- [ ] No open questions: 无删除失败
- [ ] Owner review: not required

---

## Phase E — 最终校验 & 报告

**目的：生成一份主人可扫一眼确认的终态快照。**

### Task E1：终态快照

**Files:** none

- [ ] **Step 1：worktree 剩余清单**

  Run: `git worktree list`
  Expected：主工作树 + `refactor/worktree-gate-hardening` + 10 个范围外 `steal/*` worktree（`andrej-karpathy-skills`, `eureka`, `flux-enchanted`, `generic-agent`, `loki-skills-cli`, `memto`, `millhouse`, `prompt-language-coach`, `r38-sandbox-retro`, `tlotp-monorepo`, `x1xhlol-system-prompts`）—— 本 plan 不碰这些。

- [ ] **Step 2：相关 ref 状态一览**

  Run:
  ```bash
  echo "== rescue/* (应为空) =="
  git branch --list 'rescue/*' || true
  echo "== 本范围 steal head (应全无) =="
  for T in ai-customer-support-agent freeclaude learn-likecc opus-mind prompt-engineering-models steering-log zubayer-multi-agent-research; do
    git rev-parse --verify "steal/$T" 2>/dev/null && echo "  LEAK steal/$T"
  done
  echo "== 本范围 steal -old (应全在) =="
  for T in ai-customer-support-agent freeclaude learn-likecc opus-mind prompt-engineering-models steering-log zubayer-multi-agent-research; do
    git rev-parse --verify "steal/$T-old" >/dev/null && printf "  KEEP steal/%s-old\n" "$T"
  done
  echo "== archive tag (应全在) =="
  git tag -l 'archive/steal-*-20260419' | sort
  echo "== main vs origin/main =="
  git log --oneline origin/main..main
  echo "== origin/main vs main =="
  git log --oneline main..origin/main
  ```
  Expected：
  - `== rescue/* ==` 下无内容
  - `== 本范围 steal head ==` 下无 `LEAK`
  - `== 本范围 steal -old ==` 下 7 行 `KEEP ...`
  - `== archive tag ==` 下 7 行 `archive/steal-<topic>-20260419`
  - `== main vs origin/main ==` 下空
  - `== origin/main vs main ==` 下空

### Task E2：交付 receipt

**Files:** none

- [ ] **Step 1：输出 Orchestrator 标准 receipt 格式**

  给主人展示：
  ```
  Phase B merged commits:
  | Commit | Topic |
  |--------|-------|
  | <sha>  | merge: steal/ai-customer-support-agent |
  | <sha>  | merge: steal/freeclaude |
  | <sha>  | merge: steal/learn-likecc |
  | <sha>  | merge: steal/opus-mind |
  | <sha>  | merge: steal/prompt-engineering-models |
  | <sha>  | merge: steal/steering-log |
  | <sha>  | merge: steal/zubayer-multi-agent-research |

  Pushed to: origin/main (Phase C)
  Removed worktrees: 7 rescue + 6 steal
  Deleted branches: 7 rescue + 7 steal (含 freeclaude 无-worktree 裸分支)
  Preserved: 7 archive/steal-*-20260419 tag, 7 steal/<topic>-old 分支
  ```
  SHA 从 `git log --oneline origin/main..main`（Phase C Step 2 运行前的快照）或 Phase C push 之后的 reflog (`git reflog main | head -20`) 取。

--- PHASE GATE: E → Done ---
- [ ] Deliverable exists: Phase E Step 1 全部 expected 命中
- [ ] Acceptance criteria met: 终态匹配 plan Goal
- [ ] No open questions
- [ ] Owner review: not required（已有 receipt）

---

## Rollback Guide（仅参考，不在 plan 默认流程内）

如果 Phase B 某个 merge 之后发现不对，尚未 push（Phase C 前）：

- 撤销最后一个 merge：`git reset --hard HEAD~1` （**注意：CLAUDE.md 规定 rollback 需主人明确授权，即便在 plan 执行里也要先备份 `git diff HEAD~1..HEAD > /tmp/merge-rollback.patch` 再执行**）

如果 Phase C push 之后发现不对：

- 不做 `git push --force`。按仓库惯例发一个 revert commit：`git revert -m 1 <merge-sha>`，然后正常 push。

如果 Phase D 删错了分支：

- archive tag 全在时零丢失：`git branch rescue/<topic> archive/steal-<topic>-20260419` 或 `git branch steal/<topic> archive/steal-<topic>-20260419`，然后 `git worktree add .claude/worktrees/<side>-<topic> <branch>` 重新挂回来。

---

## Self-Review 结果

**1. Spec coverage（对照 compare 报告建议 §132-153）：**
- "以 steal/<topic> 为准走正常 pipeline 合回 main" → Phase B 全部覆盖 ✓
- "rescue/<topic> 分支可回收" → Task D2 ✓
- "禁止区继续禁止（archive tag 保留、steal/<topic>-old 保留）" → Task D1 Step 1/2 验证 + 明确不在 delete 列表 ✓
- "主人决定 7 个 topic 合并顺序（或分批、或打包）" → Assumption 记录为字母序 ✓
- "每条 steal/<topic> 走 fast-forward 或 squash merge 的惯例" → Assumption 改为 `--no-ff`（FF 不可能，仓库历史是 --no-ff）✓
- "合入后 `steal/<topic> → steal/<topic>-old` 归档、worktree remove" → 调整为「直接删（tag 已是 archive）」，Assumption 说明 ✓

**2. Placeholder scan：** 搜索 "TBD", "TODO", "fill in", "etc", "similar to", "refactor" 单独出现、"clean up" 单独出现、"optimize" 单独出现 —— plan 中无命中。每个 Phase D 的 for-loop 都写出了完整命令体，不是 "same as above"。

**3. Type/名称一致性：** 7 个 topic 名字在 Phase A/B/D/E 完全一致。`archive/steal-<topic>-20260419` 格式一致。`steal/<topic>-old` 格式一致。`.claude/worktrees/<side>-<topic>` 路径一致。

**4. Step count：** A1-A3=5 步、B1-B8=22 步、C1-C2=3 步、D1-D3=9 步、E1-E2=2 步。总计 **41 步**，超过 plan_template 建议的 30 步上限。理由：B 阶段 7 topic × 3 步 = 21 步不可压缩（每个 merge 是独立原子操作、独立 verify），D 阶段的 3 个大 Task 已经用 for-loop 把 14 条分支 + 13 个 worktree 压成 3 次循环。接受超标。

---

## 下一步

Plan 已完成。**由于本 plan 涉及不可逆的 `git push origin main`（即 Gate 2: Plan → Implement 要求 Owner review），按 CLAUDE.md 约定不自动进入 subagent-driven 执行。主人 review 这份 plan，说 "开干" 或 "按这个执行" 之后再进入 Phase A。**
