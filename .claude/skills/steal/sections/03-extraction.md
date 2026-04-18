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
