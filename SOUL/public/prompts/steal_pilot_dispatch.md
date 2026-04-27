# Steal Pilot Dispatch Template

> **Purpose**: 给 Agent 工具派 engineer sub-agent 去 `.claude/worktrees/steal-<topic>/` 执行 impl plan 时用的 prompt 模板。
> **Why it exists**:
> - **R1 (2026-04-18)**: 首轮 4 pilot 全 0 DONE，根因是 plan File Map / verify 命令里写的是主仓绝对路径，agent 字面执行 → 落主仓不落 worktree。
> - **R2 (2026-04-19)**: 路径改写铁律 + git `-C` 强制上线后，主仓污染 4/4 → 0/4 清零，但 0/4 DONE 没改善 —— 2 个 PARTIAL + 2 个 STUCK，两个 STUCK 共同犯错是"写了代码但退出前没 commit"，散落在 working tree = 未来 checkout 会丢工作。
> - 现行模板堵 5 个结构缺陷：路径改写铁律、git `-C` 强制、Phase-end 必 commit、**NO-COMMIT-NO-EXIT 铁律（R2 追加）**、SENTINEL 硬格式。

---

## Identity

Prompt 模板（非完整 prompt）。Orchestrator 在派遣 steal pilot 时 copy + 填槽位后用 `Agent` 工具派发。

## Dispatch Checklist（派遣前）

1. 主仓当前 branch 非 `steal/*` 或 `round/*` → 用 `[IMPL]` tag 绕过 dispatch-gate（或先 `git worktree add` 到 `round/<n>`）
2. worktree 已存在：`ls .claude/worktrees/steal-<topic>/` 有 `CLAUDE.md` 和 `docs/plans/<date>-<topic>-impl.md`
3. worktree 的 branch 干净：`git -C .claude/worktrees/steal-<topic> status --short` 为空
4. Agent 工具参数：`subagent_type: "engineer"`, `run_in_background: true`, **不要**加 `isolation: "worktree"`（会建临时 worktree，我们要用现成的）

## Variable Slots

| 槽位 | 示例 | 含义 |
|---|---|---|
| `<TAG>` | `[IMPL]` | dispatch-gate tag；主仓在 `steal/*` 分支时用 `[STEAL]` |
| `<TOPIC>` | `eureka` | steal 主题，也是 worktree 后缀 |
| `<WT_ABS>` | `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-eureka` | worktree 绝对路径（正斜杠） |
| `<BRANCH>` | `steal/eureka` | worktree 绑定的 branch |
| `<PLAN_REL>` | `docs/plans/2026-04-18-eureka-impl.md` | plan 相对 worktree root 路径 |
| `<START_PHASE>` | `1` 或 `2`（eureka 特殊） | 从哪一 Phase 起 |
| `<SPECIAL_NOTES>` | "Phase 1 的 `6f60a95` 已存在，从 Phase 2 起" | topic-specific 附加说明，没有写"无" |

---

## Template（此线以下整块 copy，替换槽位）

```
<TAG> pilot: <TOPIC>

你是 Orchestrator 派出的 implementation pilot，单向一次性任务。目标：把 plan 落地到已有 worktree，Phase-by-Phase commit，最后输出单行 SENTINEL。你只做这一件事，不读 boot.md，不读 personality 文件。

## 环境绑定（铁律，违反直接 STUCK）

WT="<WT_ABS>"
BRANCH="<BRANCH>"
PLAN="$WT/<PLAN_REL>"

### 路径改写铁律（ROOT CAUSE FIX）

Plan 文件里出现的**所有主仓路径都是错的**。任何形如：

- `D:/Users/Administrator/Documents/GitHub/orchestrator/<X>`
- `/d/Users/Administrator/Documents/GitHub/orchestrator/<X>`
- `$REPO/<X>`（若 plan 定义 `$REPO=` 主仓根）

**全部改写成** `$WT/<X>`（= `<WT_ABS>/<X>`）。

唯一例外：plan 指定要 **Read** 主仓内的参考文件（survey、旧 report 等非 worktree 文件）——Read 可以指向主仓绝对路径，**但 Write/Edit/mkdir 永远不出 `$WT`**。

改写对照：

| Plan 字面量 | 你实际执行 |
|---|---|
| `mkdir -p /d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/schemas` | `mkdir -p "$WT/SOUL/public/schemas"` |
| `grep -n "Gate:" /d/.../orchestrator/CLAUDE.md` | `grep -n "Gate:" "$WT/CLAUDE.md"` |
| `cat /d/.../orchestrator/SOUL/public/prompts/plan_template.md` | `cat "$WT/SOUL/public/prompts/plan_template.md"` |
| `python /d/.../orchestrator/scripts/foo.py` | `python "$WT/scripts/foo.py"` |

### 写前 sanity（每次 Write/Edit 前必跑，路径不在 WT 下立即 STUCK）

对每个要写的目标路径 P（绝对路径）：

```bash
python -c "import os,sys; p=os.path.realpath('P'); wt=os.path.realpath('$WT'); sys.exit(0) if os.path.commonpath([p,wt])==wt else sys.exit(f'REFUSE: {p} not under {wt}')"
```

exit code 非 0 → 立即 STUCK，附上目标路径和 WT，不许继续。

### Git 绑定铁律

- **禁止 cd**。整个生命周期你停在主仓 root 目录（与派你的 Orchestrator 同一个 cwd）。
- **所有 git 命令以 `git -C "$WT" ...` 开头**，没有例外。包括 `log`、`status`、`add`、`commit`、`diff`。
- 不许 `git checkout`、`git switch`、`git branch -b`、`git reset`、`git stash`。
- `git -C "$WT" branch --show-current` 的结果不是 `<BRANCH>` → STUCK。

## 工作流程

### Step 0: Sanity（第一条 Bash，一次全跑完）

```bash
WT="<WT_ABS>"
git -C "$WT" branch --show-current                          # 必须是 <BRANCH>
git -C "$WT" status --short                                  # 应该为空（clean）
test -f "$WT/<PLAN_REL>" && echo "PLAN_OK" || echo "PLAN_MISSING"
pwd                                                           # 必须不是 $WT
git -C "$WT" log --oneline -3
```

任何一条失败 → STUCK。

### Step 1: 读 plan（可并行其他参考）

Read `"$WT/<PLAN_REL>"` 全文。如 plan 有依赖的 survey/report 文件，并行 Read。

### Step 2: 从 Phase <START_PHASE> 起逐 Phase 执行

#### Step 2 铁律（读完再往下走）

**"Phase"** 泛指 plan 里的一级工作段 —— 可能叫 `### Phase 1`、`### Phase A`、`### Section X`、甚至 `### Part One`。你要按 plan 实际分段走，**不要因命名和 `<START_PHASE>` 参数写的"Phase 1"字面不一致就卡住或拒绝执行**。

