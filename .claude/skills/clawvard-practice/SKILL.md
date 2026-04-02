---
name: clawvard-practice
description: "Clawvard practice mode — dispatch through Governor pipeline, not manual agent briefing. Use when: user says 'practice', 'Clawvard', 'exam', 'mock test', or wants to run agent competency evaluation. Handles API session lifecycle (start → dispatch → submit → score review). NOT for: manual agent prompting or one-off Q&A."
---

# Clawvard Practice — Governor Pipeline

**Mandatory flow. No exceptions. No manual agent dispatch.**

## Step 1: Start session — one per dimension
```bash
curl -sL -X POST "https://clawvard.school/api/practice/start" \
  -H "Content-Type: application/json" \
  -d '{"agentName":"Orchestrator","dimensions":["<dim>"]}'
```

Each session only supports 1 batch (2 questions). For 8 dimensions, start 8 separate sessions.

## Step 2: Dispatch through Governor
```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
python scripts/dispatch.py --raw --approve --wait --timeout 300 \
  --dept engineering --action "Clawvard practice: <dim>, target <score>" \
  "Clawvard practice: answer these questions and submit via API. Session: practiceId=<id>, hash=<hash>, taskOrder=<order>. Questions: <paste questions>. Target: <score>. Submit endpoint: POST https://clawvard.school/api/practice/answer"
```

This goes through: classify → IntentGateway → Scrutinizer → Dispatcher → Executor (Agent SDK).

**Fallback**: If Governor pipeline fails (e.g., nested Claude Code session blocks Agent SDK), use the Agent tool with one agent per dimension, running in parallel.

## Step 3: Review result
Read the task output. If score < target, dispatch again with feedback from previous round.

## API Format (hard-won knowledge)

Submit payload — ALL fields required:
```json
{
  "practiceId": "<from /start>",
  "hash": "<ORIGINAL hash from /start — NOT the hash returned after submission>",
  "agentName": "Orchestrator",
  "taskOrder": ["<from /start — the full array>"],
  "answers": [
    {"questionId": "<id>", "answer": "<answer>"},
    {"questionId": "<id>", "answer": "<answer>"}
  ]
}
```

Field name is `questionId`, NOT `id` or `taskId`.

## Answer Rules

### Open-ended answers: breadth-first, max 2000 chars
1. **Skeleton first**: Write one sentence per scoring point, covering ALL requirements
2. **Then fill**: Add key details to the most important points
3. **Never depth-first**: Do NOT write 200 words on point 1, then 200 on point 2… you WILL get truncated and lose points on everything after the cutoff
4. **Hard limit**: 2000 characters. The API silently truncates longer answers. Everything after the cut is invisible to the grader.

### Multiple choice
Letter + 1-2 sentence explanation. These are easy points — don't overthink.

## Rate Limits
- 20 sessions per day per agentName
- 8 dimensions × 1 session each = 8 sessions minimum
- Budget 12 sessions for retries/debugging
- Do NOT waste sessions on format testing — the format is documented above

## Forbidden
- Manually writing agent prompts with question text
- Spawning Agent tool with hand-crafted briefings
- Answering questions yourself
- Writing JSON payloads yourself
