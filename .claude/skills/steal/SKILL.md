---
name: steal
description: "Systematic knowledge extraction from open-source projects. Use when: user shares a repo/link to study, says 偷师/steal/学习/研究, or wants to analyze another project's patterns for adoption."
---

# Steal — Systematic Knowledge Extraction

You are conducting a steal (偷师) operation: extracting transferable patterns from external projects to strengthen Orchestrator. This is NOT evaluation ("should we use it?") — it's extraction ("what can we learn and adapt?").

Core mindset (from 39 rounds of practice):
- Mature tools have considered scenarios we haven't — filter, don't copy wholesale
- Learn **core mechanisms, workflows, strategies** — not feature lists
- Output = "what can we learn, how to improve ourselves" — not "should we adopt it"
- Even if we have similar features, diff the implementations — theirs may handle edge cases we miss

## Pre-flight

1. **Branch gate** *(hard rule — no exceptions)*: Steal work MUST happen on a `steal/*` or `round/*` branch. **Never modify files on any other branch.**
   - Check current branch: `git branch --show-current`
   - If not on `steal/*` or `round/*` → **immediately create and switch**: `git checkout -b steal/<topic>`
   - Do NOT ask the user whether to create the branch. Do NOT proceed with any file writes until you are on the correct branch.
   - The dispatch-gate hook also blocks `[STEAL]` work on other branches as a safety net, but the skill itself must enforce this before the hook even fires.

2. **Identify target**: URL, repo name, or local path. If user gave multiple links, process ALL — don't skip any for seeming "unrelated" (breadth rule: a traffic sign detector's tiling strategy might be exactly what a UI detector needs).

3. **Check prior art**: Search `docs/steal/` and the steal consolidated index in memory for existing reports on this target. If found, this is a **follow-up** — build on existing analysis, don't duplicate.

4. **Determine target type** — this shapes your analysis angle:

| Type | Examples | Analysis Focus |
|------|----------|---------------|
| Complete framework | Codex, PraisonAI, DeerFlow | Architecture panorama, multi-layer comparison |
| Self-evolving system | autoagent, yoyo-evolve | Closed-loop mechanisms, governance |
| Specific module | Claudeception, memvid | Single-point depth, implementation tricks |
| Industry survey | STEAL-SHEET (32 projects) | Consensus vs divergence, tradeoffs |
| Skill/prompt system | superpowers, agent-scripts | Workflow design, quality gates |

#### Mini-Prompt: Target Type Classifier (Haiku-compatible)

> This block is a self-contained intent router. It can be run by a lighter model (Haiku / Sonnet) before the full steal workflow loads. Input: the user's message or target URL. Output: one of {framework, self-evolving, specific-module, industry-survey, skill-prompt} with a 1-sentence justification.

```
SYSTEM: You classify steal (偷师) targets into 5 categories. Return JSON only.
Categories: framework | self-evolving | specific-module | industry-survey | skill-prompt
Rules:
- framework: repo with architecture, multiple layers, agent coordination
- self-evolving: repo whose primary value is improving itself (eval loops, memory updates)
- specific-module: single file or narrow feature (<500 LOC focus)
- industry-survey: collection of projects or compiled analysis (lists, stars, comparisons)
- skill-prompt: prompt collection, system prompt library, SKILL.md files, agent instructions

USER: {target_description}

RESPONSE FORMAT:
{"type": "<category>", "reason": "<one sentence>", "confidence": 0.0-1.0}
```

**Handoff**: After classification, pass `type` to the main steal workflow. The main workflow skips re-classification and enters `### Adaptive Execution by Target Type` directly with the resolved type.

### Adaptive Execution by Target Type

The target type is NOT just documentation — it drives execution behavior across all three phases.

**Complete framework:**
- Phase 1: Equal depth across all 6 dimensions. Architecture diagram required (Layer N notation). Spend 40% of analysis time on Execution/Orchestration dimension.
- Phase 2: P0 threshold = architectural patterns only (changes how the system *thinks*). Require comparison matrix for every P0. Minimum 3 P0 candidates or explain why fewer.
- Phase 3: Output includes a full architecture comparison (theirs vs ours, layer by layer).