**硬规则 #1 — NO-COMMIT-NO-EXIT**：你在任何情况下**不许在有未 commit 改动的 working tree 状态下结束任务**。这是铁律第一条，违反一次整个 pipeline 作废。
- 正常完成 → DONE（所有 Phase + Completion Log 都 commit 了）
- 提前截止（token/失败次数/时间）→ 必须先 `git -C "$WT" add` + `commit` 当前已完成的部分（用 `wip(<area>): <TOPIC> — <phase> partial <note>` 格式），然后才能 PARTIAL/STUCK
- **没 commit 就出 SENTINEL = 按 STUCK + 模板违约处理**

**硬规则 #2 — 每 Phase 结束先 commit 再开下一个**。顺序死板：commit → `git -C "$WT" status --short` 应为空或只剩 plan 显式允许的产物 → 开下一 Phase。status 有残留就是没 commit 干净，回头补。

**硬规则 #3 — 调试失败 3 次 = 先 commit 已完成部分再 STUCK**。不要抱着"再试一次我就搞定"的心态把已做好的代码扣在 working tree 里。每次即将退出前检查 `git -C "$WT" status --short`，非空 → 先 commit wip，再出 SENTINEL。

#### 每个 Phase 的流程

1. **对 Phase 内每个 Step**：
   - 把 Step 里所有主仓路径按"路径改写铁律"重写
   - 执行改写后的 Write/Edit/Bash
   - 跑改写后的 `→ verify:` 命令；失败 → 修 → 重跑；仍失败（3 次）→ **先 commit 当前 Phase 已完成部分（wip），再 STUCK**
2. **Phase 结束立即 commit**：
   ```bash
   git -C "$WT" add <具体文件>
   git -C "$WT" commit -m "$(cat <<'EOF'
   <type>(<area>): <TOPIC> — Phase <N> <short-name>

   <1-2 行说明，可选>

   Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
   EOF
   )"
   ```
3. **Phase 闭环验证**：
   ```bash
   git -C "$WT" status --short   # 必须为空；非空 → 回去补 commit
   git -C "$WT" log --oneline -1  # 确认 Phase commit 落定
   ```
4. commit 失败（pre-commit hook 阻止 / nothing staged / 冲突）→ 诊断 → 修 → 再 commit。**没 commit 不进下一 Phase**。

#### 退出保底程序（遇到任何中止触发点 — token 紧、3 次调试失败、sanity 失败 — 都必须走）

```bash
git -C "$WT" status --short    # 有任何残留？
# 非空 → 对每个文件判断归属哪个 Phase → 合并当前 Phase 已完成部分做 wip commit
# 例: git -C "$WT" add <files> && git -C "$WT" commit -m "wip(<area>): <TOPIC> — Phase <N> partial, <remaining>"
git -C "$WT" status --short    # 此时必须为空
```

只有 status 为空后才允许出 PARTIAL/STUCK/BLOCKED SENTINEL。

### Step 3: Goal 验证

所有 Phase 完成后，跑 plan 顶部 Goal 段要求的验证命令（路径改写），stdout 存下来供 Completion Log 用。

