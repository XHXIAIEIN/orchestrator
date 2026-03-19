---
description: View orchestrator runtime status and recent collection summary
---

View current system status, including container state, recent collection results, and scheduling plan.

## Steps

**1. Container status:**
```bash
docker ps --filter name=orchestrator --format "table {{.Status}}\t{{.Ports}}"
```

**2. Recent logs (last 10 lines):**
```bash
docker logs --tail 10 orchestrator
```

**3. API health check + recent collection logs:**
```bash
curl -s "http://localhost:23714/api/logs?limit=10" | python3 -m json.tool
```

Normal output should contain `Collection done` log entries showing collection counts for each data source.

If the container is not running, prompt the user to run `/run`.
