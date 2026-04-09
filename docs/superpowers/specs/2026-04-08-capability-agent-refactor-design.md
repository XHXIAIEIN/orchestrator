# Capability + Agent Architecture Refactor

**Date**: 2026-04-08
**Status**: Design reviewed (2 rounds), all P0/P1 resolved, pending implementation plan
**Scope**: Replace `departments/` (6 ministries) with `capabilities/` (15 atoms) + `agents/` (8 roles)
**Reviews**:
- Round 1: `2026-04-08-capability-agent-refactor-review.md` (3 P0 / 3 P1 → all resolved)
- Round 2: `2026-04-08-capability-agent-refactor-deep-analysis.md` (1 P0 / 4 P1 → all resolved)
- Round 3: `2026-04-08-capability-agent-refactor-round3-audit.md` (1 P0 / 5 P1 → all resolved)
- Round 4: `2026-04-08-capability-agent-refactor-round4-deep-review.md` (3 P0 / 4 P1 → all resolved. Fact-expression split moved from FSM to dispatcher; FSM simplified)
- Round 5: `2026-04-08-capability-agent-refactor-round5-review.md` (2 P0 / 4 P1 → all resolved. active_capabilities filters full compose; model_floor added)
- Round 6: `2026-04-08-capability-agent-refactor-round6-review.md` (6 HIGH → all resolved. Phase 0.5 sub-tasks; FSM executor=Governor; semaphore 3-tier)
- Round 7: `2026-04-08-capability-agent-refactor-round7-review.md` (5 P1 → all resolved. active_capabilities reverted; Override Stack table; rollback flag)
- Round 8: `2026-04-08-capability-agent-refactor-round8-deep-audit.md` (3 P0 / 5 P1 → P0s resolved; 40+ file impact)
- Codex: `2026-04-09-capability-agent-refactor-codex-review.md` (3 blockers → all resolved. Rollback, gateway, budget)
- Adversarial-1: `2026-04-09-capability-agent-refactor-adversarial-review.md` (2 CRITICAL / 5 HIGH → resolved)
- Adversarial-2: `2026-04-09-capability-agent-refactor-adversarial-review-deep.md` (4 CRITICAL / 15 HIGH → resolved)
- Adversarial-3: `2026-04-09-capability-agent-refactor-adversarial-review.md` (3 P0 + complexity overload → **v1 scope reduction**: ad-hoc/scenarios/model_floor/restrict_tools/L2 deferred to low-priority; compose binds intent; materialization replaces version pinning)

## Motivation

45 rounds of steal-study across 100+ agent projects revealed a universal convergence: the functional primitives underlying all agent orchestration systems are the same — collect, review, plan, test, develop, verify, etc. The Three Departments and Six Ministries naming is historical baggage that obscures these primitives and makes the architecture harder to reason about.

**Core insight**: WHO (identity) and WHAT (capability) must be separated. Every studied project agrees — they only differ in granularity and composition method.

## v1 Scope (post-adversarial complexity reduction)

After 12 rounds of review, the design accumulated 14 cross-cutting concepts. The final adversarial review identified this as complexity overload for v1. The following scope split applies:

### v1 — Ship Now

| Concept | Status |
|---------|--------|
| capability (15) + agent (8) two-layer split | Core |
| compose engine (L0 merge + L1 agent override + L3 intent) | Core |
| declarative FSM (pure string transitions) | Core |
| intent with active_capabilities + authority_cap + profile | Core |
| dispatcher async pipeline (Phase 0/1/2) | Core |
| Phase 0.5 fact-expression split (in dispatcher) | Core |
| ARCHITECTURE_VERSION v1/v2 flag | Core |
| compose results materialized to DB (no live registry dependency) | Core |
| compose(agent, intent) as single entry point | Core |
| Governor as FSM executor + multi-agent parallel dispatch | Core |

### Low Priority — Defer to v2

| Concept | Reason | Workaround in v1 |
|---------|--------|-------------------|
| ad-hoc mode (`resolve_adhoc(capabilities=[...])`) | 10% usage, 50% complexity; introduces permission bypass | Use explicit agent+intent dispatch |
| scenarios.yaml + reducer config | Abstraction over existing PARALLEL_SCENARIOS | Keep hardcoded scenarios in code |
| model_floor on capability | Adds conflict with profile ceiling | intent.model explicit declaration suffices |
| restrict_tools on intent | Patch for active_caps not filtering tools | Tools come from all caps; scrutiny gates dangerous usage |
| specialization dynamic routing | Current divisions routing is rarely used | Specialization dirs exist but prompt loaded statically via intent config |
| hot reload version-pinned snapshots | Compose materialization makes this unnecessary for v1 | In-flight tasks use frozen ComposedSpec from DB |
| L2 override (blueprint) | Zero consumers in current system | Removed from override stack entirely |
| Greedy set-cover capability→agent matching | Only needed by ad-hoc mode | Governor explicitly names agents |

### Key Simplifications

1. **One entry point**: `compose(agent_key, intent)` — no ad-hoc, no resolve_adhoc, no dispatch(capabilities=[...])
2. **No intent = default intent**: `compose(agent_key)` auto-binds to agent's `default: true` intent — never produces a full-capability unrestricted spec
3. **Override stack = 3 layers** (L0/L1/L3): L2 deleted, not reserved
4. **Multi-agent parallel**: Governor explicitly dispatches named agents — no automatic capability matching
5. **Compose materialized at task creation**: task row stores full ComposedSpec; execution reads from DB, not live registry

## Architecture

Two-layer system:

```
capabilities/    WHAT — functional atoms (tools, authority, prompt, rubric)
agents/          WHO  — execution roles (identity + capability composition)
```

Capabilities have no identity. Agents have identity and declare which capabilities they compose.

### 15 Capability Atoms

| Capability | Purpose | Authority | Model |
|------------|---------|-----------|-------|
| `develop` | Write new code, fix bugs | MUTATE | sonnet |
| `refactor` | Structural refactoring, large-scale rewrites | MUTATE | opus |
| `plan` | Task decomposition, solution design | READ | opus |
| `review` | Code quality review, find bugs | READ | sonnet |
| `discipline` | Anti-sycophancy, review rigor, fact-layer integrity | READ | sonnet |
| `test` | Run tests, verify coverage | EXECUTE | sonnet |
| `audit` | Security scanning, CVE, permission checks | READ | sonnet |
| `secure` | Injection detection, approval gating | READ | haiku |
| `operate` | Infrastructure repair, Docker, DB | MUTATE | sonnet |
| `collect` | Data collection, event stream processing | MUTATE | haiku |
| `compress` | Context compression, summarization | READ | haiku |
| `monitor` | Health assessment, anomaly detection | EXECUTE | haiku |
| `inspect` | TODO scanning, doc rot, config drift | READ | haiku |
| `verify` | End-to-end verification, evidence chain | EXECUTE | sonnet |
| `express` | Expression layer rewriting, tone adjustment | READ | haiku |

### Authority Levels (Deep Analysis P1-2)

Four authority levels, ordered:

```
READ < EXECUTE < MUTATE < APPROVE
```

| Level | Permissions |
|-------|------------|
| READ | Read files, grep, glob — no shell execution |
| EXECUTE | READ + run shell commands (pytest, diagnostics) — no source file modification |
| MUTATE | EXECUTE + write/edit/delete files |
| APPROVE | MUTATE + approval authority |

`can_network` remains a separate boolean, not part of the authority hierarchy.

### Authority → Tool Mapping (from round 3 P1-6)

```python
CEILING_TOOL_CAPS = {
    "READ":    {"Read", "Glob", "Grep"},                          # no shell execution
    "EXECUTE": {"Read", "Glob", "Grep", "Bash"},                  # + shell commands, no file writes
    "MUTATE":  {"Read", "Glob", "Grep", "Bash", "Write", "Edit"}, # + file modification
    "APPROVE": {"Read", "Glob", "Grep", "Bash", "Write", "Edit"}, # + approval authority
}

# Always available regardless of authority (round 4 P1-1)
ALWAYS_AVAILABLE = {"TaskCreate", "TaskUpdate", "TaskGet", "TaskList", "TaskStop"}

# Gated by can_network flag, not authority
NETWORK_TOOLS = {"WebSearch", "WebFetch"}

# Gated by can_spawn_agents flag
AGENT_TOOLS = {"Agent"}

def resolve_tools(authority, can_network=False, can_spawn_agents=False):
    tools = CEILING_TOOL_CAPS[authority] | ALWAYS_AVAILABLE
    if can_network:
        tools |= NETWORK_TOOLS
    if can_spawn_agents:
        tools |= AGENT_TOOLS
    return tools
```

