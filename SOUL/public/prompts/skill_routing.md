<!-- TL;DR: Route tasks to skills by type (bug/build/review/ship); not by keyword match. -->
# Skill Routing Decision Tree

> **Who consults this**: Any agent receiving a task. **When**: Before starting execution, to determine whether a registered skill should be invoked.

`methodology_router.md` handles *how to think*; this file handles *which tool to reach for*.

## Identity

This is a reference document that maps task intent to the correct skill. Route by intent, not by scanning the full skill list.

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
├─ New repo / unfamiliar project → `/awaken`
│  └─ Goal: force local convention discovery before any code changes
│
├─ Steal / study external repo?
│  └─ /steal (requires steal/* branch)
│
├─ Plan a multi-step task (>3 steps, >30 min estimated)?
│  └─ Use plan_template.md format (check Phase Gates)
│
├─ Multi-file structural change OR cross-module refactor (>2 files)?
│  └─ Enter Plan Mode (Shift+Tab) before any write — produces the plan,
│     then exit Plan Mode to execute. Pairs with plan_template.md.
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
| change spans >2 files, structural refactor | Plan Mode (Shift+Tab) first | jumping straight to Edit |

## Output Format

N/A — reference document. The agent reads this to decide which skill to invoke, then invokes it directly. No routing output is produced.

## Quality Bar

- Most tasks need 0-1 skills. If you're chaining 3+ skills, you're over-routing.
- verification-gate before completion claims is the one non-negotiable routing rule.
- Trivial tasks must skip skill invocation entirely — overhead exceeds value.

## Boundaries

- **Stop** if the decision tree suggests a skill that is not currently registered (check available skill list) — execute directly instead of failing on a missing skill.
- **Stop** if the user explicitly says "don't use X skill" or "just do it manually" — respect the override even if the routing table disagrees.
