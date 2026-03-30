---
name: clawvard-practice
description: Clawvard practice mode — dispatch through Governor pipeline, not manual agent briefing
---

# Clawvard Practice — Governor Pipeline

**Mandatory flow. No exceptions. No manual agent dispatch.**

## Step 1: Start session (curl — you do this, it's trivial)
```bash
curl -sL -X POST "https://clawvard.school/api/practice/start" \
  -H "Content-Type: application/json" \
  -d '{"agentName":"Orchestrator","dimensions":["<dim>"]}'
```

## Step 2: Dispatch through Governor
```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
python scripts/dispatch.py --raw --approve --wait --timeout 300 \
  --dept engineering --action "Clawvard practice: <dim>, target <score>" \
  "Clawvard practice: answer these questions and submit via API. Session: practiceId=<id>, hash=<hash>, taskOrder=<order>. Questions: <paste questions>. Target: <score>. Submit endpoint: POST https://clawvard.school/api/practice/answer"
```

This goes through: classify → IntentGateway → Scrutinizer → Dispatcher → Executor (Agent SDK).

## Step 3: Review result
Read the task output. If score < target, dispatch again with feedback from previous round.

## Forbidden
- Manually writing agent prompts with question text
- Spawning Agent tool with hand-crafted briefings
- Answering questions yourself
- Writing JSON payloads yourself
