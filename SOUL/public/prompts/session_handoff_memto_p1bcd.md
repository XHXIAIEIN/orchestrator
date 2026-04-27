# Session Handoff: memto steal — Phase 2 收尾

## Branch / worktree

- Worktree: `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-memto`
- Branch: `steal/memto`
- HEAD: `51377ff`（本地未 push）
- Plan 文件：`docs/plans/2026-04-18-memto-impl.md`（Phase 3 被拆成 step-per-commit）

## 进度（plan steps ↔ commit 对照）

| Plan step | 状态 | Commit |
|---|---|---|
| Phase 1 P0 — install memto + SKILL.md | ✅ | `337884a` |
| Pre-existing bug: `CLAUDE_PROJECTS_ROOT` forward reference | ✅ | `74ec0ef` |
| Phase 2 P1a step 4-5 — indexer/scorer chrome 过滤 ×4 | ✅ | `a302474` |
| Phase 2 P1b step 6 — indexer.py skip-malformed 增强 | ✅ | `d7b47be` |
| Phase 2 P1c step 7 — `SOUL/tools/prompt_sampler.py`（7 策略） | ✅ | `245b6ed` |
| Phase 2 P1d step 8 — `SOUL/tools/spawn_utils.py`（scaled timeout） | ✅ | `51377ff` |

**所有 verify 脚本已 PASS**（P1b: 畸形 JSONL 不崩 / P1c: 7 策略 assert / P1d: 空/50MB/缺失路径三场景）。

## 下一步候选（按轻重排）

### A. Push（需 owner 明确授权）
```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-memto
git push -u origin steal/memto
```
上一个 session 停在 `a302474` 未 push，这轮追加三笔也未 push。如果 owner 要走 PR 流程，push 后在主仓开 PR 到 `main`。

### B. Open question Q1 — plc Phase 2 ambient marker 归属
- `~/.claude/CLAUDE.md` 里多了一块 "orchestrator ambient marker"（plc Phase 2 预期写入的产物）
- 决策需要 owner 确认：
  - **永久部署** → 保留不动
  - **验证后清场的脚手架** → 用 `marker_upsert.py remove_block` 清掉
- 开 session 时 owner 贴一下 marker 当前内容，再判断
- 相关工具：`marker_upsert.py`（路径未确认，需要 grep 一下）

### C. 下一轮 steal work（仍 out of scope，但列出来方便规划）
- `memory_synthesizer.py` 接入 `prompt_sampler.py`（替换硬编码"first+last"）
- 将来 `claude -p` 调用点出现时接入 `spawn_utils.scaled_timeout_ms()`
- P2 items（NormalizedSession schema、fs snapshot diff、Hermes noise extractor）— 仅在跨 runtime 需求出现时做，当前零需求

## 已知约束

- Steal 工作必须在 `steal/*` 或 `round/*` 分支（dispatch-gate hook 拦）→ 当前 `steal/memto` 满足
- 所有 sub-agent dispatch 必须用 `isolation: "worktree"` 参数
- Commit 不自动 push（`push` 需单独 owner 授权）
- 每步执行完后跑 plan 里的 verify 脚本，不靠"我觉得对了"

## Rollback（仅 owner 明确 "roll back" 才执行）

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-memto
git stash  # 先备份
# 单步回退（保守）：
git reset --hard 245b6ed  # 撤 P1d
git reset --hard d7b47be  # 撤 P1c
git reset --hard a302474  # 撤 P1b
# 或一次回到 Phase 1 结束点：
git reset --hard 337884a
```

`74ec0ef` 的 bug fix 如果回滚，`from SOUL.tools import indexer` 会再次 NameError — 注意。
