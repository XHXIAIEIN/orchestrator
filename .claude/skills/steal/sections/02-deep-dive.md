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

