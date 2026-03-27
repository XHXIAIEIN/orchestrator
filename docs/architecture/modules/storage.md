# Storage

> 持久化层 — SQLite EventsDB + Mixin 模式 + 向量检索。

## Key Files

| File | Purpose |
|------|---------|
| `events_db.py` | EventsDB 主类，单连接池 + 线程锁序列化 |
| `_schema.py` | 全部表 DDL + 迁移语句 |
| `_tasks_mixin.py` | 任务 CRUD（create/update/query/running tasks） |
| `_profile_mixin.py` | 用户画像读写 |
| `_learnings_mixin.py` | 经验教训存储 |
| `_runs_mixin.py` | 执行日志（run_logs / sub_runs）链式哈希 |
| `_sessions_mixin.py` | 对话会话管理 |
| `_wake_mixin.py` | 唤醒记录 |
| `vector_db.py` | 向量数据库封装（语义检索） |

## Schema Overview

| Table | Purpose |
|-------|---------|
| `events` | 采集器产出的原始事件（source/category/score/dedup_key） |
| `tasks` | 任务队列（spec/action/status/scrutiny_note/parent_task_id） |
| `logs` | 系统日志（level/source/run_id/step） |
| `daily_summaries` | 每日摘要 |
| `user_profile` | 用户画像 JSON |
| `insights` | 分析洞察 |
| `profile_analysis` | 周期性画像分析 |
| `attention_debts` | 注意力债务追踪 |
| `experiences` | 经验记录（date/type/summary/detail） |
| `agent_events` | Agent 执行事件流 |
| `collector_reputation` | 采集器信誉数据 |
| `run_logs` | 部门执行日志（链式哈希审计） |
| `sub_runs` | Rollout-Attempt 子运行记录 |
| `scheduler_status` | 调度器状态 KV |

## Architecture

EventsDB 用 Mixin 模式拆分：主类组合 TasksMixin、ProfileMixin、LearningsMixin、RunsMixin、SessionsMixin、WakeMixin。所有 Mixin 共享同一个 `_ConnPool`。

连接池是 per-path 单例：同一 DB 文件的所有 EventsDB 实例共享一个连接 + 锁。写操作通过 `threading.Lock` 序列化，失败时指数退避重试（最多 3 次）。使用 DELETE journal mode（WAL 的 -shm 文件在 Docker NTFS 挂载下会出问题）。

`run_logs` 表实现链式哈希审计：每条记录包含 `hash` 和 `prev_hash`，形成不可篡改的执行日志链。

## Related

- DB file: `data/events.db`
- Vector DB: `vector_db.py`（语义搜索，独立于 SQLite）
