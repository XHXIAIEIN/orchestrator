# Dashboard Enhancement v2 — 设计文档

**日期：** 2026-03-13
**状态：** 已确认

---

## 目标

在保持当前极简黑色风格的前提下，为 dashboard 添加 7 个新信息模块，并引入 `ProfileAnalyst` 深度画像分析能力。

---

## 架构概览

采用**扁平化扩展**方案（方案 A）：新模块作为新卡片加入现有 `index.html` 的 grid 布局，不引入路由、不拆分页面，零额外依赖。

---

## Python 层

### 新文件：`src/profile_analyst.py`

`ProfileAnalyst` 类，与现有 `InsightEngine` 结构一致：

- 读取 `user_profile`、近 30 天 `events`、近 7 天 `daily_summaries`
- 调用 Claude 生成深度画像报告，字段：

```
overview       — 整体印象（200字以内）
strengths[]    — 观察到的优点/特质
blind_spots[]  — 可能的盲区或值得注意的模式
suggestions[]  — 具体可行的建议（带优先级 high/medium/low）
commentary     — AI 自由评论：想法、观察、感受
daily_note     — 昨日专属点评（仅 type='daily' 时填充）
generated_at   — 生成时间 ISO 8601
type           — 'periodic' | 'daily'
```

- 结果写入 `profile_analysis` 表

### 新文件：`src/profile_analyst_cli.py`

命令行包装层（与 `governor_cli.py` 模式一致），供 Node 层 spawn 调用：

```
python3 /orchestrator/src/profile_analyst_cli.py periodic
python3 /orchestrator/src/profile_analyst_cli.py daily
```

输出：`{"status": "ok", "generated_at": "..."}` 或 `{"error": "..."}`

### 修改：`src/storage/events_db.py`

新增表：

```sql
CREATE TABLE IF NOT EXISTS profile_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_json TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'periodic',
    generated_at TEXT NOT NULL
);
```

新增辅助查询方法：
- `get_events_by_day(days=60)` — 聚合查询：`SELECT DATE(occurred_at) as day, COUNT(*) as count FROM events WHERE occurred_at >= ? GROUP BY day`，返回 `[{day, count}]`，不受 LIMIT 限制
- `get_events_by_category(days=N)` — 聚合查询：`SELECT category, SUM(duration_minutes) as total_min FROM events WHERE occurred_at >= ? GROUP BY category`，N 支持 1/7/30
- `save_profile_analysis(data, type)` — INSERT 后立即执行裁剪：`DELETE FROM profile_analysis WHERE id NOT IN (SELECT id FROM profile_analysis ORDER BY id DESC LIMIT 50)`，裁剪逻辑在此方法内部完成
- `get_profile_analysis(type=None)` — `ORDER BY id DESC LIMIT 1`，可按 type 过滤
- `get_daily_summaries(days=7)` — 直接返回原始数据库行，`summary` 字段保持为原始 JSON 字符串，不在 Python 层解析（供 Node sql.js 直读路径使用）

### 修改：`src/scheduler.py`

新增两个调度 job：
1. **每 6 小时（interval）**：`ProfileAnalyst().run(type='periodic')`，在现有 analysis job 之后运行
2. **每日 06:00（cron，Asia/Shanghai 时区）**：`ProfileAnalyst().run(type='daily')`，数据窗口锁定前一天（`DATE(occurred_at) = yesterday`）

APScheduler cron trigger 示例：
```python
scheduler.add_job(_profile_daily, "cron", hour=6, timezone="Asia/Shanghai", id="profile_daily")
```

---

## Node 层（`dashboard/server.js`）

