# Plan: Scaffolding Prune (Opus 4.7 Era Adjustment)

> Date: 2026-04-17
> Trigger: Opus 4.7 内化了大量旧时代教学性提示；部分脚手架从"加分项"变成"双重消耗"。盘点全部 83 个 artifact 后筛出剪枝候选。
> Priority: P2（不阻塞功能，但每个会话都在消耗 token 和模型注意力）
> Scope: `.claude/hooks/` + `.claude/commands/` + `CLAUDE.md` + `SOUL/public/prompts/` + `SOUL/public/`

## Goal

将三类 artifact 处理到位，使 Claude Code 脚手架对 Opus 4.7 的 token 开销下降 ≥20%，同时修复一处与 CLAUDE.md 语义冲突的硬性指令：
1. 删除/归档 4 份未落地或已失效的 prompt 模板
2. 修正 1 处 hook 与 CLAUDE.md Git Safety 的语义冲突
3. 瘦身 1 处 CLAUDE.md 教学段落、1 处 hook 注入频率、1 处 slash command 重复

所有被"删除"的文件先 `mv` 到 `.trash/2026-04-17-scaffolding-prune/`，不走真删除。完成后报告 `.trash/` 内容，由 owner 决定最终命运。

## 背景：为什么现在剪

Opus 4.7 默认行为吃掉了以下旧脚手架的价值：
- **多步任务自动 state-plan + verify**（吞掉 CLAUDE.md § Goal-Driven Execution 的教学价值）
- **默认先 Read 再 Edit**（部分吞掉 Surgical Changes § Edit Integrity）
- **更少请示/合理化**（partial 吞掉 rationalization-immunity、stall-detector）
- **工具调用并行化更积极**（吞掉 persona-anchor 每 5 次提醒的必要性）

但仍有大量脚手架是**模型世界外的状态/约束**（Gate Functions、项目特有的 governance pipeline、security hooks），这些不在剪枝范围内。

## File Map

### Phase 1: 高优先级（安全删除 + 冲突修正）

| File | Change | Reason |
|------|--------|--------|
| `SOUL/public/research-sycophancy-split.md` | Move → `.trash/` | 3 行墓碑，指向已迁移到 docs/ 的旧文档 |
| `SOUL/public/prompts/dag_orchestration.md` | Move → `.trash/` | 173 LOC，仅 1 ref（自引），Archon 偷来的模式未接入 Orchestrator 调度 |
| `SOUL/public/prompts/rule_scoping.md` | Move → `.trash/` | 52 LOC，仅 1 ref，`applies_to` 机制从未实现 |
| `SOUL/public/prompts/session_boundary.md` | Move → `.trash/` | 70 LOC，仅 1 ref，未被任何 hook 或 skill 调用 |
| `.claude/hooks/commit-reminder.sh` | Modify (重写 8-20 行) | 与 CLAUDE.md § Git Safety "stage-first, push-later, no auto-commit" 语义冲突 |
| `CLAUDE.md` § Goal-Driven Execution | Modify (15 行 → 3 行指针) | Opus 4.7 默认行为已覆盖，保留一行提醒即可 |

### Phase 2: 中优先级（合并 + 降频 + 评估）

| File | Change | Reason |
|------|--------|--------|
| `.claude/commands/chat.md` | Move → `.trash/` | 与 `bot-tg.md` 功能重复（都是 telegram 消息查询），少一层 client 过滤 |
| `.claude/commands/bot-tg.md` | Modify（可选 alias） | 确保 `/chat` 被删后用户有迁移路径 |
| `.claude/hooks/persona-anchor.sh` | Modify (COUNT % 5 → COUNT % 20) | 降频：每 20 次工具调用再注入，减少 persona skill 已激活下的双重注入 |
| `SOUL/public/prompts/batch_worker.md` | Evaluate | 2 refs，看是否 governance pipeline 实际使用；不用则归档 |
| `SOUL/public/prompts/dedup_matrix.md` | Evaluate | 2 refs，同上 |

### Phase 3: 低优先级（语气瘦身）

| File | Change | Reason |
|------|--------|--------|
| `.claude/skills/systematic-debugging/SKILL.md` | Modify（删 "Banned phrases" 段落 + 缩短 IRON LAW 口吻） | Phase 1-4 骨架保留，对 4.7 的训斥式语气可降温 |
| `.claude/hooks/error-detector.sh` | Modify（L1/L2 escalation 文案瘦身） | 保留 2/3/4/5 次 escalation 机制，教学文案缩短 |
| `CLAUDE.md` § Rationalization Immunity 引用 | Modify（从"must consult"改为"reference"） | 表格仍保留，但不再强制每次查表 |

