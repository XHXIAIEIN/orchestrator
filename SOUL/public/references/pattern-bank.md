# Pattern Bank — Cross-Session Knowledge Accumulation

> Auto-curated from 46 rounds of steal operations. Updated after each steal round.
> Contains the most transferable, highest-impact patterns across all sources.
>
> **Consult this before starting a new steal** — if a pattern is already here,
> you're looking for a refinement, not a new discovery.

## Governance Patterns (most transferable)

| Pattern | Core Mechanism | Why It Matters | First Seen |
|---------|---------------|----------------|------------|
| Authority Ceiling | 4-tier READ→APPROVE with tool caps | Prevents privilege escalation in multi-agent | R1 |
| Gate Functions | Pre-checks before dangerous operations | Physical barrier > prompt-level "don't" | R26 (superpowers) |
| Rationalization Immunity Table | Map excuse→correct behavior | Agents rationalize skipping safety | R26 (superpowers) |
| Data Contract | User Layer (sacred) vs System Layer (replaceable) | Safe auto-update prerequisite | R46 (career-ops) |
| Verification Gate | 5-step evidence chain before "done" claims | Prevents premature completion | R24 (superpowers) |
| Blast Radius Estimation | Score 0-10 before destructive ops | Quick risk assessment without LLM call | R14 (ClawHub) |

## Execution Patterns (most reused)

| Pattern | Core Mechanism | Why It Matters | First Seen |
|---------|---------------|----------------|------------|
| Rollout-Attempt | Auto-retry with per-attempt tracking | Structured failure recovery | R8 (Agent Lightning) |
| Checkpoint-Restart | Durability modes (sync/async/exit) | Resume after crash | R30 (yoyo-evolve) |
| File-based IPC | Each worker writes to own file, merge after | Crash-safe parallel execution | R46 (career-ops) |
| 3-Fix Escalation | 3 consecutive failures → escalate to human | Prevents infinite retry loops | R35 (Hermes) |
| Scout-then-Execute | Cheap model scouts, expensive model executes | Token cost reduction | R1 |

## Memory Patterns (converging across projects)

| Pattern | Core Mechanism | Why It Matters | First Seen |
|---------|---------------|----------------|------------|
| 4-Layer Memory Stack | L0 wake (tiny) → L1 boot → L2 search → L3 archive | Progressive disclosure saves tokens | R44 (MemPalace) |
| Evidence Grading | verbatim > artifact > impression | Higher tier wins in conflicts | R42 (persona-distill) |
| Temporal KG | Triple store with as_of() and invalidation | Facts expire; relationships change | R44 (MemPalace) |
| Content-Hash Dedup | SHA256 → skip if unchanged | O(1) dedup for embeddings | R45a (Graphify) |
| Hot/Warm/Cold Tiers | Access frequency drives promotion/demotion | Memory stays relevant without manual curation | R14 (ClawHub) |

## Prompt Engineering Patterns (highest ROI)

| Pattern | Core Mechanism | Why It Matters | First Seen |
|---------|---------------|----------------|------------|
| `<critical>` Tags | XML attention markers for key rules | Measurable compliance improvement | R19 (ResearcherSkill) |
| Positive Framing | "Use Y to preserve Z" > "Don't do X" | Models follow positive instructions better | R19 (ResearcherSkill) |
| `<reference>` Wrapping | Lower-priority context in reference tags | Reduces noise without removing info | R19 (ResearcherSkill) |
| Self-Contained Worker Prompt | All info in one file, no external deps | Enables parallel batch execution | R46 (career-ops) |
| Intent Packet | Structured input to reviewer agents | Prevents "headless deliberation" | R22 (Review Swarm) |

## Quality Patterns (anti-sycophancy)

| Pattern | Core Mechanism | Why It Matters | First Seen |
|---------|---------------|----------------|------------|
| Fact-Expression Split | Separate fact extraction from narrative | Anti-sycophancy at architecture level | Research |
| Severity × Confidence | Two-dimensional issue scoring | Better than binary pass/fail | R22 (Review Swarm) |
| Forced Output Gate | Must produce evidence before claiming done | Prevents skipping verification | R19 (ResearcherSkill) |
| Anti-Degradation Protocol | Eval baseline before self-modification | Self-improvement can regress | R14 (ClawHub) |
| Triple Validation Gate | Cross-domain + generative + exclusivity | Prevents "generic best practice" patterns | R42 (persona-distill) |

---

## How to Update This Bank

After completing a steal round:
1. Check if any P0 pattern belongs in an existing category above
2. If the pattern is genuinely new (not a refinement), add a row
3. If it refines an existing pattern, update the mechanism description
4. Keep each category ≤ 10 entries — if full, replace the least-referenced one

**Criteria for bank admission**: Pattern must have been implemented AND validated in production use.
Theoretical patterns (P2/ref-only) do not belong here.
