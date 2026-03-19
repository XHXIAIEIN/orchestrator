---
description: View recent orchestrator logs
---

View system logs from either Docker container logs or API logs.

## Steps

**1. Container runtime logs (last 50 lines):**
```bash
docker logs --tail 50 orchestrator
```

**2. API structured logs (last 20 entries):**
```bash
curl -s "http://localhost:23714/api/logs?limit=20" | python3 -m json.tool
```

**Live tail (continuous output):**
```bash
docker logs -f orchestrator
```

Press Ctrl+C to stop tailing.
