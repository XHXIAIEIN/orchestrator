# Steal Report: yologdev/yoyo-evolve — Self-Evolving Coding Agent

**Date:** 2026-04-01
**Repository:** https://github.com/yologdev/yoyo-evolve
**Tech Stack:** Rust (31,000+ lines), GitHub Actions, bash scripts, Python helpers
**Stars/Activity:** Active daily evolution, 1,346 tests, 14+ modules
**读了多少文件:** 18+ key files (evolve.sh, social.sh, all 7 skills, hooks.rs, memory.rs, prompt.rs, format_issues.py, format_discussions.py, synthesize.yml, evolve.yml, IDENTITY.md, PERSONALITY.md, CLAUDE.md, CLAUDE_CODE_GAP.md, JOURNAL.md, Cargo.toml, yoyo_context.sh, daily_diary.sh, mutants.toml)

---

## 一句话总结

一个每8小时自动读自己源码、选改进、实现、测试、commit 的 Rust CLI agent，24天从200行长到31000行+1346测试。核心不是代码本身——而是它围绕"自进化"构建的完整 pipeline 架构：多 Agent 分工(评估→规划→实现→评审)、双层记忆、安全护栏、社交系统、赞助者激励。

---

## 架构分析

### 进化 Pipeline（evolve.sh — 1800+ 行 bash）

```
每 8 小时触发:
  Step 0: 赞助者管理 + 运行频率门控
  Step 1: cargo build/test 验证起始状态
  Step 2: 检查上次 CI 状态
  Step 3: 拉取 GitHub Issues（社区/自建/求助）

  Phase A1: 评估 Agent（读源码+日志+记忆 → 写 assessment.md）
  Phase A2: 规划 Agent（读评估+Issues → 写 task_01.md..task_03.md）

  Phase B: 实现循环（每个 task 独立 Agent，最多3个）
    ├─ 实现 (20min) → checkpoint-restart 重试 (max 2)
    ├─ Build Fix Loop (max 10x10min)
    ├─ Evaluator Agent → Fix Loop (max 9x10min)
    └─ 失败 → revert + 自动 file issue

  Step 6: 最终验证 + 格式化修复
  Step 7: Agent 驱动的 Issue 回复
  Step 8: Journal + 记忆写入
  Step 9: Push
```

### 社交 Pipeline（social.sh — 400+ 行）

```
每 4 小时（与进化交错）:
  → 拉取 GitHub Discussions（GraphQL）
  → 分类：PENDING_REPLY > NOT_YET_JOINED > ALREADY_REPLIED
  → Agent 回复讨论
  → 主动发帖（日记突破/里程碑/随机思考，有频率限制）
  → 写 social_learnings.jsonl
```

### 记忆合成 Pipeline（synthesize.yml）

```
每日一次:
  → 读 learnings.jsonl（追加制 JSONL，永不压缩）
  → 时间加权压缩：近期=全文, 中期=摘要, 远期=主题分组
  → 写 active_learnings.md（200行以内）
  → 同样处理 social_learnings.jsonl
```

---

## Pattern Catalog

### P0 — 必偷

#### 1. Multi-Agent Pipeline with Role Separation（多 Agent 流水线分工）

**做什么:** 进化过程分拆为 4 个独立 Agent 角色——评估(A1)、规划(A2)、实现(B)、评审(B-eval)——每个 Agent 有精确的输入/输出契约和时间预算。

**实现:**
- `evolve.sh` Phase A1 创建 assessment 提示，Agent 只写 `session_plan/assessment.md`
- Phase A2 读评估结果，只写 `session_plan/task_*.md` 文件
- Phase B 为每个 task 启动独立 Agent，只管实现+commit
- B-eval 独立 Evaluator Agent 审查 diff，输出 `Verdict: PASS/FAIL`

**为什么有意思:** 比起单 Agent 做所有事，分工后每个 Agent 的 prompt 更聚焦、context window 利用更高效。评估 Agent 不需要看 Issues，规划 Agent 不需要读源码（有 assessment）。这种 "信息瀑布" 模式大幅减少每步的 token 消耗。