**Self-evolving system:**
- Phase 1: Deep dive on Memory/Learning + Quality/Review (60% of time). Security/Governance gets elevated attention (self-modifying = higher risk). Skip Context/Budget unless novel.
- Phase 2: P0 threshold focuses on closed-loop mechanisms. Any pattern that enables self-improvement without human intervention is automatic P0 candidate. Knowledge irreplaceability scoring is mandatory.
- Phase 3: Output includes an "evolution loop map" — how does the system improve itself, what triggers it, what are the guardrails.

**Specific module:**
- Phase 1: Go narrow and deep. Pick the 2 most relevant dimensions and go to implementation-level detail (read actual functions, trace data flow). Skip dimensions where the module has nothing novel.
- Phase 2: P0 threshold = implementation tricks that save >1h of work or prevent a known bug class. Code snippets are mandatory (not just descriptions). Fewer patterns expected (2-4 typical), but each must have concrete "how to adapt" with exact file paths.
- Phase 3: Output is compact. No architecture overview needed — jump straight to steal sheet.

**Industry survey:**
- Phase 1: Breadth over depth. For each project in the survey, spend max 15 min. Focus on consensus patterns (appear in 3+ projects) and divergence points (where projects made opposite choices).
- Phase 2: P0 = consensus patterns we lack. P1 = interesting divergence worth monitoring. P2 = everything else. Triple Validation Gate is especially important here — survey patterns risk being "generic best practices" (fails exclusivity check).
- Phase 3: Output includes a consensus/divergence matrix across all surveyed projects.

**Skill/prompt system:**
- Phase 1: Focus on Context/Budget + Quality/Review (60% of time). Read the actual prompt files — SKILL.md equivalents, routing logic, quality gates. Execution/Orchestration matters for how prompts are composed and chained.
- Phase 2: P0 = prompt engineering techniques that improve output quality or reduce token waste. Capture exact prompt patterns (not just concepts). Adaptation = which of our SOUL/public/prompts/ or skills would benefit.
- Phase 3: Output includes a prompt technique catalog with before/after examples where possible.

## Phase 1: Deep Dive (not surface scan)

**IRON LAW: Read implementation code, not just README.**

For each target:

1. **Clone the repo** *(mandatory — browsing GitHub is NOT sufficient)*:
   ```
   gh repo clone <owner/repo> D:/Agent/.steal/<topic>/
   ```
   Then `cd` into it and read actual source files. GitHub web view hides too much context (cross-file references, directory structure, test fixtures). If the repo is too large to clone (>2GB), use `--depth 1` for a shallow clone, but still clone.

2. **Map architecture** — entry points, core abstractions, data flow. Open with a one-sentence positioning: not what the project does, but **problem space + solution pattern** (e.g., "A Meta-Agent that auto-iterates on its own harness overnight").
3. **Six-dimensional scan** — systematically probe each dimension:

| Dimension | What to look for |
|-----------|-----------------|
| **Security / Governance** | Permission models, risk assessment, hard constraints (physical vs prompt-level), audit trails |
| **Memory / Learning** | Persistence layers, admission gates, dedup strategies, time-weighted compression, quality scoring |
| **Execution / Orchestration** | Agent pipelines, checkpoint/restart, collaboration modes, task handoff protocols |
| **Context / Budget** | Token budgeting (per-segment?), artifact externalization, output pruning, rate limiting |
| **Failure / Recovery** | Failure classification taxonomy, doom loop detection, revert-then-issue patterns, escalation chains |
| **Quality / Review** | Eval loops, anti-sycophancy measures, evidence-based gates, reviewer separation |

