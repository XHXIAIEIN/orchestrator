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