Key change from current system: **READ no longer includes Bash**. Pure READ capabilities (review, discipline, audit, inspect) can only read files. EXECUTE capabilities (test, monitor, verify) can run commands but not modify source files.

**Design note (from review P0-3)**: The original `guard` capability was split into `secure` (security-layer gating, belongs to sentinel) and `discipline` (review rigor / anti-sycophancy, belongs to reviewer). This ensures the Fact-Expression Split's Phase 1 retains anti-sycophancy protection through reviewer's discipline capability.

Each capability is a directory:

```
capabilities/{key}/
  manifest.yaml    # tools, authority, model, paths, blast_radius, preflight
  prompt.md        # instruction fragment injected into agent
  rubric.yaml      # eval scoring dimensions and weights
  denials.jsonl    # policy denial records (migrated from departments)
  guidelines/      # safe harbor guidelines (migrated from departments)
  specializations/ # sub-specialization prompts + exam cases (from divisions)
    {spec_name}/
      prompt.md
      exam.md
      exam_cases.jsonl
```

### Specializations (from Divisions — Deep Analysis P0-1)

Each department's divisions (20 total) map to capability specializations. Intent routing specifies which specialization to load:

```yaml
# agents/engineer.yaml
intents:
  code_fix:
    specialization: implement    # → develop/specializations/implement/prompt.md
  code_scaffold:
    specialization: scaffold     # → develop/specializations/scaffold/prompt.md
```

Prompt assembly becomes four layers:
```
agent.identity
  + authority context line (if authority_cap restricts — round 5 P1-C2)
  + capability.prompt.md                        # generic (weight-descending order)
  + capability.specializations/{spec}/prompt.md # refined (if intent specifies)
```

Authority context injection (round 5 P1-C2): when intent authority_cap differs from agent's full authority, inject a clarifying line after identity:
```
[Authority: READ — this task is observation-only. Analyze and recommend, do not modify files.]
```
This prevents identity-authority cognitive dissonance (e.g., architect identity says "refactor" but tools are read-only).

Division migration mapping:
| Old division | New capability/specialization |
|---|---|
| engineering/implement | develop/implement |
| engineering/scaffold | develop/scaffold |
| engineering/integrate | develop/integrate |
| engineering/orchestrate | plan/orchestrate |
| quality/review | review/review |
| quality/detect | review/detect |
| quality/compare | review/compare |
| quality/gate | discipline/gate |
| operations/operate | operate/operate |
| operations/budget | operate/budget |
| operations/collect | collect/collect |
| operations/store | operate/store |
| protocol/interpret | inspect/interpret |
| protocol/calibrate | express/calibrate |
| protocol/communicate | express/communicate |
| protocol/polish | express/polish |
| personnel/analyze | monitor/analyze |
| personnel/recall | monitor/recall |
| personnel/evaluate | monitor/evaluate |
| personnel/chronicle | monitor/chronicle |

### 8 Agents

| Agent | Identity | Capabilities | Authority | Model |
|-------|----------|-------------|-----------|-------|
| `engineer` | Writes code | develop(0.7), test(0.3) | MUTATE | sonnet |
| `architect` | Designs and refactors | plan(0.5), refactor(0.5) | MUTATE | opus |
| `reviewer` | Reviews code | review(0.7), discipline(0.3) | READ | sonnet |
| `sentinel` | Security patrol | audit(0.7), secure(0.3) | READ | sonnet |
| `operator` | Manages infrastructure | operate(0.5), collect(0.3), compress(0.2) | MUTATE | sonnet |
| `analyst` | Metrics and health | monitor(1.0) | EXECUTE | haiku |
| `inspector` | Docs and expression | inspect(0.6), express(0.4) | READ | haiku |
| `verifier` | E2E verification | verify(0.6), test(0.4) | EXECUTE | sonnet |

Numbers in parentheses are rubric weights for evaluation scoring.

Each agent is a YAML file:

```yaml
# agents/{key}.yaml
key: engineer
description: "Write code, fix bugs, run tests"
tags: [code, implement, build, debug, fix, feature]

identity: |
  You are an engineer. You write correct, minimal code
  that directly addresses the task.

capabilities:
  - key: develop
    weight: 0.7
  - key: test
    weight: 0.3

overrides:        # optional — override compose() defaults
  max_turns: 25
  timeout_s: 300

transitions:
  done: quality_review
  fail: log_only
  retry: __self__
  escalation: ""

intents:
  code_fix:
    description: "Fix a bug or resolve an error"
    profile: BALANCED
    authority_cap: MUTATE
    active_capabilities: [develop, test]  # all caps active
    default: true
  code_feature:
    description: "Implement a new feature"
    profile: HIGH_QUALITY
    authority_cap: MUTATE
    active_capabilities: [develop, test]
```

### Mapping from Old to New

| Old (department) | New (agent) | Change |
|------------------|-------------|--------|
| engineering/工部 | engineer + architect | Refactor split out to architect (opus) |
| quality/刑部 | reviewer | Anti-sycophancy → discipline capability on reviewer |
| security/兵部 | sentinel | audit(sonnet) + secure(haiku), model stays sonnet |
| operations/户部 | operator | collect + compress made explicit |
| personnel/吏部 | analyst | monitor only (verify moved to verifier) |
| protocol/礼部 | inspector | inspect + express (expression layer) |

## CapabilityComposer

Core merge engine. Input: N capabilities + 1 agent definition. Output: `ComposedSpec`.

### Merge Strategies (union-oriented)

| Dimension | Strategy | Rationale |
|-----------|----------|-----------|
| tools | **union** | Need all tools from all capabilities |
| authority | **max** (READ < EXECUTE < MUTATE < APPROVE) | Need strongest permission |
| model | **max** (haiku < sonnet < opus) | Need most capable model |
| writable_paths | **union** | All writable paths needed |
| forbidden_paths | **union** | All forbidden paths accumulate |
| blast_radius | **max** | Combined task scope is larger |
| rubric | **weighted merge** | Per agent-declared capability weights |
| prompt | **weight-descending concat** | Higher-weight capability prompts placed LAST (exploits LLM recency bias) |

### Intent-Level Authority Cap (from review P1-2)

Authority merge gives the maximum permission from all capabilities. But some intents don't need full permissions. Each intent can declare an `authority_cap` that constrains the final authority:

```
compose(plan, refactor) → MUTATE (from refactor)
  → intent: design_plan (authority_cap: READ)
  → final authority: READ
```

This prevents planning tasks from getting write access, while refactoring tasks through the same agent still get MUTATE.

### Intent-Level Capability Filtering (from deep analysis P2-6 + round 3 P1-9)

