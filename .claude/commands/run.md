---
description: Start orchestrator (Docker mode or local mode)
---

Start the orchestrator system. Detects the current environment and chooses the appropriate startup method.

## Steps

**1. Detect environment**

Run the following command to check if Docker is available:
```bash
docker info 2>/dev/null && echo "docker_ok" || echo "no_docker"
```

**2a. Docker mode (recommended)**

If Docker is available, run:
```bash
cd $(git rev-parse --show-toplevel)
docker compose up --build -d
```

After startup, display:
- Dashboard: http://localhost:23714
- View logs: `docker logs -f orchestrator`
- Stop: `docker compose down`

**2b. Local mode (no Docker)**

If Docker is unavailable, start in two terminals:

Terminal 1 -- Python scheduler:
```bash
cd $(git rev-parse --show-toplevel)
pip install -r requirements.txt
python -m src.scheduler
```

Terminal 2 -- Node dashboard:
```bash
cd $(git rev-parse --show-toplevel)/dashboard
npm install
node server.js
```

Dashboard: http://localhost:23714

**3. Collect data**

After the system starts, immediately trigger a collection run to catch up on data missed during downtime:

Docker mode:
```bash
docker exec orchestrator sh -c "cd /orchestrator && python3 -c \"
import sys; sys.path.insert(0, '.')
from src.scheduler import run_collectors
run_collectors()
\""
```

Local mode:
```bash
cd $(git rev-parse --show-toplevel)
python3 -c "import sys; sys.path.insert(0, '.'); from src.scheduler import run_collectors; run_collectors()"
```

**4. Verify**

After startup, check health status:
```bash
curl -s http://localhost:23714/api/logs?limit=5
```

If log entries are returned, the system is running normally.
