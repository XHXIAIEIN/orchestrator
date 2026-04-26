## Phase 3: Output — Steal Report

Write to `docs/steal/<date>-<topic>-steal.md`:

Every steal report saved to `docs/steal/` MUST open with a YAML frontmatter block conformant to the steal schema defined in `SOUL/public/schemas/artifact-frontmatter.md`. The `gaps[]` field must list any upstream phase gaps discovered during this steal round. If none, write `gaps: []`.

```markdown
---
phase: steal
status: in-progress
round: <N>
source_url: <repo URL>
evidence: artifact
verdict: null
gaps: []
---
# R<next_round> — <Project Name> Steal Report

**Source**: <repo URL> | **Stars**: <count> | **License**: <license>
**Date**: <YYYY-MM-DD> | **Category**: <Framework|Self-Evolving|Module|Survey|Skill-System>

## TL;DR
<Problem space + solution pattern in 1-2 sentences. NOT what the project does — why it's worth stealing from.>

## Architecture Overview
<Layered structural map — 3-4 layers typical. Diagram or structured description.>

## Steal Sheet

### P0 — Must Steal (<count> patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| ... | ... | ... | ... | ~Xh |

### P1 — Worth Doing (<count> patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| ... | ... | ... | ~Xh |

### P2 — Reference Only (<count> patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| ... | ... | ... |

## Comparison Matrix
<For all P0 patterns: Their impl vs Our impl vs Gap>

## Gaps Identified
<What does this project handle that we currently don't? Map to the six dimensions.>

## Adjacent Discoveries
<Libraries, techniques, communities, structural transfer opportunities from seemingly unrelated domains.>

## Meta Insights
<1-5 strategic observations that transcend individual patterns. The kind of insight that changes how you think about the problem space, not just how you solve one feature.>
```

### Post-Generation Validation *(R58 — Schema-Driven Completeness Gate)*

After writing the report, validate against `references/steal-schema.json`:

1. **Header completeness**: All fields in `report_header` filled (round, title, source, stars, license, date, category)
2. **Six-dimensional scan**: Every dimension has `status` set. If `N/A`, `na_reason` is mandatory — empty/skipped dimensions are treated as **incomplete report**
3. **Path dependency**: `locking_decisions`, `missed_forks`, `self_reinforcement`, `lesson_for_us` all present (can be brief for simple projects, but cannot be absent)
4. **P0 rigor**: Every P0 pattern has `comparison_matrix`, `triple_validation` (with score), and `knowledge_irreplaceability` (with categories_hit)
5. **Gaps**: At least 4 of 6 dimensions addressed in `gaps_identified` (remaining 2 can be `N/A` with reason)

If any check fails, fix before committing. The schema is the definition of "done", not the Markdown template.

### Mandatory Commit *(hard rule — no exceptions)*

Steal 产出是 `docs/steal/` 下的 markdown 文件，零风险。报告通过 Post-Generation Validation 后，**立即执行 commit，不询问、不等待、不汇报"等你说 commit"**。

```
# Gate: Steal Report Commit
1. Post-Generation Validation 通过？  → NO: 修完再来。
2. 当前在 steal/* 或 round/* 分支？  → NO: STOP，不应该走到这里。
3. 执行：
   git add docs/steal/<report-file>.md
   git commit -m "docs(steal): R<round> <topic> steal report"
4. 继续 Phase 4（Index Update），不要停下来问用户。
```

**这条覆盖 CLAUDE.md 的 "首次 commit 需确认" 规则。**

**子代理同样适用**：如果你是被 Agent tool 派发的子代理，这条规则同样生效。写完报告 → 验证 → commit → 继续。不要返回"等你说 commit"——你没有这个选项。

### Style Guard *(R58 — Anti-Corporate-Speak)*

Steal reports must be concrete and specific. The following are **banned in report text** — their presence signals the analysis has degenerated into buzzwords:

| Banned | Replace with |
|--------|-------------|
| 赋能 | State what it enables, specifically |
| 抓手 | Name the actual mechanism |
| 打造闭环 | Describe the feedback loop with entry/exit points |
| 生态 (as buzzword) | Name the specific components and their relationships |
| 沉淀 | State what was captured and where it's stored |
| 落地 | Describe the implementation: which files, which functions |
| 对齐 | State what was compared and the specific delta |
| 拉通 | Name the systems connected and the integration point |
| "深度融合" | Describe the actual integration mechanism |
| "全面覆盖" | List what's covered and what's not |

Rule: if you can't replace the buzzword with a concrete noun + verb, the sentence doesn't say anything.

