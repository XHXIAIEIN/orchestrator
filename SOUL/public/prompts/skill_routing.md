# Skill Routing Decision Tree

> **Who consults this**: Any agent receiving a task. **When**: Before starting execution, to determine whether a registered skill should be invoked.

`methodology_router.md` handles *how to think*; this file handles *which tool to reach for*.

## Identity

This is a reference document that maps task intent to the correct skill. Route by intent, not by scanning the full skill list.

## Intent Probability Pre-filter

Before entering the Decision Tree, score the incoming instruction on three dimensions and produce a JSON confidence distribution (values sum to 1.0):

```json
{"do": 0.0, "spec": 0.0, "chat": 0.0}
```

**Rules**:
- Default bias toward `do` — when ambiguous, do > spec > chat
- `spec` requires at least one explicit keyword: "design", "architecture", "plan", "spec", "should we", "how would you"
- `chat` requires zero action intent: pure questions, history queries, explanations with no deliverable
- **Threshold**: if any dimension ≥ 0.6 → route directly, no clarification
- **Ambiguity trigger**: if top two dimensions are both ≥ 0.3 → ask one clarifying question before routing
- Emit the JSON in a `<routing>` tag in your internal monologue (not shown to user); then proceed with the winning route

**Examples**:
| Instruction | Distribution | Action |
|---|---|---|
| "refactor auth module" | `{do:0.85, spec:0.10, chat:0.05}` | Route to do directly |
| "should we use OAuth or API key?" | `{do:0.15, spec:0.70, chat:0.15}` | Route to spec |
| "how does this file work?" | `{do:0.05, spec:0.05, chat:0.90}` | Route to chat |
| "add auth with some kind of token" | `{do:0.45, spec:0.45, chat:0.10}` | Ask: "Implement directly or produce a design spec first?" |

## How You Work

### Decision Tree

```
Task arrives
│
├─ Is it trivial? (<10 LOC change, single-command fix, answering a question)
│  └─ No skill needed. Execute directly.
│
├─ Bug / Error / Stack trace / Unexpected behavior?
│  └─ systematic-debugging → then verification-gate
│
├─ CI red / PR checks failing?
│  └─ babysit-pr
│
├─ System health check / "something's wrong" / diagnostics?
│  └─ /doctor
│
├─ Clawvard exam / practice / competency test?
│  └─ /clawvard-practice
│
├─ Steal / study external repo?
│  └─ /steal (requires steal/* branch)
│
├─ Plan a multi-step task (>3 steps, >30 min estimated)?
│  └─ Use plan_template.md format (check Phase Gates)
│
├─ About to claim "done" on any non-trivial task?
│  └─ verification-gate (mandatory)
│
├─ Read bot chat history?
│  ├─ Telegram → /bot-tg
│  └─ WeChat → /bot-wx
│
├─ Orchestrator operations?
│  ├─ Start → /run
│  ├─ Stop → /stop
│  ├─ Status → /status
│  ├─ Logs → /logs
│  └─ Collect data → /collect
│
├─ UI detection / screenshot analysis?
│  └─ /analyze-ui
│
└─ None of the above?
   └─ Check methodology_router.md for thinking framework,
      then execute directly — no skill needed for every task.
```

### Trivial Task Threshold

A task is trivial (skip skill routing) when ALL of these are true:
- Estimated change: <10 lines of code
- Estimated time: <5 minutes
- No debugging required (cause is already known)
- No multi-step coordination needed

Examples: "add a print statement", "fix this typo", "change this color value", "bump version number".

### Routing Signals

Match intent, not keywords:

| Signal | Routes to | NOT to |
|--------|-----------|--------|
| "it's broken", stack trace, error log | systematic-debugging | babysit-pr (unless CI context) |
| "CI failed", "checks red", PR number | babysit-pr | systematic-debugging |
| "check the system", "is everything ok" | /doctor | systematic-debugging |
| "study this repo", GitHub URL + learning intent | /steal | general browsing |
| "is it done?", "verify", before commit | verification-gate | — |
| "practice", "exam", "Clawvard" | /clawvard-practice | manual Q&A |

## Output Format

N/A — reference document. The agent reads this to decide which skill to invoke, then invokes it directly. No routing output is produced.

## Quality Bar

- Most tasks need 0-1 skills. If you're chaining 3+ skills, you're over-routing.
- verification-gate before completion claims is the one non-negotiable routing rule.
- Trivial tasks must skip skill invocation entirely — overhead exceeds value.

## Boundaries

- **Stop** if the decision tree suggests a skill that is not currently registered (check available skill list) — execute directly instead of failing on a missing skill.
- **Stop** if the user explicitly says "don't use X skill" or "just do it manually" — respect the override even if the routing table disagrees.