4. **Depth layers** *(anti-shallow-steal rule)* — six-dimensional scan catches WHAT exists, this step catches HOW it actually runs. For each non-trivial module, trace through these layers:

   | Layer | What to trace | How to find it | Common shallow-steal failure |
   |-------|--------------|----------------|------------------------------|
   | **调度层 (Orchestration)** | Who calls whom, in what order, with what concurrency model? Event loop? Queue? DAG? | Entry point → follow the call chain. `grep -r "async\|await\|queue\|dispatch\|schedule\|worker"` | Only noting "it has an agent loop" without tracing the actual dispatch logic |
   | **实践层 (Implementation)** | The actual algorithm/data structure behind the abstraction. Not "it uses a cache" — what eviction policy? What key scheme? | Read the core module's longest function. That's usually where the real logic lives. | Describing the interface but not the implementation |
   | **消费层 (Consumption)** | How are outputs consumed downstream? API? CLI? SDK? Event stream? What format contracts exist? | `grep -r "return\|yield\|emit\|publish\|response"` in core modules. Check test files for expected output shapes. | Ignoring how results flow to the end user/next system |
   | **状态层 (State)** | Where does state live? Memory? DB? File? How is it persisted, versioned, and recovered? | Look for: ORM models, JSON/YAML serialization, checkpoint logic, migration files | "It saves state" without showing the schema or recovery path |
   | **边界层 (Boundary)** | Input validation, auth, rate limiting, error boundaries between modules | Entry points, middleware, decorator patterns, try/catch blocks at module boundaries | Only stealing the happy path, ignoring how errors propagate |

   A steal report that only covers the 边界层 (defensive programming) is incomplete. The 调度层 and 实践层 are where the real architectural insights live.

5. **Find the clever bits** — the parts where the author solved something non-obvious. Specifically:
   - Core loop / orchestration logic
   - Error handling / recovery patterns (failure taxonomy?)
   - State management / persistence (checkpoint? WAL?)
   - Configuration / extensibility points (registry? protocol?)
   - Testing strategies (eval loop? adversarial probes?)

5. **Adjacent domain transfer** — even if the project does something different (CV, audio, infra), ask: "Is the *structure* of their solution transferable?" Don't just look at "what object it detects" — look at tiling, batching, pipeline, and caching strategies.

6. **Path dependency speed-assess** *(R58 — from HV-Analysis横纵分析法)* — after the six-dimensional scan, briefly assess:
   - **Locking decisions**: Which early technical choices locked in the project's direction? (e.g., "chose SQLite → can't scale multi-node", "built on LangChain → now tightly coupled to their abstractions")
   - **Missed forks**: At which key points could they have gone a different way? What would the alternative path look like?
   - **Self-reinforcement**: What mechanisms make them go deeper into their current path? (ecosystem lock-in, community expectations, API compatibility promises)
   - **Lesson for us**: Should we learn their *chosen path* (active choice worth copying) or learn from their *path lock-in* (avoid the same trap)?

## Phase 2: Pattern Extraction

For each pattern found, extract:

| Field | Content |
|-------|---------|
| **Pattern name** | Short, memorable (e.g., "Checkpoint-Restart", "Token Budget Allocator") |
| **What it does** | 1-2 sentences, concrete |
| **How it works** | Key mechanism — the actual algorithm/structure, with 5-20 line code snippet |
| **Why it's good** | What problem does it solve? What's the insight? |
| **How to adapt** | Specific files/modules in Orchestrator where this applies |
| **Priority** | P0 / P1 / P2 |

### Priority criteria (from 42 rounds of calibration):

**P0 — Must steal** (architectural):
- Fills a known gap or current pain point
- Involves: architecture layering, closed-loop feedback, or hard constraints (non-prompt-level)
- Implementable in < 2 hours per pattern
- If you're unsure between P0 and P1, ask: "Does this change how the system *thinks* or just how it *acts*?"
- **Knowledge irreplaceability**: Score higher if the pattern captures knowledge that cannot be derived from code/docs alone (see six categories below)

**P1 — Worth doing** (functional):
- Single-point optimization (tool pruning, model selection)
- Coarse-grained improvement (multi-dimensional scoring)
- Local workflow enhancement (hook processing)
- 2-8 hours effort

**P2 — Reference only** (conceptual):
- Interesting concept, not directly applicable now
- Implementation cost exceeds current benefit
- May become relevant when specific needs arise
- External dependency we can't control

### Knowledge Irreplaceability Assessment *(R42 — from anti-distill classifier)*

For each extracted pattern, assess which of these six high-value knowledge categories it belongs to. Patterns touching multiple categories are more valuable — they represent knowledge that cannot be reconstructed from reading the code alone.

