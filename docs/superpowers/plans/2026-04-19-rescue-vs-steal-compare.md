# Rescue vs Steal 比对报告 — 2026-04-19

## 背景

上一轮 session 从 `archive/steal-<topic>-20260419` tag cherry-pick 回了 7 条 `rescue/<topic>` 分支（挂在 `.claude/worktrees/rescue-<topic>/`）。
另一侧还有 7 条活跃的 `steal/<topic>` 分支（挂在 `.claude/worktrees/steal-<topic>/`），是主人从最新 main 重做的版本（ahead 2–4 commits）。

目标：判定每对是否内容等价，给出合回 main 时走哪条的建议。

**本轮只做比对和报告，不做任何 merge / push / rebase / branch 删除。**

## 方法

对每个 topic 跑：

1. `git log --oneline main..rescue/<topic>` 和 `main..steal/<topic>` — commit 级概览
2. `git diff --name-status main..<branch>` — 两侧各自相对 main 的文件改动
3. `git diff --name-status rescue/<topic>..steal/<topic>` + `git diff --stat ...` — 两侧直接差异
4. `git rev-parse <branch>^{tree}` — tree hash 硬比较（决定性证据）
5. `git range-diff main..rescue/<topic> main..steal/<topic>` — 逐 commit patch 等价性（`=` = 内容一致，仅元数据差）

## 总结论

**7 对 rescue/steal 的 tree hash 全部相等，range-diff 全部 `=`。两侧 bit-for-bit 等价，SHA 差异纯粹是 cherry-pick 重放时 committer/date 被刷新造成的。**

| Topic | Tree hash | rescue commits | steal commits | range-diff | rescue..steal 文件差 | 判定 |
|---|---|---:|---:|---|---|---|
| ai-customer-support-agent | `194f91504583` | 2 | 2 | `1:= 2:=` | ∅ | 等价 |
| freeclaude | `2750cfba7007` | 2 | 2 | `1:= 2:=` | ∅ | 等价 |
| learn-likecc | `380171db16bc` | 2 | 2 | `1:= 2:=` | ∅ | 等价 |
| opus-mind | `e02d7a32deb9` | 4 | 4 | `1:= 2:= 3:= 4:=` | ∅ | 等价 |
| prompt-engineering-models | `797ec0e9362e` | 4 | 4 | `1:= 2:= 3:= 4:=` | ∅ | 等价 |
| steering-log | `ef6ae706c270` | 2 | 2 | `1:= 2:=` | ∅ | 等价 |
| zubayer-multi-agent-research | `baaedeccea24` | 3 | 3 | `1:= 2:= 3:=` | ∅ | 等价 |

无 "rescue 独有" 文件，无 "steal 独有" 文件，无"两侧都独有"文件。完全没有需要 port 或三方决策的内容。

## 逐 topic 对照

每节列 `rescue commit  steal commit  subject`（SHA 不同、内容 `=`）。

### ai-customer-support-agent

```
1:  f789e6e = 1:  6102092 docs(steal): R79 ai-customer-support-agent steal report
2:  ebb6f44 = 2:  604c1d2 docs(plan): implementation plan for ai-customer-support-agent steal
```

引入文件（两侧相同）:
- `docs/steal/R79-ai-customer-support-agent-steal.md` (A)
- `docs/plans/2026-04-18-ai-customer-support-agent-impl.md` (A)

### freeclaude

```
1:  d66bbb9 = 1:  9aba7f1 docs(steal): R78 freeclaude steal report
2:  ed5569e = 2:  835dca5 docs(plans): R78 FreeClaude P0 implementation plan
```

引入文件:
- `docs/steal/R78-freeclaude-deep-steal.md` (A)
- `docs/superpowers/plans/2026-04-17-r78-freeclaude-p0.md` (A)

### learn-likecc

```
1:  b992402 = 1:  d3130b0 docs(steal): R82 learn-likecc steal report
2:  399b335 = 2:  862dcff docs(plan): implementation plan for learn-likecc steal
```

引入文件:
- `docs/steal/R82-learn-likecc-steal.md` (A)
- `docs/plans/2026-04-18-learn-likecc-impl.md` (A)

### opus-mind ★

用户特别关注：两侧各自的 md-lint WIP 是否一致 → **确认一致**。

