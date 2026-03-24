# Channel Layer — 从 OpenClaw 偷来的通信层

**日期**: 2026-03-22
**状态**: 设计完成，待实施
**灵感来源**: OpenClaw 的 Channel 适配器模式 + Hub-and-spoke Gateway

## 背景

Orchestrator 有完整的 Event Bus（四级优先队列 + SQLite 持久化 + 反应式规则）和 Fan-out Collector（多路输出），但**没有任何外部消息平台集成**。用户只能通过 Dashboard 或读 JSONL 文件查看状态。

OpenClaw 用统一 Channel 接口适配 20+ 平台。我们不需要那么多，但需要同样的抽象层。

## 设计

### 架构总览

```
出站（推送通知）:
  Event Bus → FanOutCollector → ChannelTarget → [Telegram / WeCom / ...]

入站（命令输入）:
  [Telegram polling] → InboundRouter → parse command → Event Bus → Governor
```

### 组件清单

#### 1. `src/channels/base.py` — Channel 抽象基类

```python
class Channel(ABC):
    name: str               # "telegram", "wecom", etc.
    enabled: bool

    @abstractmethod
    async def send(self, message: ChannelMessage) -> bool:
        """推送一条消息到该平台。"""

    async def start(self):
        """启动入站监听（如 polling）。可选实现。"""

    async def stop(self):
        """停止监听。"""

@dataclass
class ChannelMessage:
    text: str               # Markdown 格式正文
    event_type: str         # 原始事件类型
    priority: str           # CRITICAL/HIGH/NORMAL/LOW
    department: str         # 来源部门
    timestamp: str          # ISO 时间戳
```

#### 2. `src/channels/telegram.py` — Telegram Bot

**出站:**
- `ChannelMessage` → Telegram Markdown → `POST /bot{token}/sendMessage`
- 只用 `urllib.request`，不引入额外依赖（与 fan_out.py 保持一致）

**入站:**
- Long polling via `getUpdates`
- 命令白名单:
  - `/status` → 返回 health check + 采集器状态
  - `/tasks` → 返回最近 5 个任务
  - `/run <scenario>` → 触发场景执行
  - `/help` → 命令列表
- `chat_id` 白名单鉴权（环境变量配置）

**过滤:**
- 默认只推送 `CRITICAL` 和 `HIGH` 优先级事件
- 可通过环境变量 `TELEGRAM_MIN_PRIORITY` 调整

#### 3. `src/channels/wecom.py` — 企业微信 Webhook

**仅出站**（Webhook 是单向的）:
- `ChannelMessage` → WeChat Markdown 格式 → `POST webhook_url`
- 无入站能力（企业微信 Webhook 不支持接收消息）

#### 4. `src/channels/formatter.py` — 消息格式化器

统一将 Event Bus 事件转为人类可读消息:

| event_type | 格式 |
|---|---|
| `task.completed` | ✅ **[工部]** 任务完成: {summary} |
| `task.failed` | ❌ **[{dept}]** 任务失败: {error} |
| `task.gate_failed` | 🚫 **[门下省]** 质量门禁未通过: {reason} |
| `health.degraded` | ⚠️ 系统健康异常: {details} |
| `collector.failed` | 📡 采集器故障: {collector} |
| `task.escalated` | 🔺 任务升级需人工介入: {summary} |

#### 5. `src/channels/registry.py` — Channel 注册表

```python
class ChannelRegistry:
    def register(self, channel: Channel): ...
    def broadcast(self, message: ChannelMessage): ...  # 广播到所有启用的 channel
    def start_all(self): ...   # 启动所有入站监听
    def stop_all(self): ...    # 停止所有监听
    def auto_discover(self): ... # 从环境变量自动发现
```

**自动发现逻辑:**
- `TELEGRAM_BOT_TOKEN` 存在 → 注册 TelegramChannel
- `WECOM_WEBHOOK_URL` 存在 → 注册 WeComChannel
- 都不存在 → Channel 层静默不启用（zero-impact）

#### 6. Fan-out 集成

在 `FanOutCollector` 增加 `"channel"` target type:

```python
elif target.type == "channel":
    self._emit_channel(event_type, data, department)
```

调用 `ChannelRegistry.broadcast()`。

### 配置

全部通过环境变量，与现有 Docker 模式一致:

```env
# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=987654321
TELEGRAM_MIN_PRIORITY=HIGH          # 可选，默认 HIGH

# 企业微信（仅出站）
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
```

### 不做的东西

- 20+ 平台适配（YAGNI）
- 微信个人号（灰色地带）
- Voice Wake / A2UI
- WebSocket 改造
- 复杂对话状态管理（不是聊天机器人）

### 文件清单

```
src/channels/
├── __init__.py
├── base.py          # Channel ABC + ChannelMessage
├── formatter.py     # 事件→消息格式化
├── registry.py      # 注册表 + 自动发现 + 生命周期
├── telegram.py      # Telegram Bot（出站+入站）
└── wecom.py         # 企业微信 Webhook（仅出站）
```

修改的现有文件:
- `src/governance/fan_out.py` — 增加 `"channel"` target type
- `src/scheduler.py` — 启动时调用 `registry.start_all()`
- `docker-compose.yml` — 增加环境变量模板（注释状态）

### 依赖

**零新依赖**。全部用 `urllib.request`（与现有 fan_out.py 一致）。
Telegram Bot API 和企业微信 Webhook 都是简单 HTTP POST。