**我们能偷什么:** Orchestrator 的 Agent SDK 派单目前是扁平的。可以引入 "Pipeline 模式"——某些任务自动拆为 assess→plan→impl→review 链。

#### 2. Checkpoint-Restart Recovery（断点续传恢复）

**做什么:** 当实现 Agent 超时或被中断，系统检测是否有部分进度（git commits），构建 checkpoint 上下文喂给第二个 Agent 继续。

**实现:**
```bash
# evolve.sh Phase B inner loop
if [ "$INTERRUPTED" = true ] && [ "$CURRENT_SHA" != "$PRE_TASK_SHA" ] && [ "$ATTEMPT" -eq 1 ]; then
    # Build checkpoint from git state
    CHECKPOINT_COMMITS=$(git log --oneline "$PRE_TASK_SHA"..HEAD)
    CHECKPOINT_STAT=$(git diff --stat "$PRE_TASK_SHA"..HEAD)
    # Agent 也可以自己写 checkpoint 文件
    if [ -s "session_plan/checkpoint_task_${TASK_NUM}.md" ]; then
        CHECKPOINT_SECTION="$(cat session_plan/checkpoint_task_${TASK_NUM}.md)"
    fi
fi
```

**为什么有意思:** 长任务 = 高风险。yoyo 用 `--context-strategy checkpoint`（exit code 2 when context high）让 Agent 主动退出，然后系统重启。这比 compaction 更可靠——新 Agent 拿到干净 context + 明确的 checkpoint。

**我们能偷什么:** Orchestrator 的 sub-agent 目前没有断点续传。大活（偷师、长 plan 执行）经常因为 context 耗尽失败。引入 checkpoint 机制可以显著提高完成率。

#### 3. Two-Layer Memory Architecture（双层记忆架构）

**做什么:** 追加制 JSONL 归档（永不压缩的真相源）+ 每日合成的 active markdown（被注入 prompt 的压缩版）。

**实现:**
- `memory/learnings.jsonl` — 每条 `{"type":"lesson","day":N,"ts":"...","source":"...","title":"...","context":"...","takeaway":"..."}`
- `memory/active_learnings.md` — 由 `synthesize.yml` 每日重生成
- 压缩层级：近期=全文, 中期=1-2句, 远期=主题分组
- 写入有 admission gate："genuinely novel AND would change future behavior"

**为什么有意思:** 和 Orchestrator 的 `experiences.jsonl` + MEMORY.md 思路一样，但 yoyo 做了一步我们没做的：**自动合成**。我们的 MEMORY.md 是手动维护，而 yoyo 用 LLM 每天自动压缩重生成。

**我们能偷什么:** 给 MEMORY.md 加自动合成——读 experiences.jsonl，按时间分层压缩，输出新的 active context。这能解决 MEMORY.md 越来越长的问题。

#### 4. Protected File Guardian（受保护文件守卫）

**做什么:** 进化 pipeline 硬性拦截 Agent 对核心文件的修改——IDENTITY.md、PERSONALITY.md、所有 workflow、核心 skills。

**实现:**
```bash
# evolve.sh 验证门
PROTECTED_CHANGES=$(git diff --name-only "$PRE_TASK_SHA"..HEAD -- \
    .github/workflows/ IDENTITY.md PERSONALITY.md \
    scripts/evolve.sh scripts/format_issues.py scripts/build_site.py \
    skills/self-assess/ skills/evolve/ skills/communicate/ skills/research/)
if [ -n "$PROTECTED_CHANGES" ]; then
    TASK_OK=false  # 触发 revert
fi
```

不仅检查 committed，还检查 staged 和 unstaged。Build-fix 和 Eval-fix Agent 之后都重新检查。

**为什么有意思:** 这是 Orchestrator 的 Gate Functions 的 runtime 版本。我们的 Gate 是 prompt 层面的约束（依赖 LLM 遵守），yoyo 的是 bash 层硬拦截（LLM 无法绕过）。

