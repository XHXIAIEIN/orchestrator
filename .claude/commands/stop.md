---
description: 停止 orchestrator
---

停止正在运行的 orchestrator 系统。

## 步骤

**Docker 模式：**
```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
docker compose down
```

**仅停止容器但保留网络/卷（快速重启场景）：**
```bash
docker stop orchestrator
```

停止后确认：
```bash
docker ps | grep orchestrator
```

无输出则表示已完全停止。
