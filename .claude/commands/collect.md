---
description: Manually trigger a data collection run
---

Trigger an incremental data collection to catch up on the latest data.

## Steps

Detect the runtime mode and execute collection:

**Docker mode:**
```bash
docker exec orchestrator sh -c "cd /orchestrator && python3 -c \"
import sys; sys.path.insert(0, '.')
from src.scheduler import run_collectors
run_collectors()
\""
```

**Local mode (running as a direct process):**
```bash
cd $(git rev-parse --show-toplevel)
python3 -c "import sys; sys.path.insert(0, '.'); from src.scheduler import run_collectors; run_collectors()"
```

Example output: `Collection done: {'claude': 12, 'browser': 34, 'git': 0, 'steam': 0, 'youtube_music': 0}`

Shows the number of new entries collected from each data source.