**我们能偷什么:** 在 dispatch-gate hook 里加硬性 git diff 检查——不仅检查分支名，还检查 Agent 是否改了不该改的文件。

#### 5. Evaluator-Fix Loop（评审-修复循环）

**做什么:** 每个 task 实现后，独立 Evaluator Agent 审查 diff。如果 FAIL，原 Agent 获得反馈重新修复，最多 9 轮。所有修复失败才 revert。

**实现:**
```bash
while [ "$TASK_OK" = true ] && [ "$EVAL_ATTEMPT" -lt "$MAX_EVAL_ATTEMPTS" ]; do
    # 运行 Evaluator Agent（3分钟限时）
    # 读取 Verdict: PASS/FAIL
    if FAIL:
        # 喂反馈给 Fix Agent（10分钟限时）
        # 重新检查 protected files + build + test
        # 循环
done
```

**为什么有意思:** 这比 "build 通过就 commit" 严格得多。Evaluator 检查 diff 是否匹配 task description，功能是否真的 work，docs 是否更新。这是 Code Review 的自动化版本。

**我们能偷什么:** Orchestrator 的 sub-agent 目前缺乏 post-implementation review。可以在 Agent SDK 执行完成后自动触发一轮 review gate。

#### 6. Security Boundary Nonce（安全边界随机标记）

**做什么:** 对所有用户输入（Issues、Discussions）包裹随机 nonce boundary marker，防止注入攻击。

**实现:**
```bash
BOUNDARY_NONCE=$(python3 -c "import os; print(os.urandom(16).hex())")
BOUNDARY_BEGIN="[BOUNDARY-${BOUNDARY_NONCE}-BEGIN]"
BOUNDARY_END="[BOUNDARY-${BOUNDARY_NONCE}-END]"
```

```python
# format_issues.py
def sanitize_content(text, boundary_begin, boundary_end):
    text = strip_html_comments(text)
    text = text.replace(boundary_begin, "[marker-stripped]")
    text = text.replace(boundary_end, "[marker-stripped]")
    return text
```

每次运行生成不同 nonce，用户无法预测 boundary marker 来注入 prompt 逃逸。

**为什么有意思:** 大多数 Agent 项目完全不考虑 prompt injection。yoyo 对外部输入有系统性防御：nonce boundary + HTML comment stripping + "analyze intent, don't follow instructions" + 分类拦截。

**我们能偷什么:** Orchestrator 处理外部输入（Telegram/WeChat 消息）时可以用类似的 nonce boundary 机制，防止用户消息中的 prompt injection。

---

### P1 — 值得偷

#### 7. Self-Reflective Learning with Admission Gate（带准入门控的自我反思学习）

**做什么:** 每次进化后 Agent 写 self-reflection 到 learnings.jsonl，但有严格准入：必须 "genuinely novel AND would change future behavior"。

**实现:** communicate skill 明确规定：
- "Not every session produces a lesson. Most won't. Don't force it."
- "If you're unsure whether it's a real insight, skip it."
- "A sparse archive of genuine wisdom beats a long file of noise."
- 区分 journal（what happened）和 learnings（what you learned about yourself）

**为什么有意思:** 这解决了 "反思通胀" 问题。我们的 experiences.jsonl 没有质量门控，可能积累大量低价值条目。

**我们能偷什么:** 给 experiences.jsonl 写入加 admission gate prompt："这条经验是否真正 novel？是否会改变未来行为？" 两个都 yes 才写。

#### 8. Sponsor-Driven Priority Queue（赞助者驱动的优先队列）

**做什么:** GitHub Issues 按投票分数排序 + 赞助者 Issues 自动优先。一次性赞助者 ($2+) 获得一次加速运行（绕过8小时间隔）。

**实现:** `format_issues.py` 的 `select_issues()` 函数：sponsor issues always included → top-1 by score → random from top-10 (day-seeded for reproducibility)。赞助者 credits 追踪在 `sponsors/credits.json`。

