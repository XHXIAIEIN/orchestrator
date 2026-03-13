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
- `get_events_by_day(days=60)` — 按日期聚合事件数，供热力图使用
- `get_events_by_category(days=N)` — 按 category 统计时长，支持 1/7/30 天
- `get_profile_analysis(type=None)` — 获取最新画像报告

### 修改：`src/scheduler.py`

新增两个调度 job：
1. **每 6 小时**：`ProfileAnalyst().run(type='periodic')`
2. **每日 06:00**：`ProfileAnalyst().run(type='daily')`（数据窗口锁定前一天）

---

## Node 层（`dashboard/server.js`）

新增 API 端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/profile-analysis` | 返回最新深度画像报告 |
| POST | `/api/profile-analysis/refresh` | 按需触发重新生成，spawn Python 子进程，完成后 broadcast WebSocket 通知 |
| GET | `/api/events/heatmap?days=60` | 按日聚合事件数（默认近 60 天） |
| GET | `/api/summaries` | 返回近 7 天 daily_summaries |
| GET | `/api/stats/categories?days=N` | 按 category 统计，N 支持 1/7/30 |

---

## 前端层（`dashboard/public/index.html`）

7 个新卡片，全部加入现有 `.grid`，沿用当前 CSS 变量和黑色主题。

### 模块 1：用户画像卡片（基础）

- 数据源：`/api/summary`（已有，含 profile 字段）
- 展示：兴趣标签、技能、活跃时段等结构化字段
- 随每次日常分析更新

### 模块 2：深度画像分析（增强版）⭐

- 数据源：`/api/profile-analysis`
- 展示字段：overview、strengths、blind_spots、suggestions（带优先级色标）、commentary、daily_note
- 右上角「刷新」按钮 → POST `/api/profile-analysis/refresh` → loading 动画 → WebSocket 收到 `profile_analysis_done` 后重渲染
- 显示生成时间 + 类型（定期/晨报）

### 模块 3：7 日趋势摘要

- 数据源：`/api/summaries`
- 展示：每天一行，格式：`日期 · 关键词 tags · 主要活动类型`
- 按时间倒序排列

### 模块 4：活动热力图

- 数据源：`/api/events/heatmap?days=60`
- 纯 JS 渲染，近 60 天，按周排列（7 列）
- 格子颜色深浅对应当天事件数（4 级深浅）
- 点击格子在卡片内展开当日 top 5 事件标题

### 模块 5：分类时间分布（增强版）

- 数据源：`/api/stats/categories?days=N`
- 在现有「采集统计」卡片基础上扩展
- 新增三个切换按钮：今日 / 7天 / 30天
- 增加按 `category` 细分行，带颜色进度条

### 模块 6：任务执行统计

- 数据源：前端从 `/api/tasks` 已有数据计算，无需新 API
- 在任务列表上方展示：总数 / 完成 / 失败 / 待执行 / 平均用时
- 纯前端聚合

### 模块 7：事件快速搜索

- 数据源：前端过滤 `/api/events` 已加载数据
- 最近活动卡片顶部：搜索框 + 来源筛选下拉
- 实时过滤，无需额外 API 调用

---

## 实施顺序

1. `events_db.py` — 新增表和查询方法
2. `profile_analyst.py` — 新建 ProfileAnalyst 类
3. `scheduler.py` — 注册两个新 job
4. `server.js` — 新增 5 个 API 端点
5. `index.html` — 新增 7 个 UI 模块（含 CSS）

---

## 不在范围内

- 不引入前端框架或打包工具
- 不修改现有卡片的布局逻辑
- 不添加用户认证