Each intent declares which capabilities are **active**. This filters **prompt injection and rubric weights only** — NOT model, tools, or authority (round 7 P1-1: reverted from round 5's full-chain filtering to prevent active_capabilities from becoming a "hidden agent factory" that breaks agent identity stability).

```python
def compose(agent_key, intent=None):
    agent = AGENTS[agent_key]
    all_caps = [CAPABILITIES[c.key] for c in agent.capabilities]

    # Step 1: Model/tools/authority ALWAYS merge from ALL capabilities
    tools     = union(c.tools for c in all_caps)
    authority = max(c.authority for c in all_caps)
    model     = max(c.model for c in all_caps)

    # Step 2: active_capabilities filters ONLY prompt + rubric
    if intent and intent.active_capabilities:
        active = [c for c in all_caps if c.key in intent.active_capabilities]
    else:
        active = all_caps
    prompts = [load_prompt(c) for c in sorted(active, key=weight)]
    rubric  = weighted_merge(active, agent.capability_weights)

    # Step 3: L1-L3 overrides (intent.model is explicit hard override)
    if intent and intent.model:
        model = intent.model       # explicit intent-level model (visible, auditable)
    if intent and intent.authority_cap:
        authority = min(authority, intent.authority_cap)
    # profile ceiling with model_floor...
```

Intent authors who need a different model/authority must declare it explicitly:

```yaml
# operator — model varies by intent, explicitly declared
intents:
  docker_fix:
    active_capabilities: [operate]
    model: sonnet                     # explicit — not derived from filtering
    authority_cap: MUTATE
  data_collect:
    active_capabilities: [collect]
    model: haiku                      # explicit downgrade — visible in YAML
    profile: LOW_LATENCY
```

This preserves agent identity stability: same agent key always produces the same base spec; intent-level overrides are explicit and auditable.

Examples:
- operator/docker_fix: `active_capabilities: [operate]` → only operate.prompt, no collect/compress noise
- architect/design_plan: `active_capabilities: [plan, refactor]` + `authority_cap: READ` → both prompts injected (refactor domain knowledge), but write tools blocked
- engineer/code_fix: `active_capabilities: [develop, test]` → both prompts (all caps active)

If `authority_cap` is not declared, defaults to agent's compose-level authority (not APPROVE — adversarial review D1 security fix — round 3 P2-2).

This is strictly better than permission-only blocking: LLM never sees irrelevant instructions, no wasted tool-call retries, no misleading output.

### Intent Profile Preservation (from deep analysis P1-4)

The current LOW_LATENCY / BALANCED / HIGH_QUALITY profile system is preserved. Profile resolution enters the Override Stack at L3:

```
L0: Capability merge → model=opus (from plan)
L1: Agent overrides
L2: Blueprint overrides
L3: Intent profile (LOW_LATENCY → haiku, 10 turns, 120s) + authority_cap
```

Profile acts as a **ceiling** — it can lower model/turns/timeout from compose defaults but never raise them. However, capabilities can declare a **model_floor** that profile cannot breach (round 5 P1-B1):

```python
floor = max(c.model_floor for c in active_caps)    # non-negotiable minimum
ceiling = profile.model if profile else "opus"       # profile suggestion
composed.model = max(floor, min(compose_model, ceiling))
```

Example: architect + LOW_LATENCY → compose=opus, ceiling=haiku, floor=opus → **opus** (floor wins).
Example: operator/data_collect + LOW_LATENCY → compose=haiku, ceiling=haiku, floor=haiku → **haiku** (correct).

This preserves the fast path for trivial tasks while protecting capabilities that require high-end models.

### Safety Layers

Safety is NOT in the compose layer. Three layers:

```
Layer 1: compose()        = capability union (what you CAN do)
Layer 2: agent.yaml       = role constraints (overrides)
Layer 3: intent authority_cap + scrutiny = runtime gate
```

### Override Stack (4 layers)

```
L0: Capability merge defaults (compose output from ALL capabilities)
L1: Agent overrides (agents/{key}.yaml → overrides section)
L2: RESERVED — not implemented in v1. No consumer exists. Extension point only.
L3: Intent-level (intent.model, intent.authority_cap, intent.profile)
```

### Dimension Resolution Table (v1 — L0/L1/L3 only, L2 reserved)

| Dimension | L0 (cap merge) | L1 (agent) | L3 (intent) | Rule |
|-----------|----------------|------------|-------------|------|
| **model** | max(all caps) | hard override | explicit = hard override but **floor-constrained**: `max(floor, intent.model)`; profile = ceiling: `min(prev, profile)` | Floor always wins; explicit intent still respects floor |
| **max_turns** | max(all caps) | hard override | profile ceiling: `min(prev, profile)` | Later wins; profile only lowers |
| **timeout_s** | max(all caps) | hard override | profile ceiling | Same as max_turns |
| **authority** | max(all caps) | hard override | cap: `min(prev, cap)`. Default cap = agent's compose authority (not APPROVE) | Cap only lowers |
| **tools** | union(all caps) | — | intent can add `restrict_tools` list (adversarial 5.2) | Union then restrict |
| **rubric** | weighted (active) | — | SPLIT_CONFIG override | Override replaces |
| **prompt** | weight-desc (active) | identity prepended | authority context line injected | Concatenation |
| **blast_radius** | max(all caps) | hard override | — | Later wins |
| **paths** | writable=union, forbidden=union | — | — | Accumulate |

**Model resolution examples** (adversarial review Flow E):
- architect/design_plan: compose=opus, floor=opus, profile=BALANCED → `max(opus, min(opus, sonnet))` = **opus**
- architect/design_plan + LOW_LATENCY: compose=opus, floor=opus, ceiling=haiku → `max(opus, haiku)` = **opus** (floor wins + WARN)
- operator/data_collect: compose=sonnet, intent.model=haiku, floor=haiku → `max(haiku, haiku)` = **haiku**
- operator/data_collect + explicit model=sonnet, floor=haiku → `max(haiku, sonnet)` = **sonnet**

**NOTE**: `intent.model` is NOT a pure "hard override" — it is subject to floor constraint. The term "hard override" in earlier text is corrected here.

### ComposedSpec Output

```python
@dataclass
class ComposedSpec:
    agent_key: str
    identity_prompt: str           # WHO — from agent.yaml
    capability_prompts: list[str]  # WHAT — ordered concat
    tools: list[str]               # merged tool set
    authority: str                 # READ / EXECUTE / MUTATE / APPROVE
    model: str                     # haiku / sonnet / opus
    max_turns: int
    timeout_s: int
    writable_paths: list[str]
    forbidden_paths: list[str]
    rubric: dict[str, float]       # merged scoring dimensions (weighted)
    blast_radius: int
    can_commit: bool
    can_network: bool
```

### Two Invocation Modes

```python
# Single entry point (adversarial P0-2 fix: compose always binds intent)
spec = composer.compose(agent_key="engineer", intent="code_fix")

# Without explicit intent → auto-binds to agent's default intent
spec = composer.compose(agent_key="engineer")
# → resolves to intent="code_fix" (marked default: true in engineer.yaml)
# → NEVER produces full-capability unrestricted spec

# Ad-hoc mode is LOW PRIORITY (v2) — not available in v1
# resolve_adhoc() does not exist in v1
# Multi-agent parallel: Governor explicitly names agents
# governor.dispatch_parallel(["sentinel", "reviewer", "inspector"])
```

Ad-hoc mode never produces an identity-less spec. Single-agent coverage uses that agent's identity. Multi-agent coverage becomes a sequenced or parallel plan:

- **All READ** → parallel Superstep: sentinel ∥ analyst
- **Mixed authority** → sequential (READ agents first, then MUTATE agents)

### Ad-hoc Mode (LOW PRIORITY — v2)

Ad-hoc capability-based dispatch (`resolve_adhoc(capabilities=[...])`) is deferred to v2. In v1, all dispatch goes through `compose(agent_key, intent)`.

When implemented in v2, the following rules from adversarial review 5.1 must apply:
1. Minimum privilege: match requested capabilities to specific intents, not agent-global min
2. MUTATE requires scrutiny HIGH approval
3. Full audit trail

See "Low Priority — Defer to v2" section for rationale.

## Registry Refactor

### Discovery

```python
def _discover_capabilities() -> dict[str, CapabilityEntry]:
    """Scan capabilities/*/manifest.yaml"""

def _discover_agents() -> dict[str, AgentEntry]:
    """Scan agents/*.yaml, resolve capability references"""
```

### Exports

```python
CAPABILITIES: dict[str, CapabilityEntry]
AGENTS: dict[str, AgentEntry]
VALID_AGENTS: set[str]
AGENT_TAGS: dict[str, list[str]]
INTENT_ENTRIES: dict[str, IntentEntry]  # IntentEntry.agent (was .department)
```

### Hot Reload

`reload()` builds new registries then atomic-swaps via single `RegistryState` wrapper (round 6 C4).

**In-flight task safety (v1 approach — materialization, not versioning)**:

`compose()` results are **fully materialized** into the task DB row at creation time. The task carries its own frozen ComposedSpec (identity, prompts, tools, authority, model, rubric). Execution reads from the task row, never from live registry.

This means hot reload cannot affect running tasks — they are self-contained. No version counter or snapshot cache needed in v1. (Version-pinned registry snapshots are LOW PRIORITY for v2, only needed if compose results become too large to store per-task.)

### Naming Conflict Resolution (from review P3-1)

Existing `src/governance/capability_registry.py` (tool-level capability → tool mapping) is renamed to `tool_capability_registry.py` to avoid confusion with the new `capabilities/` directory (agent-level functional atoms).

## Declarative FSM

Transitions declared per agent, with global defaults:

```yaml
# agents/_defaults.yaml — inherited by all agents
transitions:
  retry: __self__
  escalation: ""
  fact_layer: reviewer
  expression_layer: inspector
```

```yaml
# agents/engineer.yaml — overrides defaults
transitions:
  done: quality_review
  fail: log_only
  # retry and escalation inherited from _defaults
```

```yaml
# agents/reviewer.yaml
transitions:
  done: approved           # terminal
  rework: engineer
  fact_layer: __self__     # reviewer handles fact layer itself
  expression_layer: inspector
```

FSM built at registry load time. Merge strategy: **deep merge with per-key override** (from deep analysis Bug E). Each agent's `transitions` map is merged over `_defaults.yaml` at the individual key level:

```python
# Merge example:
# _defaults: {retry: __self__, escalation: "", fact_layer: →reviewer}
# engineer:  {done: quality_review, fail: log_only}
# Result:    {retry: __self__, escalation: "", fact_layer: →reviewer, done: quality_review, fail: log_only}
```

### Transition Rubric Overrides (from deep analysis P2-11)

Transitions can carry rubric weight overrides for context-specific scoring:

```yaml
# agents/reviewer.yaml
transitions:
  done: approved
  rework: →engineer
  fact_layer: __self__
    rubric_override:
      discipline: 0.6    # anti-sycophancy becomes primary in fact layer
      review: 0.4
  expression_layer: →inspector
```

### Transition Values — Pure Strings (from round 4 simplification)

FSM handles **only post-execution routing** (done/fail/retry/escalation). Runtime flow orchestration (fact-expression split) is the dispatcher's job, not the FSM's.

Transition values are pure strings, three kinds only:
- `@agent` — agent reference (e.g., `@reviewer`)
- `__self__` — self-retry
- `""`, `approved`, `log_only` — terminal values

```yaml
# agents/_defaults.yaml
transitions:
  retry: __self__
  escalation: ""
  # No fact_layer/expression_layer — those are dispatcher's responsibility

# agents/engineer.yaml
transitions:
  done: @reviewer    # NOT "quality_review" — must be resolvable @agent ref
  fail: log_only

# agents/reviewer.yaml
transitions:
  done: approved     # terminal
  rework: @engineer
```

Resolution: `@` prefix → exact agent key lookup. Terminal values → stop. Unknown → error (fail loudly).

Terminal value whitelist (round 6 D4): `KNOWN_TERMINALS = {"", "approved", "log_only"}`. Registry validates at load time — unknown non-`@` values raise an error.

### FSM Execution Semantics (round 6 C1)

**The FSM is declarative data. Governor is the executor.** The FSM never creates tasks or acquires semaphores — it only answers "what's next."

```
Executor completes task
  → callback: Governor.on_task_complete(task_id, result)
  → Governor reads FSM: agent_fsm.get_next(task.agent, "done")
  → Returns "@reviewer"
  → Governor creates new task: db.create_task(spec={agent: "reviewer", parent_id: task_id})
  → Governor dispatches via normal pipeline: semaphore → scrutiny → executor
```

FSM transitions create real tasks (with task_ids, dashboard visibility, retry capability). This matches the current ReviewManager behavior — just declaratively configured instead of hardcoded.

### Fact-Expression Split — Dispatcher Phase 0.5 (from round 4 P0-1/P0-3)

Fact-expression split stays in the dispatcher as pre-execution enrichment, NOT in the FSM. This avoids the need for `executor.resume()` (which doesn't exist — executor is stateless).

```python
async def dispatch_pipeline(spec):
    # Phase 0: Gates + Enrichment
    results = await gather_all_workers(spec)

    # Phase 0.5: Fact-Expression Split (conditional)
    # Sub-tasks created with task_ids for dashboard traceability (round 6 D2)
    # Each sub-task gets semaphore + scrutiny (round 5 P0-A2)
    if needs_fact_expression_split(spec.intent):
        # Phase 0.5a: Fact layer — reviewer with discipline
        fact_spec = composer.compose("reviewer", intent_override="fact_layer")
        fact_task_id = db.create_task(
            spec=fact_spec, parent_id=task_id, phase="fact_layer"
        )
        await semaphore.acquire("reviewer", fact_spec.authority)
        await scrutinize(fact_spec)
        fact_output = await executor.execute_task(fact_task_id)
        semaphore.release("reviewer")

        # Phase 0.5b: Expression layer — inspector with express
        expr_spec = composer.compose("inspector", intent_override="expression_layer")
        expr_task_id = db.create_task(
            spec=expr_spec, parent_id=task_id, phase="expression_layer",
            depends_on=[fact_task_id]
        )
        await semaphore.acquire("inspector", expr_spec.authority)
        await scrutinize(expr_spec, context=fact_output)
        expr_output = await executor.execute_task(expr_task_id)
        semaphore.release("inspector")

        # Return — sub-tasks visible in dashboard with status/output/duration
        return merge(fact_output, expr_output)

    # Split config includes rubric overrides (moved from FSM — round 5 P1-A4)
    # SPLIT_CONFIG = {
    #     "fact_layer":       {"agent": "reviewer", "rubric_override": {"discipline": 0.6, "review": 0.4}},
    #     "expression_layer": {"agent": "inspector"},
    # }

    # Phase 1: Semaphore acquire (after intent resolve — round 4 P1-4)
    effective_auth = min(agent.authority, intent.authority_cap or agent.default_authority)
    await semaphore.acquire(agent_key, effective_auth)

    # Phase 2: Scrutiny
    verdict = await scrutinize(enriched)

    # Phase 3: Main agent execution
    return await executor.execute(composed_spec, spec)
```

The `_SPLIT_INTENTS` set migrates from the current dispatcher as-is.

Reviewer and inspector must define `fact_layer` / `expression_layer` as explicit intents (round 8 E2):

```yaml
# agents/reviewer.yaml — add intent
intents:
  fact_layer:
    description: "Extract verified facts with anti-sycophancy"
    active_capabilities: [review, discipline]
    authority_cap: READ
    profile: BALANCED
  # ... existing intents

# agents/inspector.yaml — add intent
intents:
  expression_layer:
    description: "Rewrite with appropriate tone and expression"
    active_capabilities: [express]
    authority_cap: READ
    profile: LOW_LATENCY
  # ... existing intents
```

## Parallel Scenarios

Named shortcuts (optional) + dynamic capability-based matching:

```yaml
# scenarios.yaml
full_audit:
  agents: [sentinel, reviewer, inspector]
  reducer: merge           # MergeChannel — dict merge of all outputs
system_health:
  agents: [operator, analyst]
  reducer: merge
code_and_review:
  agents: [engineer, reviewer]
  reducer: append          # AppendChannel — sequential output collection
```

Dynamic: `dispatch(capabilities=["audit", "review", "inspect"])` → composer resolves to `[sentinel, reviewer, inspector]` → 3 agents in parallel.

## Dispatcher Pipeline Concurrency

Control plane stays as code (not agents). All studied projects agree: scheduling must be deterministic.

### Optimized: 3-phase async (~7-17s, from ~22s serial)

```python
async def dispatch_pipeline(spec):
    # Phase 0: Gates + Enrichment (all parallel)
    workers = {
        'clarify':    asyncio.create_task(clarification_gate(spec)),
        'synthesis':  asyncio.create_task(synthesis_check(spec)),
        'qdrant':     asyncio.create_task(qdrant_search(spec)),
        'cog_mode':   asyncio.create_task(classify_cognitive_mode(spec)),
        'preflight':  asyncio.create_task(run_preflight(spec)),
        'novelty':    asyncio.create_task(check_novelty(spec)),
        'learnings':  asyncio.create_task(get_learnings(spec)),
        'complexity': asyncio.create_task(classify_complexity(spec)),
    }

    # FutureGate chain: scout auto-starts when cog_mode completes
    # (created BEFORE gate callbacks to avoid race condition — deep analysis Bug C)
    async def conditional_scout():
        mode = await workers['cog_mode']
        if mode.value == "designer":
            return await run_scout(spec)
        return None
    workers['scout'] = asyncio.create_task(conditional_scout())

    # Gate callbacks: cancel all on failure (registered AFTER all tasks created)
    for gate in ['clarify', 'synthesis']:
        workers[gate].add_done_callback(
            lambda t, all_tasks=workers: cancel_all_if_failed(t, all_tasks)
        )

    # Gather with named results (review Bug 7 + deep analysis Bug D fix)
    keys = list(workers.keys())
    values = await asyncio.gather(*workers.values(), return_exceptions=True)
    results = dict(zip(keys, values))

    # Handle cancellation — BaseException for Python 3.9+ CancelledError compat
    for k, v in results.items():
        if isinstance(v, BaseException):
            if k in ('clarify', 'synthesis'):
                return REJECTED
            results[k] = None  # non-gate failures → skip enrichment

    if failed(results.get('clarify')) or failed(results.get('synthesis')):
        return REJECTED

    # Phase 2: Scrutiny (needs all enrichment)
    enriched = merge_results(results)
    return await scrutinize(enriched)
```

## Data Migration (from review P0-1)

### Database

```sql
-- Add new column
ALTER TABLE tasks ADD COLUMN agent TEXT;

-- Migrate existing data (ELSE preserves unknown values for debugging — deep analysis Bug A)
UPDATE tasks SET agent = CASE department
    WHEN 'engineering' THEN 'engineer'
    WHEN 'quality' THEN 'reviewer'
    WHEN 'security' THEN 'sentinel'
    WHEN 'operations' THEN 'operator'
    WHEN 'personnel' THEN 'analyst'
    WHEN 'protocol' THEN 'inspector'
    ELSE department
END;

-- Keep department column for historical queries (read-only)
-- New code writes to agent column only

-- run_logs table (round 8 P0-D2)
ALTER TABLE run_logs ADD COLUMN agent TEXT;
UPDATE run_logs SET agent = CASE department
    WHEN 'engineering' THEN 'engineer'
    WHEN 'quality' THEN 'reviewer'
    WHEN 'security' THEN 'sentinel'
    WHEN 'operations' THEN 'operator'
    WHEN 'personnel' THEN 'analyst'
    WHEN 'protocol' THEN 'inspector'
    ELSE department
END;

-- learnings table (round 8 P0-D2)
ALTER TABLE learnings ADD COLUMN agent TEXT;
UPDATE learnings SET agent = CASE department
    WHEN 'engineering' THEN 'engineer'
    WHEN 'quality' THEN 'reviewer'
    WHEN 'security' THEN 'sentinel'
    WHEN 'operations' THEN 'operator'
    WHEN 'personnel' THEN 'analyst'
    WHEN 'protocol' THEN 'inspector'
    ELSE department
END;

-- All query methods must dual-query during transition:
-- get_learnings_for_dispatch(agent="engineer")
--   → WHERE agent = 'engineer' OR department = 'engineering'
```

### Qdrant Metadata

Batch update in idempotent chunks (deep analysis Bug B):

```python
# Process in batches, Python-side check for missing field (round 7 Bug 1: IsNullCondition unreliable)
for batch in qdrant.scroll(limit=100):
    updates = []
    for point in batch:
        if "agent" not in point.payload:  # field absence, not null
            dept = point.payload.get("department", "")
            updates.append({
                "id": point.id,
                "payload": {"agent": DEPT_TO_AGENT.get(dept, dept)}
            })
    if updates:
        qdrant.set_payload(updates)  # idempotent — re-running is safe
```

### Query Compatibility

All DB queries (novelty, learnings, history) search both `agent` and `department` fields during transition. After confirming all historical data is migrated, drop dual-query.

## Hardcoded Reference Scan (from review P1-3)

Implementation must include a dedicated step to grep and replace ALL hardcoded department references:

```bash
grep -rn "engineering\|quality\|security\|operations\|personnel\|protocol" \
  src/ --include="*.py" | grep -v __pycache__
```

### Manifest Field Migration (from deep analysis P1-1)

| Old field | New location | Notes |
|-----------|-------------|-------|
| `dimensions` (primary/secondary/boost) | `agents/{key}.yaml → dimensions` | Clawvard exam routing |
| `policy.read_only` | Derived from authority | authority=READ → read_only |
| `policy.max_file_changes` | `capabilities/{key}/manifest.yaml → blast_radius.max_files` | Renamed |
| `preflight` checks | `capabilities/{key}/manifest.yaml → preflight` | Moved as-is |
| `policy-denials.jsonl` | `capabilities/{key}/denials.jsonl` | Path change only |
| `run-log.jsonl` | **Copy** to `data/run-logs/{agent_key}.jsonl` (adversarial R1). Originals stay in departments/ until cutover. Eval baseline (Step 0b) depends on these files — path must be stable during validation. |
| `guidelines/` | `capabilities/{key}/guidelines/` | Path change only |

Known locations:
- `_COLLABORATION_PATTERNS` in dispatcher: regex values referencing old department names
- `_DEPT_SPECIFIC_FIELDS` in task_handoff.py: key mapping
- `MUTATE_DEPARTMENTS` / `READ_DEPARTMENTS` in agent_semaphore.py: literal sets
- `_HIGH_BLAST_DEPARTMENTS` in review.py / tiered_review.py: duplicated sets
- `PARALLEL_SCENARIOS` in context/prompts.py: department name values in dict (round 3 P1-3)
- Chinese department names in prompt strings (工部, 刑部, etc.)
- Clawvard exam loading paths in eval/prompt_eval.py (round 3 P1-1)

## Spec Schema Migration (round 6 B5/C2)

Field name changes across all consumers:

| Old | New | Locations |
|-----|-----|-----------|
| `spec["department"]` | `spec["agent"]` | dispatcher, executor, prompt builder, handoff, semaphore, DB, dashboard |
| `task.department` | `task.agent` | DB model, all queries |
| `TaskIntent.department` | `TaskIntent.agent` | intent.py, routing.py, intent_rules.py |
| `DEPARTMENTS` | `AGENTS` | registry consumers (executor, prompts.py, group_orchestration) |

Grep audit command: `grep -rn 'spec\["department"\]\|\.department\b\|DEPARTMENTS\b' src/ --include="*.py"`

**Also migrate**: `spec["departments"]` (plural) → `spec["agents"]`, `spec["multi_department"]` → `spec["multi_agent"]`

### Atomic Switch Constraint (adversarial review 6.1 — CRITICAL)

The chain `intent.py → routing.py → dispatcher.py → governor.py → review_dispatch.py → executor_prompt.py` shares the `spec["department"]` contract. These modules **cannot be migrated incrementally** — changing one while others still expect `department` causes silent routing failures.

**Implementation requirement**: All modules in this chain must switch to `spec["agent"]` in the same commit. The `ARCHITECTURE_VERSION` flag gates the entire chain, not individual files:

```python
if ARCHITECTURE_VERSION == "v2":
    # ALL of these use spec["agent"]
    intent.py, routing.py, dispatcher.py, governor.py, review_dispatch.py, executor_prompt.py
else:
    # ALL of these use spec["department"]
    # (unchanged current code)
```

During v1/v2 coexistence, the flag determines which **entire chain** is active, not which individual file uses the new schema.

## Semaphore Adjustment (from review Bug 4)

New MUTATE agents: engineer, architect, operator (3, up from 2).
Options:
- Raise `mutate_max` from 2 to 3
- Keep at 2 and accept queuing (safer for file conflicts)
- Make architect conditionally MUTATE (only when intent=code_refactor, READ when intent=design_plan — handled by authority_cap)

Recommended: Keep `mutate_max=2`. Architect with `intent=design_plan` gets authority_cap=READ, so it uses a READ slot. Only `intent=code_refactor` uses a MUTATE slot. In practice, rarely all 3 MUTATE agents run simultaneously.

## Terminology Glossary

| Term | Definition | Example |
|------|-----------|---------|
| **Agent** | LLM execution role with identity and prompt | engineer, architect, reviewer |
| **Capability** | Functional atom — tools, authority, prompt fragment, rubric | develop, review, audit |
| **Worker** | Code-level concurrency unit (coroutine/thread) | asyncio.Task in dispatcher pipeline |
| **Job** | Work item in a task queue | enrichment step in dispatcher |
| **Event** | Message on the event bus | EventStream Action/Observation |
| **Superstep** | One round of parallel agent execution + reducer merge | BSP pattern in group orchestration |

## Task Execution Flow

### Single Task

```
User input
  → IntentGateway.parse() → routes to agent + intent (with authority_cap)
  → Dispatcher Pipeline (async, ~7s)
  → CapabilityComposer.compose(agent_key, intent_authority_cap)
  → Executor runs agent session
  → Agent may produce subtasks (declaring needed capabilities)
  → Governor dispatches subtasks as Superstep (capability → agent matching)
  → on_done trigger → next agent via declarative FSM
  → Channel-Reducer merges all results
```

### Subtask Allocation

Architect outputs subtasks declaring needed capabilities:

```yaml
subtasks:
  - action: "Extract module"
    capabilities: [develop, test]     # → engineer
  - action: "Review all changes"
    capabilities: [review, discipline] # → reviewer
    depends_on: [1]
```

Governor matches capabilities to agents, respects dependencies, dispatches via Superstep.

### Multiple Concurrent Tasks

Semaphore tiers built dynamically from AGENTS registry (round 6 B3 — no more hardcoded sets):

```python
def build_semaphore_tiers(agents):
    """Derive tiers from agent default authority at registry load time"""
    tiers = {"MUTATE": set(), "EXECUTE": set(), "READ": set()}
    for key, agent in agents.items():
        tiers[agent.default_authority].add(key)
    return tiers

TIER_LIMITS = {"MUTATE": 2, "EXECUTE": 3, "READ": 4}
GLOBAL_LIMIT = 5
```

At runtime, slot type uses **effective authority** = min(agent.authority, intent.authority_cap):
- Architect/design_plan (authority_cap=READ) → READ slot, not MUTATE
- Architect/code_refactor (authority_cap=MUTATE) → MUTATE slot
- Verifier (EXECUTE) → EXECUTE slot

## Migration

Feature-flagged migration with rollback path (round 7 Meta 1):

```python
# src/governance/registry.py
ARCHITECTURE_VERSION = os.getenv("ORCHESTRATOR_ARCH", "v2")
if ARCHITECTURE_VERSION == "v1":
    _discover_manifests()      # old: departments/
elif ARCHITECTURE_VERSION == "v2":
    _discover_capabilities()   # new: capabilities/ + agents/
```

Both v1 and v2 code paths coexist. `departments/` is NOT deleted until v2 is confirmed stable. Rollback = set `ORCHESTRATOR_ARCH=v1`.

### Data Contract (from R46 career-ops steal)

Before migration, write `DATA_CONTRACT.md` defining what's user data vs system data:

```
User Layer (manual migration only — never auto-updated):
  SOUL/private/             # user identity
  .claude/hooks/            # user hooks
  agents/*.yaml overrides   # user customizations
  capabilities/*/guidelines/ # user-added guidelines

System Layer (safe for automated migration):
  capabilities/*/manifest.yaml
  capabilities/*/prompt.md
  capabilities/*/rubric.yaml
  src/governance/
  SOUL/public/prompts/
```

Migration scripts read this contract. Automated steps only touch System Layer.

### Pre-Migration: Root Detection Fix (round 8 P0-D1)

25+ files detect project root via `(_REPO_ROOT / "departments").is_dir()`. This MUST be fixed BEFORE `departments/` is moved to `.trash/`.

**Fix**: Global replace root detection to use `pyproject.toml`:
```python
# Old
while not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
# New
while not ((_REPO_ROOT / "pyproject.toml").is_file() and (_REPO_ROOT / "src").is_dir()):
```

This is Migration Step -1: runs before everything else, committed separately, tested independently.

### Migration Steps

0a. **Prompt-split isolation test** (round 7 Meta 2): Split current SKILL.md into capability prompt fragments. Run eval on **OLD architecture (v1)** with concatenated prompts. If P50 drops >10% → fix prompts BEFORE touching architecture. This isolates prompt quality from compose logic.
0b. **Eval baseline**: Record P50/P90 scores per department on v1 with original SKILL.md → `data/eval/baseline-pre-refactor/`.
1. Create `capabilities/` (15 dirs) + `agents/` (8 yaml + _defaults.yaml) from existing department data
2. New `capability_composer.py` + `agent_fsm.py`
3. Run DB migration (SQL + Qdrant metadata update)
4. Rewrite all consumers (registry, executor, prompt, dispatcher, intent, routing, semaphore, etc.)
5. Grep + replace all hardcoded department references
6. `departments/` stays on disk (v1 rollback path). DO NOT move until Post-Validation Cutover.
7. Rename `capability_registry.py` → `tool_capability_registry.py`
8. Update all docs (CLAUDE.md, boot.md, SOUL/, docs/architecture/, PATTERNS.md)
9. Run integrity verification chain (from R46 career-ops pattern):
   - `verify-capabilities.py` → every capability has manifest + prompt + rubric
   - `verify-agents.py` → every agent ref resolves; capability weights sum to 1.0
   - `verify-fsm.py` → all @agent refs valid; no orphan terminals
   - `verify-intents.py` → active_capabilities ⊆ agent.capabilities
   - `verify-migration.py` → DB agent column populated; Qdrant agent field coverage
10. Run eval on v2 architecture, compare against Step 0b baseline
11. If P50 drop >10% → tune prompts on v2; if still failing → `ORCHESTRATOR_ARCH=v1` rollback

### Post-Validation Cutover (separate step, NOT part of migration)

Only after v2 is confirmed stable in production (minimum 48h run):
12. Remove v1 code path from registry.py
13. `departments/` → `.trash/departments-legacy-YYYYMMDD/`
14. Remove dual-query compatibility in DB methods

**CRITICAL (Codex review)**: `departments/` MUST remain on disk during the entire v1/v2 coexistence period. 25+ files probe this directory for root detection (Step -1 fixes this), but `shared_knowledge.py` and `periodic.py` still directly access it under v1 mode. Moving it before cutover breaks the advertised rollback path.

### Impact Radius (round 8 finding)

`grep -rn department src/ --include="*.py"` yields **138 references across 40+ files**. The File Changes section below lists the architecturally significant files. The full list (including storage mixins, channel layer, jobs, evolution, health, budget, and root detection patterns) will be enumerated in the implementation plan via a complete grep audit.

Key subsystems NOT in the original File Changes but requiring migration:
- **Storage**: `_schema.py`, `_runs_mixin.py`, `_learnings_mixin.py` (run_logs + learnings tables)
- **Channel**: `formatter.py`, `base.py`, `registry.py`, `chat/tools.py`, `chat/commands.py`
- **Jobs**: `proactive_jobs.py`, `periodic.py`, `sync_vectors.py`, `shared_knowledge.py`
- **Evolution**: `actions.py`, `risk.py`, `loop.py`
- **Budget**: `token_budget.py` (Codex review: `json_extract(t.spec, '$.department')` queries, `UsageRecord.department`, daily caps per department — all must migrate to agent key; new agent traffic must contribute to per-role limits during transition), `multi_budget.py`
- **Root detection**: 25+ files using `(_REPO_ROOT / "departments").is_dir()`

### File Changes

```
New:
  capabilities/              15 subdirectories (manifest.yaml + prompt.md + rubric.yaml each)
  agents/                    8 yaml files + _defaults.yaml
  scenarios.yaml
  src/governance/capability_composer.py
  src/governance/agent_fsm.py

Rewrite:
  src/governance/registry.py
  src/governance/executor.py
  src/governance/executor_prompt.py
  src/governance/dispatcher.py    (+ async concurrency)
  src/gateway/intent.py
  src/gateway/routing.py
  src/governance/group_orchestration.py
  src/governance/safety/agent_semaphore.py
  src/governance/task_handoff.py
  src/governance/review.py
  src/governance/policy/tiered_review.py
  src/governance/eval/prompt_eval.py      (exam_cases.jsonl loading paths)
  .claude/skills/clawvard-practice/SKILL.md  (exam routing logic)
  src/gateway/intent.py                    (Codex review: NOT auto-updating — explicit rewrite required:
                                            JSON output field "department"→"agent", VALID_DEPARTMENTS→VALID_AGENTS,
                                            default fallback "engineering"→"engineer",
                                            TaskIntent.department→.agent, to_governor_spec() field name,
                                            LLM prompt text "选择一个部门"→"选择一个 agent")
  src/gateway/intent_rules.py              (rule-based routing: return values + field names)
  src/governance/governor.py               (spec["department"] → spec["agent"], FSM executor)
  src/governance/task_handoff.py           (_DEPT_SPECIFIC_FIELDS → _AGENT_SPECIFIC_FIELDS, add architect)
  src/governance/group_orchestration.py    (_COLLABORATION_PATTERNS full rewrite, not just key rename)

Rename:
  src/governance/capability_registry.py → tool_capability_registry.py

Remove (→ .trash/):
  departments/
  src/governance/department_fsm.py
  src/governance/eval/department_rubric.py
```

## Design Provenance

Key patterns drawn from steal-study (45 rounds, 825+ patterns):

| Pattern | Source | Application |
|---------|--------|-------------|
| WHO/WHAT separation | yoyo-evolve, OpenClaw, R42 immortal-skill | capabilities/ vs agents/ split |
| Channel-Reducer | LangGraph R43 | Superstep result merging |
| Connection-Based Agent | MachinaOS R40 | Declarative FSM from agent.yaml |
| Middleware Pipeline | DeerFlow R29 | Prompt fragments as ordered layers |
| FutureGate chain | ChatDev R13 | Conditional scout in dispatcher |
| Protocol-not-ABC | PraisonAI R39 | CapabilityEntry/AgentEntry as data |
| Progressive Skill Loading | DeerFlow R29 | Capability prompts loaded on demand |
| Control plane = code | ALL projects | Dispatcher stays deterministic |
| Role-Dimension Matrix | R42 immortal-skill | Capability weights in agent declaration |
| Intent-level authority | PUA R35 flavor routing | authority_cap per intent |
| Data Contract | career-ops R46 | User/System layer separation for safe migration |
| File-based IPC | career-ops R46 | Sub-task intermediate results to disk for crash resilience |
| Integrity verification chain | career-ops R46 | 5-step post-migration data verification |

## Review Issue Resolution

### Round 1 (review.md)

| Issue | Severity | Resolution |
|-------|----------|------------|
| DB migration missing | P0 | Added SQL migration + Qdrant batch update + dual-query transition |
| FSM 3-field expressiveness | P0 | Expanded to `transitions` map + `_defaults.yaml` inheritance |
| Anti-sycophancy lost on reviewer | P0 | Split guard → secure + discipline; reviewer gets discipline |
| sentinel haiku for security | P1 | audit capability model → sonnet; sentinel resolves to sonnet |
| Authority max inflation | P1 | Added intent-level `authority_cap` in L3 override |
| Hardcoded department refs | P1 | Added grep scan + replace step in migration |
| compress orphan | P2 | Assigned to operator |
| verify duplicate | P2 | Removed from analyst, only on verifier |
| ad-hoc no identity | P2 | Single-agent → use identity; multi-agent → sequential/parallel plan |
| Rubric 1/N crude | P2 | Agent declares per-capability weights |
| asyncio gather dict | P2 | Fixed: zip(keys, values) + return_exceptions=True |
| CapabilityRegistry naming | P3 | Renamed to tool_capability_registry.py |

### Round 2 (deep-analysis.md)

| Issue | Severity | Resolution |
|-------|----------|------------|
| Divisions system lost (20 sub-specializations) | P0 | Added `specializations/` subdirs in capabilities, full migration mapping |
| Manifest fields lost (preflight, dimensions, etc.) | P1 | Field-by-field migration table, all accounted for |
| `test` READ authority contradiction | P1 | Introduced EXECUTE level: READ < EXECUTE < MUTATE < APPROVE |
| Intent Profile dissolution | P1 | Profile preserved in L3 override, can lower model/turns/timeout |
| Authority granularity (3 levels) | P1 | 4 levels now: READ, EXECUTE, MUTATE, APPROVE |
| authority_cap doesn't filter prompts | P2 | Superseded by active_capabilities (round 3) |
| DB CASE missing ELSE | P2 | Added `ELSE department` fallback |
| Qdrant migration non-idempotent | P2 | Idempotent batch processing with skip-if-migrated filter |
| cancel_all_if_failed race condition | P2 | Create all tasks (including scout) BEFORE registering callbacks |
| CancelledError Python 3.9+ compat | P2 | Changed to `isinstance(v, BaseException)` |
| FSM defaults merge strategy undefined | P2 | Explicit: deep merge with per-key override |
| Fact layer rubric weights fixed | P2 | Transition-level `rubric_override` support |
| Ad-hoc SuperstepPlan semantics | P2 | Implicit dependency → sequential; no dependency → parallel |
| resolve_trigger namespace conflict | P3 | `@` prefix for agent refs, bare names for triggers |

### Round 3 (round3-audit.md)

| Issue | Severity | Resolution |
|-------|----------|------------|
| FSM fact_layer → terminal state kills main task | P0 | `return_to: __caller__` in transition; Governor resume() after sub-execution |
| Clawvard exam paths / dimensions not migrated | P1 | Added eval code + SKILL.md to File Changes; dimensions in agent.yaml |
| EXECUTE tool set undefined | P1 | Defined CEILING_TOOL_CAPS: READ={Read,Glob,Grep}, EXECUTE=+Bash, MUTATE=+Write+Edit |
| PARALLEL_SCENARIOS not in hardcoded scan | P1 | Added to Known locations list |
| Prompt concatenation quality unverified | P1 | Added Step 0: eval baseline before migration, P50 >10% drop → pause |
| Intent-level capability filtering missing | P1 | `active_capabilities` field on intents; 3-tier fallback (explicit > authority > all) |
| authority_cap default undefined | P2 | Defaults to APPROVE (no filtering) |
| rubric_override YAML syntax invalid | P2 | Transition value = `string \| {target, return_to?, rubric_override?}` union type |
| DB migration validation query | P2 | Added post-migration SELECT DISTINCT check |
| `→` Unicode prefix risk | P3 | Changed to ASCII `@` prefix |

### Round 4 (round4-deep-review.md)

| Issue | Severity | Resolution |
|-------|----------|------------|
| `executor.resume()` doesn't exist; return_to unimplementable | P0 | **Architectural change**: removed return_to entirely; fact-expression split moved to dispatcher Phase 0.5 |
| `quality_review` trigger can't resolve in new FSM | P0 | All agent refs use `@agent` format; FSM values are pure strings only |
| Fact-expression split has no entry in new dispatcher pipeline | P0 | Added Phase 0.5 in dispatcher; `_SPLIT_INTENTS` logic preserved |
| CEILING_TOOL_CAPS missing Agent/Task/Web tools | P1 | Added ALWAYS_AVAILABLE, NETWORK_TOOLS, AGENT_TOOLS sets + resolve_tools() |
| Intent LLM prompt still selects "departments" | P1 | Noted: prompt is dynamically generated from registry, auto-updates |
| operator missing collect intent (sonnet cost) | P1 | Added `data_collect` intent with LOW_LATENCY profile |
| Semaphore effective authority timing undefined | P1 | Semaphore acquire placed after intent resolve in pipeline |
| Prompt concat order undefined | P2 | Weight-descending: high-weight prompts last (recency bias) |
| Tier 2 active_capabilities fallback counter-intuitive | P2 | Removed Tier 2; only explicit (Tier 1) or all (Tier 2) |
| scenarios.yaml missing reducer strategy | P2 | Added `reducer` field (merge/append) |
| Profile "lower" semantics ambiguous | P2 | Clarified: profile is ceiling (only lowers, never raises) |
| _defaults.yaml fact_layer harmful default | P2 | Removed — fact_layer no longer in FSM |
| Ad-hoc dependency detection unreliable | P2 | Simplified: multi-agent ad-hoc always serialized |

### Round 5 (round5-review.md)

| Issue | Severity | Resolution |
|-------|----------|------------|
| Phase 0.5 bypasses semaphore + scrutiny | P0 | Each sub-execution individually acquires semaphore + passes scrutiny |
| active_capabilities only filters prompts, not compose chain | P0 | active_capabilities now filters ALL merge inputs (model, tools, authority, rubric) |
| rubric_override status post-Round 4 contradiction | P1 | Moved to dispatcher SPLIT_CONFIG; FSM stays pure strings |
| Profile ceiling can force-downgrade opus→haiku | P1 | Added `model_floor` to capability manifest; floor wins over ceiling |
| Agent identity vs authority_cap cognitive dissonance | P1 | Authority context line injected after identity in prompt assembly |
| Qdrant migration filter invalid syntax | P1 | Fixed to use `IsNullCondition` (valid Qdrant API) |
| DB NULL department handling | P2 | SQL CASE already handles via ELSE; NULL→NULL is acceptable |
| resolve_tools missing LSP/NotebookEdit | P2 | Full tool audit deferred to implementation |
| Prompt middle-child attention problem | P2 | Add `## [Capability: X]` section headers as delimiters |
| Subtask capability→agent matching undefined | P2 | Greedy set-cover + no-coverage → serial split; details in implementation |
| Default fallback agent undefined | P2 | `engineer` as default fallback (matching current `engineering` behavior) |
| Hot reload atomicity | P2 | Build new dicts then atomic swap |
| denials.jsonl split across capabilities | P2 | Agent-level aggregation query helper |
| Ad-hoc vs scenarios.yaml unclear | P2 | Unify: ad-hoc matching a known scenario auto-uses its reducer |
| architect/design_plan filters out refactor knowledge | — | Fixed: active_capabilities: [plan, refactor] with authority_cap=READ |

### Round 6 (round6-review.md — consumer-side integration audit)

| Issue | Severity | Resolution |
|-------|----------|------------|
| Fact-Expression Split loses task traceability | HIGH | Phase 0.5 creates sub-tasks with task_ids via db.create_task() |
| FSM transition executor undefined | HIGH | Governor is the executor; FSM is declarative data only |
| _COLLABORATION_PATTERNS Chinese names won't match | HIGH | Full rewrite: patterns + values updated to agent names + functional verbs |
| _DEPT_SPECIFIC_FIELDS missing architect | HIGH | New _AGENT_SPECIFIC_FIELDS with architect entry (refactor_plan, dependency_graph) |
| Semaphore EXECUTE tier undefined | HIGH | 3-tier dynamic build from AGENTS; MUTATE(2), EXECUTE(3), READ(4) |
| active_capabilities is implicit model selector | HIGH | Warning log when compose model differs from agent default |
| FSM terminal value detection fragile | MED | KNOWN_TERMINALS whitelist validated at registry load time |
| spec["department"] field name migration | MED | Spec Schema Migration section added with grep audit command |
| intent_rules.py hardcoded department values | MED | Added to Rewrite file list (was missing) |
| resolve_tools missing LSP/PowerShell | MED | Tool audit required before implementation (added to migration step) |
| Hot reload atomicity gap | MED | Single RegistryState wrapper object with atomic reference swap |
| Default fallback agent | MED | `engineer` as default (matching current `engineering` behavior) |
| Ad-hoc all-READ forced serial | MED | Refined: all-READ → parallel; mixed authority → serial |

### Round 7 (round7-review.md — end-to-end consistency audit)

| Issue | Severity | Resolution |
|-------|----------|------------|
| active_capabilities is hidden agent factory | P1 | **Reverted**: active_caps filters prompt+rubric only; model/authority by explicit intent declaration |
| Override Stack missing resolution table | P1 | Added formal Dimension Resolution Table (every dimension × every layer) |
| Qdrant IsNullCondition unreliable on missing fields | P1 | Changed to Python-side `"agent" not in point.payload` check |
| Big Bang migration no rollback | P1 | Added `ARCHITECTURE_VERSION` env flag; v1/v2 coexist; departments/ NOT deleted until v2 stable |
| No isolated prompt-split validation | P1 | Added Step 0a: test concatenated prompts on OLD architecture first; isolate variables |
| Phase 0.5 dispatcher overreach | P2 | Tagged tech debt; extract Governor.run_sub_chain() during implementation |
| model_floor vs profile ceiling power inversion | P2 | Floor wins + WARN log (capability safety > cost preference) |
| Cancel storm passive/active confusion | P2 | Use task.cancelled() to distinguish |
| Specialization routing static | P2 | Acknowledged trade-off; dynamic routing deferred to v2.1 |
| Ad-hoc chain context handoff | P2 | Permissive handoff policy (pass all fields) for dynamic chains |
| YAML None terminal parsing | P3 | Schema validates None before string ops; friendly error message |

### Round 8 (round8-deep-audit.md — codebase grep audit, 138 references)

| Issue | Severity | Resolution |
|-------|----------|------------|
| 25+ files use `departments/` for root detection → crash on removal | P0 | Pre-migration Step -1: global replace to `pyproject.toml` detection |
| run_logs + learnings tables missing from DB migration | P0 | Added ALTER TABLE + UPDATE for both tables; dual-query during transition |
| dispatcher imports `department_fsm` → crash after rename | P0 | Covered by implementation plan's full grep audit |
| Channel layer (5 files) not in File Changes | P1 | Added to Impact Radius section; full list in implementation plan |
| Token Budget per-department billing not migrated | P1 | Added to Impact Radius section |
| learnings query silent failure (new agent name ↔ old dept name) | P1 | Dual-query: `WHERE agent = X OR department = Y` |
| `department="proactive"` special value | P1 | Route to operator or define as system agent; resolve in implementation |
| `vet_all_departments` import breaks | P1 | Covered by full grep audit |
| Semaphore threading.Lock vs async | P1 | Concurrency model decision deferred to implementation plan |
| fact_layer/expression_layer intents not defined on agents | P2 | Added explicit intent definitions on reviewer + inspector |
| Telegram bot shows raw agent key | P2 | AGENT_NAMES mapping in implementation |
| Evolution subsystem 9 dept refs | P2 | In Impact Radius; full cleanup in implementation |

### Codex Adversarial Review (codex-review.md — 3 blockers)

| Issue | Severity | Resolution |
|-------|----------|------------|
| Rollback removes `departments/` before v2 validated — self-contradictory | CRITICAL | Separated post-validation cutover from migration steps; `departments/` stays on disk during v1/v2 coexistence |
| Gateway "auto-updates from registry" assumption is false | HIGH | Marked intent.py as explicit full rewrite (JSON field, validation, defaults, prompt text, TaskIntent field) |
| Budget/accounting stays on department key — spend controls fail open | HIGH | Budget migration added to Impact Radius with explicit work items |

### Adversarial Review (adversarial-review.md — Codex-assisted, 2 CRITICAL + 5 HIGH)

| Issue | Severity | Resolution |
|-------|----------|------------|
| authority_cap defaults to APPROVE — permission vulnerability | CRITICAL | **Fixed**: default changed to agent's compose-level authority (not APPROVE). verify-intents.py must check: MUTATE+ agents require explicit authority_cap on every intent |
| run-log.jsonl migration path missing — breaks eval baseline | CRITICAL | **Fixed**: copy to `data/run-logs/{agent_key}.jsonl`; originals stay until cutover |
| 15 capability granularity uneven | HIGH | Accepted as v1 trade-off; verify-capabilities.py warns on prompt.md > 2000 tokens |
| Override Stack L2 has no consumer | HIGH | L2 marked RESERVED in v1; Dimension Resolution Table simplified to L0/L1/L3 |
| dimension_map.yaml migration missing | HIGH | Implementation plan action: migrate to `agents/shared/exam/dimension_map.yaml` |
| blueprint.yaml cleanup not mentioned | HIGH | Implementation plan action: grep audit for blueprint consumers |
| policy-denials.jsonl wrong level (capability vs agent) | HIGH | Corrected: agent-level, not capability-level → `data/denials/{agent_key}.jsonl` |
| spec["departments"] (plural) not migrated | HIGH | Implementation plan action: `spec["departments"]` → `spec["agents"]` + multi_agent flag |
| compose() debug trace needed | HIGH | Implementation plan: ComposedSpec._trace field for resolution chain |
| Phase 0.5 failure semantics | MEDIUM | Fact layer failure → REJECTED (no Phase 1-3) |
| Scenario matching algorithm | MEDIUM | V1: exact agent set equality only; no subset/superset inference |
| model_floor vs intent.model priority | MEDIUM | `final = max(floor, intent.model if explicit else min(compose, ceiling))` — floor always wins |
| resolve_tools missing platform tools | MEDIUM | Implementation Step 2 MUST complete tool audit from current capability_registry.py |
| department="proactive" | MEDIUM | Map to agent="operator" + intent="system_maintenance" in DB migration |

### Adversarial Deep Review (adversarial-review-deep.md — 4 CRITICAL / 15 HIGH / 3 MEDIUM)

| Issue | Severity | Resolution |
|-------|----------|------------|
| Migration Step 6 still moves departments/ during v1/v2 coexistence | CRITICAL | **Fixed**: Step 6 changed to "stays on disk"; removal only in Post-Validation Cutover |
| ad-hoc mode bypasses authority_cap (no intent = no cap) | CRITICAL | **Fixed**: ad-hoc uses min of agent's intent authority_caps; MUTATE requires scrutiny HIGH approval |
| Gateway→FSM chain cannot be incrementally migrated | CRITICAL | **Fixed**: ARCHITECTURE_VERSION gates entire chain atomically, not individual files |
| L2 Override Stack contradicts itself (active in table, RESERVED in conclusion) | CRITICAL | **Fixed**: L2 removed from Dimension Resolution Table; marked RESERVED in v1 |
| architect/design_plan active_caps contradicts round 5 fix | HIGH | **Fixed**: unified to `[plan, refactor]` with authority_cap=READ |
| intent.model described as "hard override" but floor constrains it | HIGH | **Fixed**: corrected to "floor-constrained explicit request" with examples |
| hot reload affects in-flight tasks — no version pinning | HIGH | **Fixed**: registry_version in ComposedSpec + task row; in-flight tasks pinned |
| active_capabilities=[] edge case | HIGH | Implementation: verify-intents.py must check non-empty |
| intent tools larger than prompt suggests (active_caps filters prompt not tools) | HIGH | **Added**: intent can declare `restrict_tools` list in Dimension Table |
| semaphore tier changes during task execution | HIGH | Implementation: semaphore key = task_id + resolved authority; no mid-task tier change |
| Qdrant partial migration state undefined | MEDIUM | Implementation: dual-field filter adapter required during transition |
| 48h validation insufficient for low-frequency paths | MEDIUM | Implementation: cutover requires full scenario replay + periodic task checklist |
| eval baseline not comparable if exam corpus changes simultaneously | HIGH | Implementation: freeze exam corpus before migration; compare on identical test set |
| Migration Steps 3/4/9 circular dependency | HIGH | Implementation: restructure as schema→dual-write→consumer-rewrite→backfill→verify |

### Adversarial-3 (adversarial-review.md — complexity overload analysis, 3 P0 + systemic critique)

| Issue | Severity | Resolution |
|-------|----------|------------|
| resolve_adhoc() permission algorithm is wrong (min of all intents, not matching) | P0 | **Deferred**: ad-hoc mode moved to LOW PRIORITY v2; does not exist in v1 |
| compose(agent_key) without intent produces over-privileged spec | P0 | **Fixed**: no-intent compose auto-binds to agent's default intent |
| Hot reload version pinning is fake (no snapshot retention) | P0 | **Simplified**: compose results materialized to DB at task creation; no live registry dependency |
| v1 complexity overload (14 cross-cutting concepts) | Systemic | **Scope reduction**: 8 concepts deferred to low-priority v2; v1 ships with 10 concepts |
| 5 entry points for consumers | Systemic | **Fixed**: single entry `compose(agent, intent)`; ad-hoc/scenario are v2 |
| active_capabilities semantic awkwardness | P1 | Accepted as v1 trade-off; restrict_tools deferred to v2 |
| Phase 0.5 dispatcher overreach | P1 | Tagged tech debt; Governor.run_sub_chain() in v2 |
| Migration is still big-bang despite feature flag | P1 | Acknowledged; atomic chain switch is by design; dual-write in implementation plan |
| Consumer API cognitive load | P1 | Mitigated by single entry point + compose trace |
