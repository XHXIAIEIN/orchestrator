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

1. **Branch gate**: Current branch MUST match `steal/*` or `round/*`. If not:
   ```
   git checkout -b steal/<topic>
   ```
   The dispatch-gate hook blocks `[STEAL]` work on other branches.

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

## Phase 1: Deep Dive (not surface scan)

**IRON LAW: Read implementation code, not just README.**

For each target:

1. **Clone or browse** the repo (`gh repo clone` to `D:/Agent/tmp/steal/<topic>/`)
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

4. **Find the clever bits** — the parts where the author solved something non-obvious. Specifically:
   - Core loop / orchestration logic
   - Error handling / recovery patterns (failure taxonomy?)
   - State management / persistence (checkpoint? WAL?)
   - Configuration / extensibility points (registry? protocol?)
   - Testing strategies (eval loop? adversarial probes?)

5. **Adjacent domain transfer** — even if the project does something different (CV, audio, infra), ask: "Is the *structure* of their solution transferable?" Don't just look at "what object it detects" — look at tiling, batching, pipeline, and caching strategies.

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

### Priority criteria (from 39 rounds of calibration):

**P0 — Must steal** (architectural):
- Fills a known gap or current pain point
- Involves: architecture layering, closed-loop feedback, or hard constraints (non-prompt-level)
- Implementable in < 2 hours per pattern
- If you're unsure between P0 and P1, ask: "Does this change how the system *thinks* or just how it *acts*?"

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

### Comparison matrix (required for P0 patterns):

For every P0 pattern, include a diff against our current implementation:

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| ... | ... | ... | Large/Small/None | Steal/Enhance/Skip |

"Already covered" is never a valid shortcut without this evidence.

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
- **Agent dispatch for large repos**: Use sub-agents to parallelize (one per major module). Tag all agent prompts with `[STEAL]` at the start
- **Commit per meaningful unit**: Report → plan → implementation batches, each a separate commit
- **Clone to tmp**: `D:/Agent/tmp/steal/<topic>/`, not in the orchestrator repo

### Meta-cognition
- **Track the trend**: Across 39 rounds, we've observed: early reports focus on features, mid-stage on closed loops, late-stage on governance. When analyzing, ask: "Is this project still thinking about features, or has it evolved to think about self-governance?"
- **Hard > soft constraints**: Physical interception (hooks, file system gates) > prompt-level "please don't do this". Always note which type a pattern uses.
- **The real competition isn't features — it's self-constraint architecture**: The next frontier for AI agents is not "what they can do" but "how they govern themselves". Weight governance patterns higher than feature patterns.