```
1:  19da186 = 1:  23badab docs(steal): R79 opus-mind steal report
2:  989e903 = 2:  3b6e929 docs(plans): R79 opus-mind P0 implementation plan
3:  b5da584 = 3:  cb4f822 docs(plan): implementation plan for opus-mind steal
4:  6a698f3 = 4:  6831b91 wip(md-lint): opus-mind — rescue Phase A partial    ← md-lint WIP
```

引入文件:
- `.claude/skills/md-lint/scripts/__init__.py` (A)
- `.claude/skills/md-lint/scripts/audit.py` (A) — 383 行 WIP，两侧内容一致
- `docs/steal/R79-opus-mind-steal.md` (A)
- `docs/superpowers/plans/2026-04-17-r79-opus-mind-p0.md` (A)
- `docs/plans/2026-04-18-opus-mind-impl.md` (A)

### prompt-engineering-models ★

用户特别关注：`unaudited-attachment-triage` 约束两侧是否一致 → **确认一致**。

```
1:  e8ee80c = 1:  d16dfa6 docs(steal): R80 prompt-engineering-models steal report
2:  d10687d = 2:  f871a86 docs(steal): R80 retrospective — correct trojan misjudgment to unaudited-attachment triage
3:  fe172b8 = 3:  b059fc7 docs(steal): add unaudited-attachment-triage constraint   ← 约束文件
4:  da4c0e2 = 4:  1de66dc docs(plan): implementation plan for prompt-engineering-models steal
```

引入文件:
- `.claude/skills/steal/constraints/unaudited-attachment-triage.md` (A) — 两侧内容一致
- `docs/steal/R80-prompt-engineering-models-steal.md` (A)
- `docs/plans/2026-04-18-prompt-engineering-models-impl.md` (A)

### steering-log

```
1:  dcc5675 = 1:  c351bac docs(steal): R78 steering-log steal report
2:  ccd230e = 2:  320d39f docs(plan): implementation plan for steering-log steal
```

引入文件:
- `docs/steal/R78-steering-log-steal.md` (A)
- `docs/plans/2026-04-18-steering-log-impl.md` (A)

### zubayer-multi-agent-research

```
1:  bdbd340 = 1:  528b0bb docs(steal): R59 zubayer multi-agent research skill steal report
2:  1344e44 = 2:  770ecb9 docs(steal): rename to R79 naming convention
3:  f6570bf = 3:  47ac1db docs(plan): implementation plan for zubayer-multi-agent-research steal
```

引入文件:
- `docs/steal/R79-zubayer-multi-agent-research-steal.md` (A)
- `docs/plans/2026-04-18-zubayer-multi-agent-research-impl.md` (A)

## 合并策略建议

既然 7 对全部等价，rescue 分支不再承载任何独有内容。建议：

1. **以 steal/<topic> 为准走正常 pipeline 合回 main。** 理由：
   - 它们是基于最新 main 重做出来的，SHA 与当前主线衔接更干净
   - steal worktree (`.claude/worktrees/steal-<topic>/`) 是日常 steal 流程默认路径
   - 命名与 steal pipeline 一致（合入后还能 steal/<topic>-old 归档）

2. **rescue/<topic> 分支可回收**（下一轮如果主人批准才动手）：
   - `git worktree remove .claude/worktrees/rescue-<topic>`
   - `git branch -D rescue/<topic>`
   - 回收零风险：tree 已在 steal 一侧完整保留，archive tag 仍在

3. **禁止区继续禁止**：
   - `archive/steal-<topic>-20260419` tag 保留（原约束）
   - `steal/<topic>-old` 分支保留（原约束）

4. **下一轮合入 main 前还要做的事（不在本轮范围）**：
   - 主人决定 7 个 topic 合并顺序（或分批、或打包）
   - 每条 steal/<topic> 走 fast-forward 或 squash merge 的惯例（仓库既有规则）
   - 合入后 `steal/<topic> → steal/<topic>-old` 归档、worktree remove

## 验证命令（主人 want 复核时）

```bash
# 1. tree hash 对照
for T in ai-customer-support-agent freeclaude learn-likecc opus-mind prompt-engineering-models steering-log zubayer-multi-agent-research; do
  printf "%-32s rescue=%s steal=%s\n" "$T" \
    "$(git rev-parse rescue/$T^{tree})" "$(git rev-parse steal/$T^{tree})"
done

# 2. range-diff 复查
for T in ai-customer-support-agent freeclaude learn-likecc opus-mind prompt-engineering-models steering-log zubayer-multi-agent-research; do
  echo "==[$T]=="
  git range-diff main..rescue/$T main..steal/$T
done
```

两条命令只读、随时可复跑。
