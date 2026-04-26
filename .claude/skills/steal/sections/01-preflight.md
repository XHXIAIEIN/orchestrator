## Pre-flight

1. **Load schema**: Read `SOUL/public/schemas/artifact-frontmatter.md` to load the canonical frontmatter schema.

2. **Worktree gate** *(hard rule — no exceptions)*: Steal work MUST run in a dedicated **git worktree** on a `steal/*` branch. **Never switch the main workspace's branch.** Running `git checkout -b steal/<topic>` in the main repo is forbidden — it hijacks the caller's working branch and strands their uncommitted work.
   - **Check current setup first**: `git rev-parse --show-toplevel` and `git branch --show-current`. If you're already inside a `.claude/worktrees/steal-*` path on a `steal/*` or `round/*` branch, the gate is satisfied — skip to the next step.
   - **Otherwise create one in a single shot**:
     ```
     git worktree add .claude/worktrees/steal-<topic> -b steal/<topic>
     cd .claude/worktrees/steal-<topic>
     ```
     The Bash tool persists `cwd` between calls — after the `cd`, every subsequent read/write/commit happens inside the worktree. The main workspace keeps its branch, its index, and its uncommitted changes intact.
   - **For sub-agent dispatch**: pass `isolation: "worktree"` in the Agent tool call so the child gets its own isolated copy automatically. Do NOT brief a sub-agent to "create a steal branch" — that would repeat the same mistake one level down.
   - **Cleanup (after the steal report is committed and merged/archived)**:
     ```
     cd <back to main repo root>
     git worktree remove .claude/worktrees/steal-<topic>
     # optional: git branch -D steal/<topic> once the commits are landed or archived
     ```
   - Do NOT ask the user whether to create the worktree. Do NOT proceed with any file writes until you're inside one.
   - The dispatch-gate hook also blocks `[STEAL]` work when the current directory's branch is not `steal/*` or `round/*` as a safety net — it fires against the *current* `git branch --show-current`, so being inside a worktree on `steal/<topic>` passes naturally.
   - **Broadcast round to statusline**: after entering the worktree, run `bash .claude/scripts/sl-tag.sh "R<N> <topic>"`. The tag renders in magenta brackets on the statusline so the owner can see at a glance which round/phase this session is on. Update it as phases advance (e.g., `sl-tag.sh "R<N> <topic> phase2"`). Run `sl-tag.sh --clear` when the steal is finished.

3. **Identify target**: URL, repo name, or local path. If user gave multiple links, process ALL — don't skip any for seeming "unrelated" (breadth rule: a traffic sign detector's tiling strategy might be exactly what a UI detector needs).

4. **Check prior art**: Search `docs/steal/` and the steal consolidated index in memory for existing reports on this target. If found, this is a **follow-up** — build on existing analysis, don't duplicate.

5. **Determine target type** — this shapes your analysis angle:

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