所有 phases 合计改动 ≈ 13 个文件，LOC 净减少估计 ~400。

## Steps

### Phase 1: 高优先级

1. 创建归档目录 `mkdir -p .trash/2026-04-17-scaffolding-prune/`
   → verify: `test -d .trash/2026-04-17-scaffolding-prune && echo ok`

2. 归档 `SOUL/public/research-sycophancy-split.md` 到 `.trash/2026-04-17-scaffolding-prune/`
   - depends on: step 1
   → verify: `test ! -f SOUL/public/research-sycophancy-split.md && test -f .trash/2026-04-17-scaffolding-prune/research-sycophancy-split.md`

3. 归档 `SOUL/public/prompts/dag_orchestration.md`
   - depends on: step 1
   → verify: `test ! -f SOUL/public/prompts/dag_orchestration.md && ls .trash/2026-04-17-scaffolding-prune/ | grep dag_orchestration`

4. 归档 `SOUL/public/prompts/rule_scoping.md`
   - depends on: step 1
   → verify: `test ! -f SOUL/public/prompts/rule_scoping.md`

5. 归档 `SOUL/public/prompts/session_boundary.md`
   - depends on: step 1
   → verify: `test ! -f SOUL/public/prompts/session_boundary.md`

6. 全仓 grep 检查，确认 step 3-5 被归档的 3 个 prompt 没有遗留实际调用（仅自引用和盘点报告除外）
   - depends on: step 3, 4, 5
   → verify: `grep -rI --exclude-dir=.trash --exclude-dir=.git "dag_orchestration\|rule_scoping\|session_boundary" . | grep -v "docs/plans/2026-04-17" | wc -l` 应为 0

7. 重写 `.claude/hooks/commit-reminder.sh` 第 15-20 行，把"Do NOT end your turn without committing"的强制语改成"提示未提交文件数 + 建议但不强制"
   - 具体：把 `echo "[COMMIT-NOW] ... Do NOT end ... Do not ask the user ..."` 改为 `echo "[COMMIT-CHECK] You have ${TOTAL} uncommitted file(s). Per CLAUDE.md Git Safety: stage-first, push-later. Consider staging now if a feature point is complete."`
   → verify: `bash -n .claude/hooks/commit-reminder.sh && ! grep -q "Do NOT end your turn" .claude/hooks/commit-reminder.sh`

8. 修改 `CLAUDE.md` § Goal-Driven Execution（约第 28-45 行）：替换为 3 行指针
   - 原文 15 行展开 → 替换为：`Transform vague tasks into verifiable goals before starting. Write tests/reproductions first where applicable; ensure tests pass before and after refactors. For multi-step tasks, state a brief verify command per step.`
   - 保留 Commitment Hierarchy / Execution / Planning Discipline 其他小节不动
   → verify: `wc -l CLAUDE.md` 应从 191 降至约 180；`grep -c "Goal-Driven Execution" CLAUDE.md` = 1（标题仍在）

9. 运行 session-start hook 自检，确认 hook 链不报错
   - depends on: step 7
   → verify: `bash .claude/hooks/commit-reminder.sh < /dev/null && echo 'hook ok'`

--- PHASE GATE: Phase 1 → Phase 2 ---
- [ ] 5 个归档动作全部生效（`.trash/` 有 4 个文件，git status 显示删除）
- [ ] `commit-reminder.sh` 语义已调整，与 CLAUDE.md Git Safety 一致
- [ ] `CLAUDE.md` § Goal-Driven Execution 瘦身完成
- [ ] 无 hook 报错
- [ ] Owner review: **required**（因为涉及 CLAUDE.md 核心配置，走 CLAUDE.md Gate Functions § Modify Core Config）

### Phase 2: 中优先级

10. 确认 `/chat` slash command 没有被外部脚本硬编码依赖
    → verify: `grep -rI "slash.*chat\|/chat\b" --exclude-dir=.git --exclude-dir=.trash . | grep -v "docs/plans/2026-04-17" | grep -v "bot-tg\|bot-wx"` 应为空

11. 归档 `.claude/commands/chat.md` 到 `.trash/2026-04-17-scaffolding-prune/`
    - depends on: step 10
    → verify: `test ! -f .claude/commands/chat.md`

12. 修改 `.claude/hooks/persona-anchor.sh` 第 11 行：`if [ $((COUNT % 5)) -eq 0 ]` → `if [ $((COUNT % 20)) -eq 0 ]`
    → verify: `grep -c "COUNT % 20" .claude/hooks/persona-anchor.sh` = 1 且 `grep -c "COUNT % 5" .claude/hooks/persona-anchor.sh` = 0

