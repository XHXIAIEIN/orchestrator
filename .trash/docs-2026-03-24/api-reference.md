# Orchestrator API Reference

Base URL: `http://localhost:23714`

供其他项目的 Claude 实例或脚本调用。所有接口返回 JSON。

---

## 快速上手

```bash
# 检查 orchestrator 是否在跑
curl -s http://localhost:23714/api/health

# 一览全局状态（推荐：最轻量的入口）
curl -s http://localhost:23714/api/brief

# 查所有未解决的注意力债务
curl -s http://localhost:23714/api/debts?status=open
```

---

## 核心接口

### GET /api/health

健康检查。

**响应**:
```json
{ "status": "ok", "uptime": 21600 }
```

---

### GET /api/brief

跨项目摘要 — 一个请求拿到全局状态。

**响应**:
```json
{
  "status": "ok",
  "debts": {
    "open": 3,
    "high_priority": [
      { "id": 1, "project": "construct3-rag", "summary": "...", "severity": "high" }
    ]
  },
  "tasks": { "pending": 2, "running": 0 },
  "last_collector_run": "2026-03-19T10:00:00Z",
  "last_analysis": "2026-03-19T09:30:00Z"
}
```

---

## 注意力债务

### GET /api/debts

查询注意力债务列表。

**查询参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 筛选状态：`open` / `tasked` / `resolved` |
| `project` | string | 模糊匹配项目名 |
| `severity` | string | 筛选严重度：`high` / `medium` / `low` |

**示例**:
```bash
# 所有未解决的高优先级债务
curl -s 'http://localhost:23714/api/debts?status=open&severity=high'

# 某个项目的债务
curl -s 'http://localhost:23714/api/debts?project=construct3-rag'
```

**响应**: 数组，按 severity (high→low) + 时间倒序排列。

---

## 任务管理

### GET /api/tasks

查询任务列表。

**查询参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 筛选状态：`pending` / `awaiting_approval` / `running` / `done` / `failed` |
| `department` | string | 筛选部门：`engineering` / `quality` / `operations` / `protocol` / `security` / `personnel` |

**示例**:
```bash
# 等待审批的任务
curl -s 'http://localhost:23714/api/tasks?status=awaiting_approval'

# 工部的任务
curl -s 'http://localhost:23714/api/tasks?department=engineering'
```

### GET /api/tasks/:id

查询单个任务详情。

### POST /api/tasks

创建新任务。

**请求体**:
```json
{
  "action": "修复 collector 路径配置",
  "reason": "git collector 连续 3 天 0 数据",
  "priority": "high",
  "spec": {
    "department": "engineering",
    "project": "orchestrator"
  }
}
```

### POST /api/tasks/:id/approve

批准并执行任务（触发 Governor 派单）。

---

## 数据查询

### GET /api/events

查询事件记录。

**查询参数**: `days` (默认 7) — 查最近 N 天。

### GET /api/events/heatmap

事件热力图数据。

**查询参数**: `days` (默认 60)。

### GET /api/stats

按来源统计事件数量。

### GET /api/stats/categories

按分类统计时间投入。

**查询参数**: `days` (默认 7)。

### GET /api/summaries

最近 7 天的每日摘要。

### GET /api/insights

最新的 insight 分析结果。

---

## Pipeline 状态

### GET /api/pipeline/status

完整的管道状态：采集器、分析、治理、部门、调度器。

### GET /api/pipeline/logs

系统日志。

**查询参数**: `limit` (默认 20，最大 200)。

### GET /api/pipeline/tasks

任务列表（含部门、认知模式、blast radius）。

**查询参数**: `limit` (默认 30，最大 100)。

### GET /api/pipeline/departments

六部运行统计（执行次数、成功率、最近记录）。

### GET /api/schedule-status

调度器状态（下次采集/分析时间）。

---

## Profile 分析

### GET /api/profile-analysis

最新的 profile 分析。

### GET /api/profile-analysis/history

最近 30 条 profile 分析历史。

### POST /api/profile-analysis/refresh

触发新的 profile 分析（异步，返回 202）。

---

## TTS 语音

### POST /api/tts

生成语音。

**请求体**: `{ "text": "要说的话", "reference_id": "可选的声音 ID" }`

### GET /api/tts/health

TTS 服务健康检查。

---

## Blueprint

### GET /api/blueprints

所有部门的 Blueprint 配置（声明式策略、预检规则、生命周期）。

**响应**:
```json
{
  "engineering": {
    "version": "1",
    "name_zh": "工部",
    "model": "claude-sonnet-4-6",
    "policy": {
      "allowed_tools": ["Bash", "Read", "Edit", "Write", "Glob", "Grep"],
      "denied_paths": [".env", "*.key", "data/events.db"],
      "can_commit": true,
      "read_only": false
    },
    "preflight": [
      { "check": "cwd_exists", "required": true },
      { "check": "skill_exists", "required": true },
      { "check": "disk_space", "target": "100", "required": false }
    ],
    "on_done": "quality_review",
    "on_fail": "log_only"
  },
  "protocol": null
}
```

### GET /api/departments/:name/blueprint

单个部门的 Blueprint 配置。返回 YAML 解析后的 JSON。

---

## Policy Advisor

### GET /api/policy-advisor/summary

所有部门的策略否决事件统计。

**响应**:
```json
{
  "engineering": { "denials": 4, "has_suggestions": true },
  "protocol": { "denials": 2, "has_suggestions": true },
  "quality": { "denials": 0, "has_suggestions": false }
}
```

### GET /api/departments/:name/policy-denials

单个部门的策略否决事件列表。

**查询参数**: `limit` (默认 50，最大 200)。

**响应**: 数组，倒序排列。每条包含 `ts`, `type`（tool_blocked/timeout/max_turns/write_in_readonly），`detail`, `suggested_fix`。

### GET /api/departments/:name/policy-suggestions

Policy Advisor 为该部门生成的 Blueprint 调整建议（Markdown）。

---

## 实时通道

### GET /api/logs

SSE 流 — 实时推送系统日志。

### WebSocket /

WebSocket 连接，推送事件：
- `task_update` — 任务状态变更
- `profile_analysis_done` — 分析完成
- `soul_voice` — 语音生成完成（含 base64 音频）
- `tts_status` — TTS 生成进度

---

## 在其他项目中使用

在其他项目的 `CLAUDE.md` 中加入：

```markdown
## Orchestrator 集成

查全局状态：`curl -s http://localhost:23714/api/brief`
查未解决债务：`curl -s http://localhost:23714/api/debts?status=open`
完整 API 文档：见 orchestrator 项目 docs/api-reference.md
```
