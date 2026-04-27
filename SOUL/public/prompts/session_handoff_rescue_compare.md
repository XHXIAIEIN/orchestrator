继续上个 session 的 rescue 任务。

## 上轮成果（已就位）
7 个 rescue worktree + 分支已建好，每个都从 archive/steal-<topic>-20260419 cherry-pick 回了本尊 commit，全部 clean、未 merge、未 push。

| rescue 分支 | 关键产物 |
|------------|---------|
| rescue/ai-customer-support-agent | R79 report + impl plan |
| rescue/freeclaude | R78 deep report + p0 plan |
| rescue/learn-likecc | R82 report + impl plan |
| rescue/opus-mind | R79 report + 2 plan + md-lint/scripts/audit.py (383 行 WIP) |
| rescue/prompt-engineering-models | R80 report + retrospective + unaudited-attachment-triage.md 约束 + plan |
| rescue/steering-log | R78 report + impl plan |
| rescue/zubayer-multi-agent-research | R79 report + rename + impl plan |

## 本轮任务（选项 2：比对 rescue vs 活 steal）
7 个 topic 各自还有一条活跃的 steal/<topic> 分支（worktree 在 .claude/worktrees/steal-<topic>/）——那是老 archive tip 之后主人从 main 重做的版本（基于最新 main，ahead 2-4 commit）。

目标：判断每个 topic 上，**rescue/<topic>**（从 archive tag 救回来的）和 **steal/<topic>**（活跃重做版）是否等价、哪份为准、合回 main 时该走哪条。

## 判断框架（每个 topic 都跑一遍）
1. `git diff --name-only rescue/<topic>..steal/<topic>` 看文件差异
2. `git log --oneline main..rescue/<topic>` vs `git log --oneline main..steal/<topic>` 看 commit 级差异
3. 对每个共同文件：`git diff rescue/<topic> steal/<topic> -- <file>` 看内容差异
4. 分三类判定：
   - **完全等价** → rescue 可删，用活 steal 走正常 pipeline
   - **rescue 独有内容** → 需要 port 到活 steal，或者 rescue 成为主干
   - **两者都独有** → 给主人列差异清单让他决定

## 特别关注
- **opus-mind**：rescue 有 md-lint/scripts/audit.py (383 行 WIP)，活 steal/opus-mind 上 be82509 新版 SHA 6831b91 也有 md-lint wip——核对两份内容是否一致
- **prompt-engineering-models**：rescue 有 unaudited-attachment-triage 约束文件，活 steal/prompt-engineering-models 也有 b059fc7——核对是否一致

## 禁止
- 不要动 archive/steal-*-20260419 tag（留着做保险）
- 不要动 steal/<topic>-old 分支（留着做保险）
- 不要 merge / push / rebase 任何分支
- 不要改现有 rescue 或 steal 分支的 commit
- 本轮只做比对和报告，不做决策执行

## 交付
一份比对报告：每个 topic 一节，列"等价 / rescue 独有 / steal 独有"三类文件，最后给一个合并策略建议。