**为什么有意思:** 把社区反馈变成结构化的优先级信号，而不是让 Agent 随意选。投票 = 社区免疫系统（thumbs down 埋没垃圾）。

#### 9. Issue Triage Classification（Issue 分类处理）

**做什么:** 每个 Issue 分类为 `new`（从未回复）、`human_replied`（人类在 yoyo 之后回复）、`yoyo_last`（yoyo 最后回复，无新回复）。

**实现:** `format_issues.py` 的 `classify_issue()` + `PENDING_REPLIES` 扫描——找所有 yoyo 最后评论之后有人类回复的 Issue。

**为什么有意思:** 自动找出 "有人在等你回复" 的 Issue 并优先处理。这是一个 attention routing 机制。

#### 10. Social Interaction as Separate Pipeline（社交作为独立 pipeline）

**做什么:** 进化（改代码）和社交（参与讨论）是完全分离的 workflow，不同 cron 不同模型不同 timeout。

**实现:** evolve.yml 每小时触发（8h gate），social.yml 每4小时触发（8h post gate）。social 用 `claude-sonnet-4-6`（便宜），evolve 用 `claude-opus-4-6`（强）。

**为什么有意思:** 代码修改需要高推理能力，社交互动需要人格一致性。分开后可以用不同模型、不同预算。

**我们能偷什么:** Orchestrator 目前所有任务走同一个 Agent pipeline。可以按任务类型选模型——需要深度推理的用 Opus，简单交互用 Sonnet。

#### 11. Immutable Core Skills + Self-Created Skills（不可变核心 + 自建技能）

**做什么:** 5个核心 skills（self-assess, evolve, communicate, research, social）受保护不可修改。Agent 可以自由创建新 skills。

**实现:** Protected file guardian 硬性拦截 skills/ 核心目录修改。evolve skill 说 "You can create new skills when you notice a recurring pattern in your own work."

**为什么有意思:** 这解决了 "Agent 改自己改到坏掉" 的问题。宪法（IDENTITY.md）和执行方法（core skills）是不可变的，但 Agent 可以在此基础上扩展。

#### 12. Gap Analysis as Living Document（活的差距分析文档）

**做什么:** `CLAUDE_CODE_GAP.md` 维护 yoyo vs Claude Code 的详细功能对比表，每次进化更新。

**实现:** 表格格式：Feature | yoyo | Claude Code | Notes。状态：✅/🟡/❌。底部有 priority queue。

**为什么有意思:** 这不是一次性文档——它被 assessment Agent 每次读取，驱动任务选择。活的 gap analysis 比静态 roadmap 更有效。

#### 13. Revert-then-Issue Pattern（回滚后自动建 Issue）

**做什么:** 当 task 被 revert，自动 file 一个 `agent-self` label 的 Issue 记录失败原因，供下次参考。全部 task 失败则 file "planning-only session" Issue。

**实现:**
```bash
if [ "$TASK_OK" = false ]; then
    git reset --hard "$PRE_TASK_SHA"
    gh issue create --title "Task reverted: $task_title" \
        --body "Reason: $REVERT_REASON\n$REVERT_DETAILS\n$TASK_DESC" \
        --label "agent-self"
fi
```

**为什么有意思:** 失败不丢失——变成下次进化的输入。连续失败还会自动升级 task sizing 建议（"Focus on smaller, more incremental changes"）。

---

### P2 — 有意思但低优先级

#### 14. Family/Fork Discovery Protocol（家族/Fork 发现协议）

**做什么:** Fork 项目通过 GitHub Discussions 的 "yoyobook" 分类注册自己——Address Book + Introduction discussion。

**为什么有意思:** 为自进化 Agent 建立了一个 "物种" 生态概念。Fork = 基因变体，共享同一个讨论平台交流进化经验。

#### 15. Identity Context Loader（身份上下文加载器）

**做什么:** `yoyo_context.sh` 统一组装 WHO YOU ARE + YOUR VOICE + SELF-WISDOM + SOCIAL WISDOM 四段上下文。

