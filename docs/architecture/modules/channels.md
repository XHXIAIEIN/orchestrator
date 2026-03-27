# Channels

> 双向用户通信层 — Event Bus 事件推送 + 入站消息解析。

## Key Files

| File | Purpose |
|------|---------|
| `base.py` | `Channel` ABC + `ChannelMessage` 数据类 |
| `formatter.py` | Event Bus 事件 → 人类可读消息（Unicode 块字符可视化） |
| `config.py` | Channel 层全局配置 |
| `registry.py` | Channel 注册与发现 |
| `inbound.py` | 入站消息统一处理 |
| `wake.py` | 唤醒词检测 |
| `media.py` | MediaType / MediaAttachment 多媒体抽象 |
| `transcribe.py` | 语音转文字 |

## Channel List

| Channel | Directory | Status |
|---------|-----------|--------|
| Telegram | `telegram/` | 完整：对话 + 派单 + 多媒体 + ASCII 动画 |
| WeChat | `wechat/` | 完整：登录 + CDN + 收发 |
| WeCom | `wecom/` | 基础适配 |
| Chat | `chat/` | 公共对话引擎（Claude API + SOUL 人格 + DB） |

## Per-Channel File Pattern

每个平台目录遵循相同结构：

| File | Role |
|------|------|
| `channel.py` | Channel 子类，组合 Sender + Handler + API |
| `handler.py` | 入站消息解析、命令路由 |
| `sender.py` | 出站消息发送、优先级队列、速率控制 |
| `api.py` | 平台原生 API 封装（如 `TelegramAPI`） |

Telegram 的 `TelegramChannel` 用多重继承组合：`TelegramSender, TelegramHandler, TelegramAPI, Channel`。

## Architecture

出站流：Event Bus 事件 → `formatter.py` 转为 `ChannelMessage` → 各 Channel 的 `send()` 方法推送。formatter 把部门名映射到中文（工部/礼部/兵部...），用 Unicode 块字符渲染热力图和状态矩阵。

入站流：Channel 的 `start()` 启动 long polling → 解析消息 → 经 `chat/` 公共引擎处理对话 → 必要时发布到 Event Bus 触发任务派单。

Chat 公共层提供对话上下文管理、工具调用、DB 持久化，各平台 Channel 复用而非各自实现。

## Related

- Chat engine: `src/channels/chat/`
- Telegram handler: `src/channels/telegram/handler.py`
