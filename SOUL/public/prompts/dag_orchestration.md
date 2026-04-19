<!-- TL;DR: Build dependency graphs; parallelize independent nodes, gate on outputs. -->
# DAG Orchestration Pattern

Design pattern for composing multi-step AI tasks as directed acyclic graphs (DAGs). Enables parallel execution of independent steps, conditional branching, and approval gates.

**Source**: R47 Archon steal (DAG executor, workflow engine). Adapted for Claude Code skill orchestration.

## When to Use

- Task has 3+ steps with some that can run in parallel
- Steps have explicit dependencies ("do B only after A completes")
- Need conditional routing ("run X only if Y produced result Z")
- Need human gates between phases

## Core Concepts

### Nodes (Steps)

Each node is one unit of work. Six types:

| Type | What It Does | Example |
|------|-------------|---------|
| **prompt** | AI reasoning with structured output | "Analyze this codebase and identify patterns" |
| **command** | Run a skill or slash command | `/prime governance` |
| **bash** | Shell script (no AI) | `npm test`, `git diff` |
| **loop** | Iterate until signal | Implement features one by one until all pass |
| **approval** | Pause for human decision | "Review the implementation before merging" |
| **cancel** | Abort the workflow | "Requirements invalid, stopping" |

### Edges (Dependencies)

```yaml
depends_on: [node-a, node-b]   # wait for both A and B
```

### Trigger Rules

When a node has multiple dependencies, how to decide if it runs:

| Rule | Behavior |
|------|----------|
| `all_success` | Run only if ALL dependencies succeeded |
| `one_success` | Run as soon as ONE dependency succeeds |
| `all_done` | Run after all dependencies finish (regardless of status) |

### Conditional Execution

```yaml
when: "$classify.output.type == 'bug'"
```

Conditions reference prior node outputs. Fail-closed: unparseable condition = skip.

## DAG Definition Format

For skill authors defining multi-step workflows:

```yaml
# In a skill's workflow definition or plan file
dag:
  - id: explore
    type: prompt
    prompt: "Explore the codebase for X..."

  - id: plan
    type: prompt
    depends_on: [explore]
    prompt: "Based on exploration, create plan..."

  - id: review-gate
    type: approval
    depends_on: [plan]
    message: "Review the plan?"
    on_reject:
      prompt: "User rejected: $REJECTION_REASON. Revise."
      max_attempts: 3

  - id: implement-a
    type: command
    depends_on: [review-gate]
    command: "implement module A"

  - id: implement-b
    type: command
    depends_on: [review-gate]
    command: "implement module B"
    # A and B run in PARALLEL (same dependency, no dependency on each other)

  - id: integrate
    type: bash
    depends_on: [implement-a, implement-b]
    command: "npm test && npm run build"

  - id: final-review
    type: approval
    depends_on: [integrate]
    message: "All tests pass. Merge?"
```

## Execution Strategy

### Layer-Based Scheduling (Kahn's Algorithm)

```
Layer 0: [explore]              — run sequentially
Layer 1: [plan]                 — depends on L0, run sequentially
Layer 2: [review-gate]          — depends on L1, pause for human
Layer 3: [implement-a, implement-b]  — PARALLEL (both depend on L2)
Layer 4: [integrate]            — depends on L3, run after both complete
Layer 5: [final-review]         — depends on L4, pause for human
```

**Rule**: Nodes in the same layer with no mutual dependencies run in parallel.

### Applying in Claude Code

Since Claude Code runs in a single conversation, "parallel" means dispatching sub-agents:

```markdown
## Parallel Execution
For nodes in the same layer, dispatch as sub-agents:
- Agent A: implement module A
- Agent B: implement module B
Wait for both to complete before proceeding to integration.
```

For sequential layers, execute in the main conversation.

## Patterns for Common Workflows

### Feature Development DAG

```
explore → plan → [approve] → implement → test → [approve] → merge
```

### Code Review DAG (with conditional routing)

```
                 ┌→ code-review ──────────┐
classify ────────┤→ error-handling ────────┤→ synthesize → fix
(haiku)          ├→ test-coverage ─────────┤
                 └→ docs-impact ──────────┘
                    (only if API changed)
```

Use `when:` conditions on each review node. Synthesize with `trigger_rule: one_success`.

### Adversarial Development DAG

```
negotiate → generate → evaluate → [pass?] → complete
                ↑          │
                └── retry ──┘ (if score < 7)
```

This is a loop, not a pure DAG. Implement with the loop node type.

## Integration with Existing Patterns

- **Disk State Loop** (`disk_state_loop.md`): Use for loop nodes within a DAG
- **Approval Gate** (`approval.py`): Use for approval nodes
- **Sub-agent dispatch**: Use for parallel layer execution
- **Verification Gate** (`verification-gate`): Use as the final node

## Anti-Patterns

| Don't | Why | Do Instead |
|-------|-----|-----------|
| Everything sequential | Wastes time when steps are independent | Identify parallel opportunities |
| No approval gates | Risky for large changes | Gate before destructive actions |
| Circular dependencies | Not a DAG anymore | Restructure as loop node |
| Too many layers | Overhead exceeds benefit | 3-5 layers typical for features |
| Skip trigger rules | First failure kills everything | Use `one_success` for resilient synthesis |