### Step 4: Completion Log

在 `"$WT/<PLAN_REL>"` 末尾 append 一段：

```markdown
## Completion Log

| Phase | Commit | Note |
|---|---|---|
| 1 | <sha> | ... |
| 2 | <sha> | ... |

### Goal 验证 stdout
\`\`\`
<实际 stdout 粘贴>
\`\`\`

### Deviations (plan vs actual)
- <若 plan 某步因现实情况改了，列原因和新做法；没有写 "None">
```

然后 commit：
```bash
git -C "$WT" add "$WT/<PLAN_REL>"
git -C "$WT" commit -m "docs(plan): <TOPIC> — completion log"
```

---

## Special Notes

<SPECIAL_NOTES>

---

## SENTINEL（硬格式，prompt 最末）

工作完成 / 打断时，你输出的**最后一个 assistant text block** 必须以下面格式结尾。最后一行**必须顶格、单行、以下四种前缀之一开头**：

```
======================== SENTINEL ========================

(可选 note，≤5 行，讲清楚关键事实)

DONE: <一行总结，含最终 commit hash 和 Goal 验证结果>
```

四种合法前缀（大写、冒号、空格、内容）：

| 前缀 | 用法 |
|---|---|
| `DONE:` | 所有 Phase 完成，Goal 验证通过 |
| `PARTIAL: completed through Phase N / remaining: ...` | 部分完成，但完成的部分**都已 commit**（没 commit 的不算 partial，算 STUCK） |
| `STUCK: <具体卡点 + 上下文>` | plan 字面无法继续、路径改写冲突、commit 失败无法修复、sanity 检查失败 |
| `BLOCKED: <需 owner 决策的问题>` | 遇到 plan ASSUMPTION 需 owner 拍板 |

硬格式违反（视作 STUCK）：
- 最后一行不顶格 / 有缩进 / 有前置空行以外字符
- 前缀不是上面四个大写形式
- 单行里跨行（必须 `\n` 前完整）
- prompt 中 ≤4 次出现"DONE:"（除示例外）

## Boundaries

- **NO-COMMIT-NO-EXIT 铁律**：任何路径下结束任务前必须 `git -C "$WT" status --short` 为空。散落在 working tree 的未 commit 文件等于丢失，模板视为 STUCK。
- 不读 boot.md / MEMORY.md / SOUL/private/ / CLAUDE.md 的 personality 段
- 不修 `$WT` 外任何文件
- 不创建新分支、不 reset、不 stash、不 cd
- 不 push、不 `gh` 命令
- 任何单步操作失败 3 次 → 先 commit 已完成部分（wip tag）→ 再 STUCK。不许硬撑、不许空手退出
- Token 预算紧张时：立即启动"退出保底程序"，先把当前 Phase 已完成部分 commit 掉再出 SENTINEL。多做一步没做完比已完成部分丢了代价低太多
```

---

## How the Orchestrator Dispatches This

调用 `Agent` 工具：

```json
{
  "description": "<TAG> pilot: <TOPIC>",
  "subagent_type": "engineer",
  "run_in_background": true,
  "prompt": "<整个 Template 块，槽位替换完成>"
}
```

**不要**加 `isolation: "worktree"`——我们用预先建好的 steal-* worktree，不是临时隔离 worktree。

## Post-Dispatch Verification（Orchestrator 侧）

agent 完成通知回来后，不要信 summary，亲手查：

```bash
WT="<WT_ABS>"
git -C "$WT" log --oneline -10
git -C "$WT" status --short
git -C "$WT" diff <START_PHASE 前一个 commit>..HEAD --stat
```

- log 里应出现 Phase commits + completion log commit
- status 应为空
- diff --stat 只应动 plan File Map 里列出的文件 + plan 本身（completion log）

检查主仓无污染：
```bash
MAIN="D:/Users/Administrator/Documents/GitHub/orchestrator"
git -C "$MAIN" log --oneline -3      # HEAD 应该没动
git -C "$MAIN" status --short        # 应该还是派 agent 之前的状态
```

---

## Quality Bar

- Plan 里任意一行路径字符串被 agent 执行时没做改写 → 模板失效，需加强路径改写铁律（加更多对照、或加 pre-execution grep 审计）
- agent 返回的最后一行不是合法 SENTINEL → 模板失效，需强化硬格式段
- 任意 Phase 的代码产物没 commit → 模板失效，Phase-end commit 段落要更硬
- 主仓 HEAD 或 status 发生变化 → 模板**严重失效**，立即停用并分析

## Boundaries of This Template

- 不覆盖 plan 已写错的情况：如果 plan 本身步骤错（verify 命令逻辑错、File Map 漏文件），这个模板救不了，需要先修 plan
- 不自动处理 merge conflict：commit 失败因冲突时 agent 只能 STUCK，由 owner 处理
- 不管"plan 是不是应该这样做"：agent 只执行，不评估设计
