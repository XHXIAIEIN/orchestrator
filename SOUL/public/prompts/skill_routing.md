# Skill Routing Decision Tree

Route by task intent, not by scanning the full skill list.
methodology_router.md handles *how to think*; this file handles *which tool to reach for*.

## Decision Tree

```
Task arrives
├─ Bug / Error / Unexpected behavior?
│  └─ systematic-debugging → then verification-gate
│
├─ CI red / PR checks failing?
│  └─ babysit-pr
│
├─ System health check / "something's wrong"?
│  └─ /doctor
│
├─ Clawvard exam / practice / competency test?
│  └─ /clawvard-practice
│
├─ Steal / study external repo?
│  └─ /steal (requires steal/* branch)
│
├─ Plan a multi-step task?
│  └─ Use plan_template.md format (check Phase Gates)
│
├─ About to claim "done"?
│  └─ verification-gate (mandatory before any completion claim)
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

## Routing Signals

Don't just match keywords — match intent:

| Signal | Routes to | NOT to |
|--------|-----------|--------|
| "it's broken", stack trace, error log | systematic-debugging | babysit-pr (unless it's CI) |
| "CI failed", "checks red", PR number | babysit-pr | systematic-debugging |
| "check the system", "is everything ok" | /doctor | systematic-debugging |
| "study this repo", GitHub URL + learning intent | /steal | general browsing |
| "is it done?", "verify", before commit | verification-gate | — |
| "practice", "exam", "Clawvard" | /clawvard-practice | manual Q&A |

## Anti-Patterns

- **Don't chain skills unnecessarily.** Most tasks need 0-1 skills, not a pipeline.
- **Don't invoke a skill for trivial tasks.** "Add a print statement" doesn't need systematic-debugging.
- **Don't skip verification-gate before completion claims.** This is the one non-negotiable routing rule.