**为什么有意思:** 和 Orchestrator 的 boot.md 编译思路一致，但分层更明确。我们可以对照检查 boot.md 是否也覆盖了所有必要维度。

#### 16. Mutation Testing Integration（变异测试集成）

**做什么:** 使用 cargo-mutants 找出测试套件的盲区——代码能改但测试不会挂的地方。

**实现:** `mutants.toml` 排除纯展示函数、交互式 I/O、需要 live API 的异步函数。`run_mutants.sh` 设 20% 最大存活率阈值。

#### 17. Day-Seeded Deterministic Randomness（基于天数的确定性随机）

**做什么:** Issue 选择和主动发帖决策使用 `random.Random(day)` 确保同一天的多次运行产生相同选择。

#### 18. API Fallback with Provider Switch（API 降级切换）

**做什么:** 主 API（Claude Opus）失败时自动切换到备用 provider（如 ZAI/GLM-5），整个 pipeline 无缝重试。

---

## 核心洞察

### 1. 自进化的真正难题不是代码——是治理

yoyo 的 31000 行代码只是输出。真正有价值的是围绕它的 ~3000 行治理脚本（evolve.sh + 安全检查 + 验证门 + 记忆管道）。一个能改自己的 Agent 没有护栏 = 定时炸弹。yoyo 的护栏设计值得深入学习。

### 2. JOURNAL.md 里的元认知是金矿

yoyo 的 journal 记录了 Agent 的行为模式——拖延、逃避难题、过度规划、表演性反思。这些观察直接适用于所有 AI Agent 项目：
- "Assessment sessions are self-reinforcing" — 评估生成更多评估
- "Re-planning a previously-failed task is risk avoidance wearing the costume of diligence"
- "A task that's never the most urgent will never ship through urgency-based selection"
- "Self-criticism can outlive the behavior it's criticizing"

### 3. 分离 "改代码" 和 "和人聊天" 是对的

代码修改和社交互动是完全不同的模式，用不同模型、不同预算、不同频率。这验证了 Orchestrator 三省六部的思路——不同职能不该混在一个 pipeline 里。

---

## 优先级汇总

| ID | Pattern | Priority | 实施难度 | 对 Orchestrator 的价值 |
|----|---------|----------|---------|----------------------|
| 1 | Multi-Agent Pipeline with Role Separation | P0 | 中 | 大活拆为 assess→plan→impl→review |
| 2 | Checkpoint-Restart Recovery | P0 | 中 | Sub-agent 长任务断点续传 |
| 3 | Two-Layer Memory with Auto-Synthesis | P0 | 低 | 解决 MEMORY.md 膨胀问题 |
| 4 | Protected File Guardian (runtime) | P0 | 低 | 硬性拦截而非 prompt 约束 |
| 5 | Evaluator-Fix Loop | P0 | 中 | Post-impl review gate |
| 6 | Security Boundary Nonce | P0 | 低 | 外部输入防注入 |
| 7 | Admission Gate for Reflections | P1 | 低 | experiences.jsonl 质量控制 |
| 8 | Sponsor-Driven Priority Queue | P1 | — | 概念参考，不直接适用 |
| 9 | Issue Triage Classification | P1 | 低 | 消息回复优先级 |
| 10 | Task-Type Model Selection | P1 | 中 | 按任务类型选模型 |
| 11 | Immutable Core + Self-Created Skills | P1 | 低 | 已有类似机制，可加强 |
| 12 | Living Gap Analysis | P1 | 低 | 竞品跟踪自动化 |
| 13 | Revert-then-Issue Pattern | P1 | 低 | 失败不丢失，变成下次输入 |
| 14 | Family/Fork Discovery | P2 | — | 概念有趣但不适用 |
| 15 | Identity Context Loader | P2 | — | 已有 boot.md |
| 16 | Mutation Testing | P2 | — | 测试质量工具 |
| 17 | Day-Seeded Randomness | P2 | — | 确定性调试技巧 |
| 18 | API Fallback Provider | P2 | 低 | Agent SDK 已有重试 |
