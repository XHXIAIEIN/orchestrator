---
description: 查看 orchestrator 运行状态和最近采集摘要
---

查看系统当前状态，包括容器状态、最近采集结果和调度计划。

## 步骤

**1. 容器状态：**
```bash
docker ps --filter name=orchestrator --format "table {{.Status}}\t{{.Ports}}"
```

**2. 最近日志（最后 10 行）：**
```bash
docker logs --tail 10 orchestrator
```

**3. API 健康检查 + 最近采集日志：**
```bash
curl -s "http://localhost:23714/api/logs?limit=10" | python3 -m json.tool
```

正常输出应包含 `Collection done` 日志条目，显示各数据源采集数量。

如果容器未运行，提示用户执行 `/run`。
