# Orchestrator API (for Claude instances)

Base: `http://localhost:23714`

Check availability: `curl -s http://localhost:23714/api/health`

## Common

```bash
# Global brief: open debt count + high-priority list + task status
curl -s http://localhost:23714/api/brief

# Open attention debts
curl -s 'http://localhost:23714/api/debts?status=open'

# High-severity debts only
curl -s 'http://localhost:23714/api/debts?status=open&severity=high'

# Debts for a specific project
curl -s 'http://localhost:23714/api/debts?project=PROJECT_NAME'

# Tasks awaiting approval
curl -s 'http://localhost:23714/api/tasks?status=awaiting_approval'

# Submit a task
curl -s -X POST http://localhost:23714/api/tasks -H 'Content-Type: application/json' -d '{"action":"description","reason":"why","priority":"high","spec":{"department":"engineering"}}'
```

## Filters

- `/api/debts` — `status`: open/tasked/resolved, `severity`: high/medium/low, `project`: fuzzy match
- `/api/tasks` — `status`: pending/awaiting_approval/running/done/failed, `department`: engineering/quality/operations/protocol/security/personnel

## Departments (Six Ministries)

```bash
# List all departments
curl -s http://localhost:23714/api/departments

# Full detail for one department (skill + guidelines + runs + learned-skills)
curl -s http://localhost:23714/api/departments/engineering

# Department SKILL.md (returns raw markdown)
curl -s http://localhost:23714/api/departments/engineering/skill

# Recent execution log (default 20, max 100)
curl -s 'http://localhost:23714/api/departments/quality/runs?limit=10'

# Department guidelines
curl -s http://localhost:23714/api/departments/engineering/guidelines
```

Available departments: `engineering`, `quality`, `operations`, `protocol`, `security`, `personnel`

## Blueprints (Department Policies)

```bash
# All department blueprints (policies, preflight rules, lifecycle config)
curl -s http://localhost:23714/api/blueprints

# Single department blueprint
curl -s http://localhost:23714/api/departments/engineering/blueprint
```

Blueprint defines the machine-readable policy for each department: allowed tools, writable paths, preflight checks, timeout, max turns, and post-execution hooks. SKILL.md is the LLM prompt; blueprint.yaml is the Governor config.

## Policy Advisor

```bash
# Denial event summary across all departments
curl -s http://localhost:23714/api/policy-advisor/summary

# Denial events for a department
curl -s 'http://localhost:23714/api/departments/engineering/policy-denials?limit=20'

# Generated blueprint adjustment suggestions (markdown)
curl -s http://localhost:23714/api/departments/engineering/policy-suggestions
```

Policy Advisor observes task execution, records when agents hit policy limits (blocked tools, timeouts, max turns, write-in-readonly), and generates data-driven blueprint.yaml adjustment suggestions.

## Parallel Scenarios

```bash
# List available scenarios
curl -s http://localhost:23714/api/scenarios

# Trigger a scenario (dispatches multiple departments in parallel)
curl -s -X POST http://localhost:23714/api/scenarios/full_audit/run -H 'Content-Type: application/json' -d '{"project":"orchestrator"}'
```

| Scenario | Departments | Use case |
|---|---|---|
| `full_audit` | security + quality + protocol | Full system audit |
| `code_and_review` | engineering + quality | Fix + review on different projects |
| `system_health` | operations + personnel | Health check + performance report |
| `deep_scan` | protocol + security + personnel | Debt scan + security + metrics |
| `full_pipeline` | protocol + security + quality + personnel | All read-only departments at once |

## Agent Observability

```bash
# All running agents with real-time status (what they're doing right now)
curl -s http://localhost:23714/api/agents/live

# Full execution trace for a specific task (all turns, tools, decisions, errors)
curl -s http://localhost:23714/api/agents/42/trace

# Event history for a task
curl -s http://localhost:23714/api/agent-events/42

# SSE real-time stream (all agent events across all tasks)
curl -s http://localhost:23714/api/agent-events-stream
```

`/api/agents/live` response:
```json
{
  "agents": [{
    "task_id": 42,
    "department": "engineering",
    "project": "orchestrator",
    "action": "fix scheduler import",
    "cognitive_mode": "react",
    "elapsed_s": 45,
    "current_activity": {
      "turn": 3,
      "tools": ["Edit"],
      "thinking_preview": "found the issue on line 29..."
    },
    "recent_events": [...]
  }],
  "running_count": 2,
  "pending_count": 1,
  "max_concurrent": 3
}
```

`/api/agents/:id/trace` — full execution replay: turns, tools used, decisions made, errors hit, cost.

## Experiences

```bash
# Recent experiences
curl -s http://localhost:23714/api/experiences

# By type (bonding/humor/conflict/trust/discovery/limitation/milestone/lesson)
curl -s 'http://localhost:23714/api/experiences?type=milestone&limit=5'
```

## Other endpoints

- `GET /api/events?days=7` — event records
- `GET /api/insights` — latest analysis
- `GET /api/summaries` — last 7 daily summaries
- `GET /api/pipeline/status` — full pipeline status
- `GET /api/schedule-status` — scheduler status
