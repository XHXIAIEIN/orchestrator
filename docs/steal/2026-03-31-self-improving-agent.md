# Round 23: self-improving-agent @pskoett

**来源**: https://clawhub.ai/pskoett/self-improving-agent | https://github.com/peterskoett/self-improving-agent
**统计**: 2.9k stars, 335k downloads, MIT-0 license
**分析日期**: 2026-03-31

## 概述

ClawHub 最热 skill——把 agent 的错误、纠正、功能缺口结构化记录到 `.learnings/` markdown 文件，通过 hook 自动检测触发，达到 Recurrence 阈值后 promote 到 CLAUDE.md/SOUL.md 等永久记忆。

## 核心机制

1. **三分类日志**: LEARNINGS.md (corrections/knowledge_gaps/best_practices) + ERRORS.md (command failures) + FEATURE_REQUESTS.md (capability gaps)
2. **结构化 Entry**: `TYPE-YYYYMMDD-XXX` ID + Priority/Status/Area/Metadata 全套字段
3. **Hook 自动检测**: activator.sh (UserPromptSubmit, 提醒评估) + error-detector.sh (PostToolUse, 捕获非零退出码)
4. **Recurrence 去重**: Pattern-Key 做 stable key，grep 搜已有条目 → bump count → 达阈值(≥3, 跨2+任务, 30天内) 自动 promote
5. **Promote 分层**: 行为模式→SOUL.md, 工作流→AGENTS.md, 工具坑→TOOLS.md, 项目约定→CLAUDE.md
6. **Skill 自萃取**: 5+ related learnings + Recurrence≥2 + 跨项目适用 → 自动提取为独立 skill

## 与 Orchestrator 现有能力对比

| 维度 | self-improving-agent | Orchestrator |
|------|---------------------|-------------|
| 存储 | Markdown 文件（.learnings/） | **DB（events.db learnings 表）** ✅ 更优 |
| 三分类 | LRN/ERR/FEAT 三文件 | entry_type 字段区分 ✅ 已有 |
| 去重 | grep Pattern-Key + 手动 bump | **embedding dedup（OpenViking 偷来的）** ✅ 更优 |
| Recurrence | 纯计数 + See Also 链接 | recurrence 字段 + last_seen ✅ 已有 |
| 证据追加 | 手动 append 到 Details | detail 字段 `\n---\n` 自动拼接 ✅ 已有 |
| 矛盾检测 | 无 | **prefix 冲突检查** ✅ 更优 |
| Promote | Recurrence≥3 → 写入 CLAUDE.md | promoter.py + compiler.py ✅ 已有 |
| 相关性推导 | 手动 See Also 链接 | **_infer_related_keys() 自动推导** ✅ 更优 |
| **Hook 检测** | **3 个 shell hook 自动触发** | ❌ **缺失** — 我们的 learnings 只在 Clawvard 考试等显式调用中产生 |
| **Detection Triggers** | **对话模式匹配（"actually..."、"no, that's..."）** | ❌ **缺失** |
| **Feature Request 捕获** | **"I wish you could..."等模式** | ❌ **缺失** — 有 entry_type='feature' 但无自动检测 |
| **Skill 萃取** | **extract-skill.sh 从 learnings 提取独立 skill** | ❌ **缺失** |
| **跨会话共享** | sessions_send/sessions_history | ❌ **缺失** — DB 持久化变相实现，但无显式 cross-session messaging |
| **Periodic Review** | grep 快查命令 + review 流程 | ❌ **缺失** — 无定期审查机制 |

## 可偷模式

### P0 — 立即可用，填补结构性缺口

#### 1. Error Detection Hook (PostToolUse)
**描述**: error-detector.sh 在每次工具调用后检查退出码，非零自动触发 learnings 记录。
**为什么值得**: 我们的 learnings 系统有完整的写入管线但没有自动触发器——等于造了仓库但没有进货渠道。当前 learnings 只在 Clawvard 考试和手动调用时产生，日常工作中的错误全部丢失。
**适配方案**: 在 `.claude/hooks/` 增加 `error-detector.sh`，PostToolUse hook，检测 Bash 工具非零退出码 → 调用 `learnings.append_error()` 写入 DB。不需要 markdown 中间层。

