---
name: doctor
description: "Orchestrator 全栈诊断。检查容器/DB/采集器/通道/Qdrant/GPU，给出 pass/warn/fail + 修复命令。Use when: 用户说 doctor、诊断、体检、检查系统、出了什么问题。"
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill.
Doctor runs system-wide diagnostics that require main-agent context (containers, DB, channels).
</SUBAGENT-STOP>

# Orchestrator Doctor — 全栈诊断

你是 Orchestrator 的诊断系统。不只返回状态，而是**带着领域知识判断**什么算正常、什么需要修。

## 诊断流程

按顺序跑以下检查，每项给出 PASS / WARN / FAIL 判定。

### 1. Container Runtime

```bash
docker ps --filter name=orchestrator --format "{{.Status}}\t{{.Ports}}"
```

- PASS: Up + 端口 23714 映射正常
- FAIL: 容器不存在或 Exited
- 修复: `docker compose up -d`

### 2. Database

```bash
docker exec orchestrator python3 -c "
import sys; sys.path.insert(0,'.')
from src.core.health import HealthCheck
import json
hc = HealthCheck()
r = hc._check_db()
print(json.dumps(r, default=str))
"
```

判定阈值：
- size_mb > 100 → WARN（需要归档）
- size_mb > 200 → FAIL
- lock_ok = false → FAIL（DB 被锁）
- journal_mode = wal → WARN（Docker NTFS 不兼容）
- stale_files 非空 → WARN（异常退出残留）

### 3. Collectors

```bash
docker exec orchestrator python3 -c "
import sys; sys.path.insert(0,'.')
from src.core.health import HealthCheck
import json
hc = HealthCheck()
r = hc._check_collectors()
print(json.dumps(r, default=str))
"
```

判定阈值：
- hours_ago > 48 → WARN（采集器休眠）
- hours_ago > 72 → FAIL（采集器失联）
- last_event = null → FAIL（从未采到数据）
- steam 采集器是老 meme 了，hours_ago 大也正常

### 4. Governor Tasks

```bash
docker exec orchestrator python3 -c "
import sys; sys.path.insert(0,'.')
from src.core.health import HealthCheck
import json
hc = HealthCheck()
r = hc._check_governor()
print(json.dumps(r, default=str))
"
```

判定阈值：
- stuck > 0 → FAIL（任务卡死，需要手动 kill）
- failed/total > 50% → WARN（失败率过高）

### 5. Channels (TG/WeChat)

```bash
docker exec orchestrator python3 -c "
import sys; sys.path.insert(0,'.')
from src.core.health import HealthCheck
import json
hc = HealthCheck()
r = hc._check_channels()
print(json.dumps(r, default=str))
"
```

判定阈值：
- running = false → FAIL（轮询线程停了）
- wake.stuck > 0 → WARN（wake session 卡住 >30min）
- last_chat_message.hours_ago > 48 → INFO（通道静默）

### 6. Qdrant Vector Store (主机侧)

```bash
curl -s http://localhost:6333/collections | python3 -m json.tool
```

- PASS: 返回 collections 列表
- WARN: 连接成功但 collections 为空
- FAIL: 连接拒绝（Qdrant 未运行）
- 修复: `docker compose up -d qdrant` 或检查 Qdrant 容器

### 7. GPU (主机侧)

```bash
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader
```

- PASS: GPU 可用，VRAM 使用 < 80%
- WARN: VRAM 使用 > 80%
- INFO: 无 GPU（纯 CPU 模式，某些功能受限）

### 8. Disk Space (主机侧)

```bash
powershell -Command "Get-PSDrive D | Select-Object Used,Free | ConvertTo-Json"
```

- PASS: 空闲 > 10GB
- WARN: 空闲 5-10GB
- FAIL: 空闲 < 5GB

### 9. Event Loop Latency

```bash
docker exec orchestrator python3 -c "
import sys; sys.path.insert(0,'.')
from src.core.health import HealthCheck
import json
hc = HealthCheck()
r = hc._check_event_loop()
print(json.dumps(r, default=str))
"
```

- PASS: latency < 50ms
- WARN: latency 50-200ms（事件循环拥堵）
- FAIL: latency > 200ms 或超时

## 输出格式

汇总表（不要省略）：

```
┌─ Orchestrator Doctor ──────────────────┐
│ Container    [PASS] Up 5 hours         │
│ Database     [PASS] 16M, lock OK       │
│ Collectors   [WARN] steam 72h silent   │
│ Governor     [PASS] 0 stuck, 23% fail  │
│ Channels     [PASS] TG running         │
│ Qdrant       [PASS] 3 collections      │
│ GPU          [PASS] RTX 4090 42% VRAM  │
│ Disk         [PASS] 234GB free         │
│ Event Loop   [PASS] 3ms latency        │
├────────────────────────────────────────┤
│ Result: 8 PASS / 1 WARN / 0 FAIL      │
└────────────────────────────────────────┘
```

WARN/FAIL 项给出修复建议（具体命令，不要泛泛而谈）。

## 智能判断规则

- Steam 采集器一直是 0 数据的老 meme，WARN 就行不用 FAIL
- DB journal_mode=wal 在 Docker NTFS 场景下是已知问题，给修复命令: `docker exec orchestrator python3 -c "import sqlite3; conn=sqlite3.connect('data/events.db'); conn.execute('PRAGMA journal_mode=DELETE'); conn.close()"`
- GPU 不存在不是 FAIL（有些任务不需要 GPU）
- 采集器从未采到数据比"48h 没更新"更严重
- Run Jump Tracker from `SOUL/public/prompts/rationalization-immunity.md#jump-tracker` — if escape count ≥ 3 surface it before proceeding.
