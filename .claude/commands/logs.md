---
description: 查看 orchestrator 最近日志
---

查看系统日志，支持 Docker 容器日志和 API 日志两种来源。

## 步骤

**1. 容器运行日志（最近 50 行）：**
```bash
docker logs --tail 50 orchestrator
```

**2. API 结构化日志（最近 20 条）：**
```bash
curl -s "http://localhost:23714/api/logs?limit=20" | python3 -m json.tool
```

**实时跟踪（持续输出）：**
```bash
docker logs -f orchestrator
```

按 Ctrl+C 停止跟踪。
