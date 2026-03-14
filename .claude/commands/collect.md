---
description: 手动触发一次数据采集
---

触发一次增量数据采集，补齐最新数据。

## 步骤

检测运行模式并执行采集：

**Docker 模式：**
```bash
docker exec orchestrator sh -c "cd /orchestrator && python3 -c \"
import sys; sys.path.insert(0, '.')
from src.scheduler import run_collectors
run_collectors()
\""
```

**本地模式（进程直接运行时）：**
```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
python3 -c "import sys; sys.path.insert(0, '.'); from src.scheduler import run_collectors; run_collectors()"
```

输出示例：`Collection done: {'claude': 12, 'browser': 34, 'git': 0, 'steam': 0, 'youtube_music': 0}`

显示各数据源采集到的新条目数量。