新增 API 端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/profile-analysis` | 用 sql.js 直读 DB，返回最新深度画像报告（JSON.parse data_json） |
| POST | `/api/profile-analysis/refresh` | 立即返回 `{status:'accepted'}`（202），后台 spawn `profile_analyst_cli.py periodic`；spawn 完成后 broadcast `{type:'profile_analysis_done'}`；spawn 超时设为 60 秒，超时则 broadcast `{type:'profile_analysis_error', error:'timeout'}` |
| GET | `/api/events/heatmap?days=60` | 用 sql.js 直读，聚合查询返回 `[{day, count}]` |
| GET | `/api/summaries` | 用 sql.js 直读，对每行执行 `JSON.parse(row.summary)`，返回结构化数组 |
| GET | `/api/stats/categories?days=N` | 用 sql.js 直读，按 category 聚合统计，与 `/api/stats` 路径精确匹配不冲突 |

`/api/summaries` 返回结构示例：
```json
[{"date": "2026-03-13", "summary": "...", "top_topics": [...], "behavioral_insights": "...", "time_breakdown": {...}}]
```

前端刷新按钮行为：点击 → POST refresh（立即返回）→ 进入 loading 状态 → 监听 WebSocket `profile_analysis_done` 或 `profile_analysis_error` → 退出 loading 并重渲染或显示错误。页面关闭/重连后，若 WebSocket 错过通知，下次 `load()` 轮询会自动拉取最新数据。

---

## 前端层（`dashboard/public/index.html`）

7 个新卡片，全部加入现有 `.grid`，沿用当前 CSS 变量和黑色主题。

### 模块 1：用户画像卡片（基础）

- 数据源：`/api/summary`（已有，含 `profile` 字段）
- `user_profile` 的 `profile_json` 为动态 key-value 结构，前端采用动态遍历渲染，不做固定字段假设
- 展示：遍历所有顶层字段，数组类型渲染为 tag 列表，字符串渲染为文本行

### 模块 2：深度画像分析（增强版）⭐

- 数据源：`/api/profile-analysis`
- 展示字段：overview、strengths、blind_spots、suggestions（带优先级色标）、commentary、daily_note
- 右上角「刷新」按钮 → POST `/api/profile-analysis/refresh` → loading 动画 → WebSocket 收到 `{type:'profile_analysis_done'}` 后重渲染
- 显示生成时间 + 类型标签（定期/晨报）

### 模块 3：7 日趋势摘要

- 数据源：`/api/summaries`（已由 Node 层解析，前端直接消费结构化数据）
- 展示：每天一行，格式：`日期 · top_topics tags · 主要活动类型`
- 按时间倒序排列

### 模块 4：活动热力图

- 数据源：`/api/events/heatmap?days=60`，返回 `[{day, count}]` 聚合数据
- 纯 JS 渲染，近 60 天，按周排列（7 列）
- 格子颜色深浅对应当天事件数（4 级：0/1-3/4-9/10+）
- 点击格子在卡片内展开当日 top 5 事件标题（从已加载的 `/api/events` 数据中过滤）

### 模块 5：分类时间分布（增强版）

- 数据源：`/api/stats/categories?days=N`
- 在现有「采集统计」卡片基础上扩展
- 新增三个切换按钮：今日 / 7天 / 30天，点击重新请求
- 增加按 `category` 细分行，带颜色进度条

### 模块 6：任务执行统计

- 数据源：前端从 `/api/tasks`（LIMIT 50）已有数据计算，无需新 API
- **设计取舍**：统计基于最近 50 条，为近似值，适用于趋势参考，不追求全量精确
- 在任务列表上方展示：总数 / 完成 / 失败 / 待执行 / 平均用时

### 模块 7：事件快速搜索

- 数据源：前端过滤 `/api/events` 已加载数据
- 最近活动卡片顶部：搜索框 + 来源筛选下拉
- 实时过滤，无需额外 API 调用

---

## 实施顺序

1. `events_db.py` — 新增表和查询方法
2. `profile_analyst.py` + `profile_analyst_cli.py` — 新建 ProfileAnalyst 类和 CLI 入口
3. `scheduler.py` — 注册 interval + cron 两个新 job
4. `server.js` — 新增 5 个 API 端点
5. `index.html` — 新增 7 个 UI 模块（含 CSS）

---

## 不在范围内

- 不引入前端框架或打包工具
- 不修改现有卡片的布局逻辑
- 不添加用户认证