13. 检查 `batch_worker.md` 和 `dedup_matrix.md` 的实际 consumer（2 refs 可能是自引 + 一处真调用，也可能两次自引）
    → verify: 对每个文件跑 `grep -rI "batch_worker\|dedup_matrix" --exclude-dir=.git --exclude-dir=.trash . | grep -v "SOUL/public/prompts/"`；若输出仅为本 plan 文件则同样归档

14. 若 step 13 判定为孤儿，归档 `batch_worker.md` 和 `dedup_matrix.md`
    - depends on: step 13
    → verify: `test ! -f SOUL/public/prompts/batch_worker.md` 或 说明保留原因

--- PHASE GATE: Phase 2 → Phase 3 ---
- [ ] `/chat` 迁移路径清晰（bot-tg 仍可用）
- [ ] persona-anchor 降频生效
- [ ] batch_worker / dedup_matrix 去留已决策
- [ ] Owner review: not required（可直接进 Phase 3）

### Phase 3: 低优先级

15. 修改 `.claude/skills/systematic-debugging/SKILL.md`：
    - 保留 Phase 1 "MANDATORY GATE" 骨架和 5 条检查项
    - 删除第 3 行的"IRON LAW"重复强调段
    - 删除所有 "Banned phrases:" 相关段落（若存在）
    - 总行数从 88 降至约 70
    → verify: `wc -l .claude/skills/systematic-debugging/SKILL.md` 低于 75，且 `grep -c "Phase 1" .claude/skills/systematic-debugging/SKILL.md` ≥ 2

16. 修改 `.claude/hooks/error-detector.sh` 的 L1/L2 escalation 文案（约第 80-120 行），把多行教学文案压缩为单行 directive
    → verify: `bash -n .claude/hooks/error-detector.sh && wc -l .claude/hooks/error-detector.sh` 降低 ≥30 行

17. 修改 `CLAUDE.md` 中 Rationalization Immunity 的引用措辞（约第 48 行）：`consult` → `reference when in doubt`
    → verify: `grep "rationalization-immunity" CLAUDE.md` 包含 "reference"

--- PHASE GATE: Phase 3 → Done ---
- [ ] 所有 `wc -l` 对比记录完成
- [ ] `git diff` 只包含本 plan 范围内的文件
- [ ] 无 hook 语法错误（`bash -n` 全 pass）
- [ ] `.trash/2026-04-17-scaffolding-prune/` 内容列表已写入 commit message 或 PR 描述
- [ ] Owner review: not required（evidence-based）

## 影响评估

| 维度 | 剪枝前 | 剪枝后（估） |
|---|---|---|
| CLAUDE.md 行数 | 191 | ~180 |
| SOUL/public/prompts 文件数 | 25 | 20-21 |
| SOUL/public/prompts 总 LOC | ~1800 | ~1500 |
| hooks 总 LOC | ~2200 | ~2170 |
| 每次 session 启动 context 注入量 | baseline | 降 10-15% |
| CLAUDE.md 加载 token（粗估） | ~4000 | ~3700 |

## 不在本次范围

明确排除的：
- 任何 `约束类` hook（guard-*, config-protect*, env-leak, security-scan, block-protect, dispatch-gate, agent-postcheck）
- 任何 `状态类` hook（session-*, pre/post-compact, audit, routing, correction-detector, memory-save）
- `.claude/agents/` 所有 subagent 定义（配置类，必需）
- SOUL/public/prompts/ 中被 governance pipeline 引用 ≥5 次的 "生产模板"（task/chat/analyst/insights/profile/scrutiny/clarification/guardian_assessment/collaboration_modes/cognitive_modes/methodology_router）
- CLAUDE.md 所有 Gate Functions / Git Safety / Memory Evidence Grading / Per-Skill Constraints 小节
- `SOUL/public/steal/` 历史偷师报告（档案性质，低引用是正常的）

## 风险 & 回滚

- 所有删除均走 `.trash/`，可一条 `mv` 命令复原
- CLAUDE.md 修改前先 `git diff > /tmp/claude-md-backup-2026-04-17.patch`
- hook 改动后必须跑 `bash -n` 语法检查
- 若 Phase 1 Gate 未通过 owner review → STOP，不进入 Phase 2

## 后续（不在本 PR）

- 把 `steal` skill 的 `constraints/` 子目录模式推广到 `verification-gate` 和 `systematic-debugging`（把软提醒转成硬约束）
- 建立季度复盘机制：下次模型大版本升级时重跑本盘点
