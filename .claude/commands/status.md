---
description: View orchestrator runtime status and recent collection summary
---

View system status using the HealthCheck engine (not just raw docker ps).

## Steps

**1. Container status (quick):**
```bash
docker ps --filter name=orchestrator --format "table {{.Status}}\t{{.Ports}}"
```

**2. Full health report via HealthCheck engine:**
```bash
docker exec orchestrator python3 -c "
import sys, json; sys.path.insert(0,'.')
from src.core.health import HealthCheck
hc = HealthCheck()
report = hc.run()
# Compact output
for component in ['db', 'collectors', 'governor', 'channels', 'event_loop']:
    data = report.get(component, {})
    print(f'{component}: {json.dumps(data, default=str, ensure_ascii=False)}')
print(f'issues: {json.dumps(report.get(\"issues\", []), default=str, ensure_ascii=False)}')
print(f'healthy: {report.get(\"healthy\", False)}')
"
```

**3. System snapshot (same data injected into agent dispatches):**
```bash
docker exec orchestrator python3 -c "
import sys; sys.path.insert(0,'.')
from src.governance.context.providers import build_system_snapshot
print(build_system_snapshot())
"
```

## Interpretation

- **healthy: true** → all clear
- **issues 非空** → 按 level high/medium/low 排序，high 需要立即处理
- **Collector hours_ago > 48** → 采集器可能挂了，检查 cron 或 API key
- **Governor stuck > 0** → 有任务卡死，可能需要手动终止
- **DB size > 100MB** → 需要归档旧数据

If the container is not running, prompt the user to run `/run`.
For deep diagnostics with repair suggestions, use `/doctor`.
