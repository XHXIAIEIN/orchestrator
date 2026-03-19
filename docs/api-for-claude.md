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

## Other endpoints

- `GET /api/events?days=7` — event records
- `GET /api/insights` — latest analysis
- `GET /api/summaries` — last 7 daily summaries
- `GET /api/pipeline/status` — full pipeline status
- `GET /api/schedule-status` — scheduler status