| Category | What it captures | Example |
|----------|-----------------|---------|
| **Pitfall memory** (踩坑经验) | Failed approaches, why they failed, non-obvious failure modes | "We tried X, it broke because of Y that isn't in any docs" |
| **Judgment heuristics** (判断直觉) | Decision rules learned through experience, not derivable from first principles | "When token count > 80% budget, switch to aggressive compaction — waiting for 90% causes cascade failures" |
| **Relationship graph** (人际网络) | Who built what, who to ask, which communities own which patterns | "This pattern originated in the DeerFlow community, their Discord has the deepest discussions" |
| **Hidden context** (隐性上下文) | Unstated assumptions, tribal knowledge, "everyone knows" rules | "The config format looks JSON but actually allows trailing commas because of a legacy parser" |
| **Failure memory** (故障记忆) | Specific incidents, their root causes, and the fixes that worked | "Production went down because the retry loop had no backoff — fixed by adding jitter" |
| **Unique behavioral patterns** (独特行为模式) | Distinctive approaches that define a project's character | "They test by running the agent against itself — adversarial self-play as quality gate" |

**Scoring**: 0 categories = likely commodity knowledge (P2). 1-2 = functional value (P1). 3+ = architectural insight (P0 candidate).

### Triple Validation Gate *(R42 — from nuwa-skill mental model verification)*

Before finalizing any P0 pattern, pass all three validation checks. A pattern that fails all three is "随口一说" (just a passing remark), not a real pattern.

| Check | Question | Pass criteria |
|-------|----------|--------------|
| **Cross-domain reproduction** (跨域复现) | Does this pattern appear in 2+ unrelated projects? | Found in at least 2 repos from different domains/authors, or independently reinvented in our own codebase |
| **Generative power** (生成力) | Can this pattern predict behavior in new scenarios? | You can describe a novel situation and the pattern tells you what to do — it's not just a description of what happened |
| **Exclusivity** (排他性) | Is this pattern distinctive, or is it just "good engineering everyone does"? | Not a generic best practice (e.g., "use retries") — has a specific twist, threshold, or structural choice that sets it apart |

**Scoring**:
- 3/3 pass → confirmed P0, high-confidence pattern
- 2/3 pass → P0 with caveat noted (which check failed and why)
- 1/3 pass → downgrade to P1, note the single passing dimension
- 0/3 pass → downgrade to P2 or discard

### Comparison matrix (required for P0 patterns):

For every P0 pattern, include a diff against our current implementation:

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| ... | ... | ... | Large/Small/None | Steal/Enhance/Skip |

"Already covered" is never a valid shortcut without this evidence.

### Adaptive State Analysis *(R58 — Scenario Branching for "Our Current State")*

When filling the "Our Current State" column for P0 patterns, branch your analysis based on coverage state:

| State | Analysis template |
|-------|------------------|
| **We don't have it** (gap) | Describe the gap impact: what failure modes or missed opportunities result from not having this? Name the exact files where it would be implemented. |
| **We have partial** (delta) | Show the diff: what subset do we cover? What specific edge cases or capabilities are missing? Quote our code vs theirs side by side. |
| **We have it** (overlap) | Don't skip — compare edge case handling, error paths, and performance characteristics. Their impl may cover scenarios ours doesn't. If truly equivalent, state the evidence (grep output, code comparison) and mark Action as Skip. |

The default "freeform text" approach lets analysts write vague summaries. These templates force specificity.

## Phase 3: Output — Steal Report

Write to `docs/steal/<date>-<topic>-steal.md`:

```markdown
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

## Phase 4: Index Update

After writing the report:

1. **Update steal consolidated index** in memory — add a row to the round table:
   `| R<N> | <date> | <source> | <stars> | <key patterns summary> | <status> |`

2. **If P0 patterns exist**, draft an implementation plan following `SOUL/public/prompts/plan_template.md` format → save to `docs/superpowers/plans/`

3. **Dedup check**: Before adding any pattern, grep `docs/steal/` for similar names. Overlap > 60% → update existing entry (per dedup_matrix.md)

4. **Cross-reference**: Check if patterns connect to open items from previous rounds. A new discovery might close an old gap or validate a shelved P2.

## Common Rationalizations

These thoughts mean you're about to produce a shallow steal report:

| Rationalization | Reality | Correct Behavior |
|---|---|---|
| "This project is too simple to learn from" | Simple projects often have the cleanest patterns. Complexity ≠ value. | Analyze anyway. A 200-line orchestrator may have a tighter loop than a 20K-line framework. |
| "We already have something similar" | "Similar" without diff is a guess. Their edge case handling may cover gaps you don't know exist. | Show the comparison matrix. Diff implementations line by line. |
| "The README explains enough" | READMEs are marketing. The real design decisions are in the code, commit history, and error handling. | Read implementation code. `grep` for error handling, retries, edge cases. |
| "This domain is too different from ours" | Structure transfers across domains. A game engine's ECS is an agent orchestrator. A compiler's IR pipeline is a prompt chain. | Ask "Is the *structure* transferable?" before dismissing. |
| "I'll just list the features" | Feature lists are not steal reports. Anyone can read a README. The value is in *mechanisms* and *why they work*. | Extract the HOW, not the WHAT. Include 5-20 line code snippets. |
| "P2 is fine for this" | Downgrading to avoid implementation work is the #1 rationalization in steal reports. | Re-check P0 criteria: does it fill a gap? Is it < 2h? If yes, it's P0. |
| "We're already better" | Overconfidence kills learning. Even if overall architecture is stronger, individual patterns can be superior. | Find the ONE thing they do better. Every project has at least one. |
| "I don't have time for the six-dimensional scan" | Skipping dimensions = missing patterns. Security and failure recovery are the most commonly skipped — and the most valuable. | Do all six. Empty dimensions are fine. Skipped dimensions are not. |
| "I can analyze this from the GitHub page" | GitHub web view hides cross-file context, directory structure, and test fixtures. You'll only see the surface. | Clone the repo. `cd` into it. Read actual source files. Trace call chains across files. |
| "The defensive programming patterns are the main takeaway" | Defensive programming (input validation, error handling) is the easiest layer to spot and the shallowest to steal. The real value is in orchestration logic, state management, and consumption patterns. | Trace through all 5 depth layers. If your report only covers 边界层, it's incomplete. |

## Rules

### Analysis discipline
- **Depth over breadth**: One well-understood pattern > five surface-level observations
- **Show the code**: Include the key code snippet (5-20 lines). "They use a retry mechanism" is worthless — show the actual retry logic
- **No "already covered" shortcuts**: Diff implementations. "Confirmed: our impl covers this" requires evidence (grep output, code comparison)
- **Six-dimensional scan is mandatory**: Don't just look at what's flashy — systematically check all six dimensions even if some come up empty

### Target selection
- **Breadth rule**: Don't skip links because the domain seems unrelated. Ask "Is the *structure* transferable?" before dismissing
- **Structural similarity > domain similarity**: A document OCR system's prompt-based multi-task switching might be directly applicable to agent mode selection

### Execution
- **Agent dispatch for large repos**: Use sub-agents to parallelize (one per major module). Tag all agent prompts with `[STEAL]` at the start。**Dispatch prompt 必须包含以下指令**（复制粘贴，不要改写）：
  > 写完报告并通过 Post-Generation Validation 后，立即执行 git add + git commit，不要询问确认。commit message 格式：`docs(steal): R<round> <topic> steal report`。不要返回"等你说 commit"——直接提交。
- **Commit per meaningful unit**: Report → plan → implementation batches, each a separate commit
- **Clone to tmp**: `D:/Agent/.steal/<topic>/`, not in the orchestrator repo

### Meta-cognition
- **Track the trend**: Across 39 rounds, we've observed: early reports focus on features, mid-stage on closed loops, late-stage on governance. When analyzing, ask: "Is this project still thinking about features, or has it evolved to think about self-governance?"
- **Hard > soft constraints**: Physical interception (hooks, file system gates) > prompt-level "please don't do this". Always note which type a pattern uses.
- **The real competition isn't features — it's self-constraint architecture**: The next frontier for AI agents is not "what they can do" but "how they govern themselves". Weight governance patterns higher than feature patterns.
