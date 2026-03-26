# Wake Session Redesign

> Wake Claude 从"文件邮箱"升级为"会话模型"，集成 Governor 审批，支持交互介入。

## 数据模型

`wake_sessions` 表（events.db）：

```sql
CREATE TABLE IF NOT EXISTS wake_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL,       -- FK → tasks (Governor 审批)
    chat_id     TEXT NOT NULL,           -- 发起人，Claude Code 用 bot-tg/bot-wx 查上下文
    spotlight   TEXT NOT NULL,           -- 一句话聚焦 + 关键词
    mode        TEXT NOT NULL DEFAULT 'silent',  -- silent / milestone
    status      TEXT NOT NULL DEFAULT 'pending', -- 见状态流转
    result      TEXT,                    -- 事后结构化报告
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_wake_status ON wake_sessions(status);
```

- **spotlight**: 事前聚焦，如 "修复 TG bot 轮询崩溃 [telegram, polling, fix]"
- **result**: 事后报告（改了哪些文件、跑了什么命令、最终状态）
- **里程碑**: 不存此表，通过 `task_id` 关联 `agent_events` 表（`event_type='wake.milestone'`）
- **交互指令**: 不存此表，聊天记录已在 `chat_messages` 表，追加指令写 `agent_events`（`event_type='wake.inject'`）

## 状态流转

```
pending → approved → running → done
            ↘                    ↗
           denied    running → failed
                       ↓
                    cancelled
```

| 状态 | 驱动者 | 行为 |
|------|--------|------|
| pending | chat engine `wake_claude` tool | 创建 wake_session + Governor 任务 |
| approved | Governor 审批通过 | watcher 下一轮轮询拉起 |
| denied | Governor 审批拒绝 | 终态，推通知 |
| running | watcher | 拉起 Claude Code，写 started_at |
| done | watcher | 正常结束，写 result + finished_at |
| failed | watcher | 异常退出，写 result 记录错误 |
| cancelled | 用户 `/wake cancel` | watcher 每 turn 检测，终止 Claude Code |

## 触发方式

### LLM 自动触发（保留）

Chat engine 的 `wake_claude` tool 仍由 LLM 自主判断调用。tool 内部：

1. 生成 spotlight（LLM 产出一句话摘要 + 关键词）
2. 创建 Governor 任务（source="wake"）
3. 创建 wake_session 关联 task_id
4. 回复用户"收到，等审批"

### `/wake` 命令（新增）

解析规则：第一个 token 精确匹配子命令表，不命中则整行当任务描述。

| 命令 | 作用 |
|------|------|
| `/wake <描述>` | 派任务，描述即 spotlight |
| `/wake` | 查活跃 session |
| `/wake cancel` | 取消当前 running session |
| `/wake verbose` | 切 milestone 模式 |
| `/wake quiet` | 切 silent 模式 |

保留子命令：`cancel`, `verbose`, `quiet`。

示例：
- `/wake 修复 TG bot 轮询崩溃` → 派任务
- `/wake cancel` → 取消
- `/wake 修复 cancel 相关的 bug` → 派任务（cancel 不在第一个位置）

## 交互模式

### 默认 silent

Claude Code 跑完推 result 报告，过程不打扰。

### milestone 模式

Claude Code 每完成关键步骤写 `agent_events`（`event_type='wake.milestone'`），channel 层推送到 TG/WX。

### 切换

- 用户发 `/wake verbose` → 更新 mode 为 milestone
- 用户发 `/wake quiet` → 更新 mode 为 silent
- LLM 遇到明显相关消息（"进度怎么样"、"快点"）也可自动路由

### 中途追加指令

LLM 判断用户消息是给 wake 任务的 → 调用 `wake_interact` tool → 写 `agent_events`（`event_type='wake.inject'`）→ watcher 每 turn 间检查并注入 Claude Code 下一轮输入。

## Watcher 重构

### 从文件轮询改为 DB 轮询

| 项目 | 现在 | 重构后 |
|------|------|--------|
| 任务来源 | tmp/wake/*.json | wake_sessions 表 |
| 状态管理 | 改文件内容 | 改 DB 行 |
| 里程碑 | 无 | 写 agent_events |
| 通知 | watcher 直调 TG API | watcher 写 DB，channel 层订阅推送 |
| 取消 | 不支持 | 每 turn 检查 status |
| 交互注入 | 不支持 | 每 turn 检查 agent_events wake.inject |
| 结果 | 发 TG 后丢弃 | 写入 result 字段 |

### watcher 核心循环

```python
while True:
    sessions = db.get_wake_sessions(status='approved')
    for s in sessions:
        submit_to_executor(s)
    sleep(POLL_INTERVAL)
```

### 执行器每 turn 检查

```python
# Agent SDK 回调中
if db.get_wake_session(session_id).status == 'cancelled':
    kill subprocess
    return

injects = db.get_agent_events(task_id, event_type='wake.inject', since=last_check)
if injects:
    inject into next prompt turn
```

### watcher 不再发通知

watcher 只写 DB 状态和事件。通知由 channel 层负责：
- channel 层轮询或订阅 event bus
- 根据 session mode 决定推什么（silent 只推终态，milestone 推每个里程碑）

### tmp/wake/ 降级为工作目录

不再承担消息传递职责，仅存临时产物：

```
tmp/wake/
  telegram/{session_id}/    -- TG 来源的临时文件
  wechat/{session_id}/      -- WX 来源的临时文件
```

## Governor 集成

wake 任务全走 Governor 审批链：

1. `wake_claude` tool 或 `/wake <描述>` 创建任务（source="wake", priority 根据 spotlight 关键词判断）
2. Governor 按现有审批策略处理（auto-approve / 人工审批 / scrutiny）
3. 审批通过 → wake_session status 从 pending 改为 approved
4. watcher 捞到 approved session 开始执行

## 废弃项

- `tmp/wake/*.json` 作为消息队列 → 废弃（目录保留做工作目录）
- `src/channels/wake.py` 的 `write_wake_request()` / `read_response()` / `list_pending()` → 重写
- watcher 直调 TG API → 移除，通知走 channel 层
- 60s dedup 机制 → 不再需要（DB 唯一性 + Governor 审批天然去重）