#### 2. Correction Detection (UserPromptSubmit 分析)
**描述**: 通过模式匹配检测用户纠正（"actually..."、"no, that's wrong"、"不对"、"错了"），自动记录为 correction 类型 learning。
**为什么值得**: 用户纠正是最高信号的学习机会，但当前完全被浪费——纠正发生在对话中，下次会话就消失了。
**适配方案**: 扩展现有 `routing-hook.sh` 或新增 hook，用 Python 分类器检测 correction 语义（中英文都要覆盖），触发 `learnings.append_learning(category='correction')`。

#### 3. Activation Reminder (Session Start)
**描述**: activator.sh 在会话启动时提醒 agent 检查 pending learnings，避免重复犯错。
**为什么值得**: 我们 session-start.sh 已经编译 boot.md 和注入状态，但**从不提醒 agent 检查 pending learnings**。learnings 写了但没人看 = 白写。
**适配方案**: 在 session-start.sh 末尾加一段：查 DB 中 pending+high priority learnings 数量，输出 `[learnings] X pending (Y high-priority)` 提醒。已有 `get_learnings_summary()` 方法可直接调用。

### P1 — 值得偷但需要设计

#### 4. Skill Extraction Pipeline
**描述**: extract-skill.sh 扫描 learnings，当同主题条目≥5 且 Recurrence≥2 时，自动提取为独立 skill 文件。
**为什么值得**: 从经验中自动生长出新能力——这是真正的 self-improvement 闭环。我们有 20+ 轮偷师经验，但偷师成果是人工写 PATTERNS.md，没有自动化。
**适配方案**: 新增 `SOUL/tools/extract_skill.py`，定期扫描 DB learnings 表，按 area/pattern_key 前缀聚类，达标的生成 `.claude/skills/<topic>/skill.md` 骨架。compiler.py 编译时顺带跑。

#### 5. Feature Request Auto-Capture
**描述**: 检测 "I wish..."、"能不能..."、"要是有...就好了" 等模式，自动记录为 feature request。
**为什么值得**: 功能缺口信号散落在对话中，事后无法追溯。虽然我们有 `append_feature()`，但零自动触发。
**适配方案**: 与 P0-2 的 correction detection 合并到同一个分类器 hook 中，增加 feature_request 意图类别。

#### 6. Periodic Review Trigger
**描述**: 在自然断点（完成 feature、切换任务、周末）自动提示 review pending learnings。
**为什么值得**: 防止 learnings 堆积成死数据。
**适配方案**: session-stop.sh hook 中加一段：如果 pending learnings > 10，输出 review 提醒。或者在 compiler.py 编译时检查并输出。

### P2 — 参考价值

#### 7. Multi-Agent Learning Broadcast
**描述**: sessions_send 把 learning 推送给其他活跃 session。
**为什么值得**: 我们的 sub-agent 架构（三省六部）中，一个 agent 踩的坑其他 agent 不知道。
**适配方案**: DB 已经是共享的，但可以在 Agent SDK dispatch 时注入 `recent_learnings` context。低优先级——DB 持久化已经变相解决。

#### 8. Copilot Instructions Sync
**描述**: 把 promoted learnings 同步到 `.github/copilot-instructions.md`。
**为什么值得**: 跨工具一致性。不过我们不用 Copilot，跳过。

## 独特 Prompt 技巧

1. **Detection Trigger 清单作为 prompt**: 把"什么时候该记录"的条件直接写进 skill 指令，而不是依赖 agent 自主判断。这比说"记录错误和教训"具体得多——给了明确的 pattern match 触发词。
2. **Quick Reference Table 开头**: SKILL.md 第一段就是 `| Situation | Action |` 表格，让 agent 立即知道该做什么而不需要读完全文。这是 attention budgeting 的好实践。
3. **Promotion Examples 对比**: "verbose learning" vs "concise in CLAUDE.md" 的 before/after 示例，教 agent 如何蒸馏而不是照搬。
4. **Status 状态机**: pending → in_progress → resolved/wont_fix/promoted 五态，比我们的 pending/promoted 两态更细。

## 关键差异总结

Orchestrator 在存储层（DB）、去重（embedding dedup）、矛盾检测上**已经超越** self-improving-agent。但在**感知层**（自动检测错误/纠正/功能请求）和**闭环层**（skill 萃取、定期审查）上严重缺失。

类比：我们建了一个很好的数据仓库，但没有数据采集管道。self-improving-agent 的仓库是 markdown 文件（不如我们），但它的采集管道（hook 自动检测 + 对话模式匹配）是完整的。

**偷什么**: 偷采集管道，不偷存储层。具体就是 P0 的三个 hook。
