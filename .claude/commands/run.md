---
description: 启动 orchestrator（Docker 模式或本地模式）
---

启动 orchestrator 系统。检测当前环境，选择合适的启动方式。

## 步骤

**1. 检测环境**

运行以下命令判断 Docker 是否可用：
```bash
docker info 2>/dev/null && echo "docker_ok" || echo "no_docker"
```

**2a. Docker 模式（推荐）**

如果 Docker 可用，执行：
```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
docker compose up --build -d
```

启动后显示：
- Dashboard：http://localhost:23714
- 查看日志：`docker logs -f orchestrator`
- 停止：`docker compose down`

**2b. 本地模式（无 Docker）**

如果 Docker 不可用，分两个终端启动：

终端 1 — Python scheduler：
```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
pip install -r requirements.txt
python -m src.scheduler
```

终端 2 — Node dashboard：
```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator/dashboard
npm install
node server.js
```

Dashboard：http://localhost:23714

**3. 采集数据**

系统启动后，立即触发一次采集以补齐停机期间的数据：

Docker 模式：
```bash
docker exec orchestrator sh -c "cd /orchestrator && python3 -c \"
import sys; sys.path.insert(0, '.')
from src.scheduler import run_collectors
run_collectors()
\""
```

本地模式：
```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
python3 -c "import sys; sys.path.insert(0, '.'); from src.scheduler import run_collectors; run_collectors()"
```

**4. 验证**

启动后检查健康状态：
```bash
curl -s http://localhost:23714/api/logs?limit=5
```

返回日志条目则表示系统正常运行。
