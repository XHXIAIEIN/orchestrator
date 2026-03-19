---
description: Stop orchestrator
---

Stop the running orchestrator system.

## Steps

**Docker mode:**
```bash
cd $(git rev-parse --show-toplevel)
docker compose down
```

**Stop container only, preserving networks/volumes (for quick restart):**
```bash
docker stop orchestrator
```

Confirm after stopping:
```bash
docker ps | grep orchestrator
```

No output means it has been fully stopped.
