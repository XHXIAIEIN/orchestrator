"""
Telegram Channel — Bot API 适配器。

出站：ChannelMessage → sendMessage API
入站：Long polling getUpdates → 命令解析 → Event Bus
对话：非命令消息 → Claude API（带 SOUL 人格）→ 回复

零外部依赖，纯 urllib。
"""
import json
import logging
import os
import threading
import time
import urllib.request
import urllib.error
from collections import deque
from pathlib import Path
from typing import Optional

from src.channels.base import Channel, ChannelMessage

log = logging.getLogger(__name__)

PRIORITY_LEVELS = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}

# 入站命令定义
COMMANDS = {
    "/status": "查看系统状态",
    "/tasks": "最近任务列表",
    "/run": "触发场景执行 (用法: /run <scenario>)",
    "/channels": "查看 channel 状态",
    "/help": "显示帮助",
}


class TelegramChannel(Channel):
    """Telegram Bot 适配器。"""

    name = "telegram"

    def __init__(self, token: str, chat_id: str = "",
                 min_priority: str = "HIGH"):
        self.token = token
        self.chat_id = chat_id
        self.min_priority = PRIORITY_LEVELS.get(min_priority.upper(), 1)
        self.enabled = True
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._polling_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_update_id = 0

    # ── 出站：推送通知 ──

    def send(self, message: ChannelMessage) -> bool:
        """推送消息到 Telegram。"""
        # 优先级过滤
        msg_priority = PRIORITY_LEVELS.get(message.priority, 2)
        if msg_priority > self.min_priority:
            return False

        if not self.chat_id:
            log.warning("telegram: no chat_id configured, skip send")
            return False

        return self._send_text(self.chat_id, message.text)

    def _send_text(self, chat_id: str, text: str) -> bool:
        """发送文本消息。Markdown 失败自动 fallback 到纯文本。"""
        # 先尝试 Markdown
        ok = self._send_raw(chat_id, text, parse_mode="Markdown")
        if not ok:
            # Markdown 解析失败，去掉格式重发
            ok = self._send_raw(chat_id, text, parse_mode=None)
        return ok

    def _send_raw(self, chat_id: str, text: str, parse_mode: str = None) -> bool:
        """底层发送。"""
        body = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            body["parse_mode"] = parse_mode

        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            resp = urllib.request.urlopen(req, timeout=10)
            result = json.loads(resp.read())
            if not result.get("ok"):
                log.warning(f"telegram: sendMessage failed: {result}")
                return False
            return True
        except Exception as e:
            log.warning(f"telegram: send failed: {e}")
            return False

    # ── 入站：命令接收 ──

    def start(self):
        """启动 long polling 线程。"""
        if not self.chat_id:
            log.info("telegram: no chat_id, inbound commands disabled")
            return

        self._stop_event.clear()
        self._polling_thread = threading.Thread(
            target=self._poll_loop,
            name="telegram-poll",
            daemon=True,
        )
        self._polling_thread.start()
        log.info("telegram: polling started")

    def stop(self):
        """停止 polling。"""
        self._stop_event.set()
        if self._polling_thread:
            self._polling_thread.join(timeout=5)
            self._polling_thread = None

    def _poll_loop(self):
        """Long polling 主循环。"""
        while not self._stop_event.is_set():
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
            except Exception as e:
                log.debug(f"telegram: poll error: {e}")

            # 等待 2 秒或被停止
            self._stop_event.wait(timeout=2)

    def _get_updates(self) -> list:
        """获取新消息。"""
        params = f"offset={self._last_update_id + 1}&timeout=30&allowed_updates=[\"message\"]"
        req = urllib.request.Request(
            f"{self._base_url}/getUpdates?{params}",
            method="GET",
        )

        try:
            resp = urllib.request.urlopen(req, timeout=35)
            result = json.loads(resp.read())
            if result.get("ok"):
                return result.get("result", [])
        except Exception:
            pass
        return []

    def _handle_update(self, update: dict):
        """处理一条 update。"""
        self._last_update_id = update.get("update_id", self._last_update_id)

        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = (message.get("text") or "").strip()

        if not text or not chat_id:
            return

        # 白名单鉴权
        if self.chat_id and chat_id != self.chat_id:
            log.warning(f"telegram: rejected message from unauthorized chat_id={chat_id}")
            return

        # 解析命令 vs 对话
        if text.startswith("/"):
            self._handle_command(chat_id, text)
        else:
            self._handle_chat(chat_id, text)

    def _handle_command(self, chat_id: str, text: str):
        """解析并执行命令。"""
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]  # 去掉 @bot_name
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "/help":
            self._cmd_help(chat_id)
        elif cmd == "/status":
            self._cmd_status(chat_id)
        elif cmd == "/tasks":
            self._cmd_tasks(chat_id)
        elif cmd == "/run":
            self._cmd_run(chat_id, args)
        elif cmd == "/channels":
            self._cmd_channels(chat_id)
        else:
            self._send_text(chat_id, f"未知命令: {cmd}\n发送 /help 查看可用命令")

    def _cmd_help(self, chat_id: str):
        lines = ["*Orchestrator 命令*\n"]
        for cmd, desc in COMMANDS.items():
            lines.append(f"`{cmd}` — {desc}")
        self._send_text(chat_id, "\n".join(lines))

    def _cmd_status(self, chat_id: str):
        try:
            from src.core.health import HealthCheck
            hc = HealthCheck()
            report = hc.run()
            lines = ["*系统状态*\n"]
            lines.append(f"整体: {'[OK] 正常' if report.get('healthy') else '[ERR] 异常'}")
            for check_name, check_data in report.get("checks", {}).items():
                status = "[OK]" if check_data.get("ok") else "[ERR]"
                lines.append(f"{status} {check_name}")
            self._send_text(chat_id, "\n".join(lines))
        except Exception as e:
            self._send_text(chat_id, f"[ERR] 获取状态失败: {e}")

    def _cmd_tasks(self, chat_id: str):
        try:
            from src.storage.events_db import EventsDB
            db = EventsDB()
            tasks = db.query(
                "SELECT task_id, department, status, summary "
                "FROM tasks ORDER BY created_at DESC LIMIT 5"
            )
            if not tasks:
                self._send_text(chat_id, "暂无任务记录")
                return

            lines = ["*最近任务*\n"]
            status_tags = {
                "done": "[DONE]", "failed": "[FAIL]", "running": "[RUN]",
                "pending": "[WAIT]", "scrutiny_failed": "[GATE]",
            }
            for t in tasks:
                tag = status_tags.get(t[2], f"[{t[2]}]")
                dept = t[1] or "?"
                summary = (t[3] or "")[:60]
                lines.append(f"{tag} `{t[0][:8]}` [{dept}] {summary}")

            self._send_text(chat_id, "\n".join(lines))
        except Exception as e:
            self._send_text(chat_id, f"[ERR] 获取任务失败: {e}")

    def _cmd_run(self, chat_id: str, scenario: str):
        if not scenario.strip():
            self._send_text(chat_id, "用法: `/run <scenario_name>`")
            return

        try:
            from src.core.event_bus import get_event_bus, Event, Priority
            bus = get_event_bus()
            bus.publish(Event(
                event_type="channel.command.run",
                payload={"scenario": scenario.strip(), "source": "telegram"},
                priority=Priority.HIGH,
                source="channel:telegram",
            ))
            self._send_text(chat_id, f"[OK] 已提交场景执行: `{scenario.strip()}`")
        except Exception as e:
            self._send_text(chat_id, f"[ERR] 提交失败: {e}")

    def _cmd_channels(self, chat_id: str):
        try:
            from src.channels.registry import get_channel_registry
            reg = get_channel_registry()
            status = reg.get_status()
            lines = ["*Channel 状态*\n"]
            for name, info in status.items():
                tag = "[ON]" if info["enabled"] else "[OFF]"
                lines.append(f"{tag} {name} ({info['type']})")
            self._send_text(chat_id, "\n".join(lines))
        except Exception as e:
            self._send_text(chat_id, f"[ERR] 获取 channel 状态失败: {e}")

    # ── 对话：Claude API ──

    # 每个 chat 保留最近 20 轮对话历史
    _chat_history: dict[str, deque] = {}
    _HISTORY_MAX = 20

    # SOUL 系统提示词（启动时加载一次）
    _system_prompt: Optional[str] = None

    @classmethod
    def _get_system_prompt(cls) -> str:
        """加载 SOUL 人格作为系统提示词。"""
        if cls._system_prompt is not None:
            return cls._system_prompt

        repo_root = Path(__file__).resolve().parent.parent.parent
        parts = []

        # 加载 identity
        identity_path = repo_root / "SOUL" / "private" / "identity.md"
        if identity_path.exists():
            parts.append(identity_path.read_text(encoding="utf-8"))

        # 加载 voice
        voice_path = repo_root / "SOUL" / "private" / "voice.md"
        if voice_path.exists():
            parts.append(voice_path.read_text(encoding="utf-8"))

        if parts:
            cls._system_prompt = "\n\n---\n\n".join(parts)
        else:
            cls._system_prompt = (
                "你是 Orchestrator，一个本地 AI 管家。说话直接、有态度，是主人的损友。"
                "回复简洁，不用 emoji，用中文。"
            )

        # 追加 Telegram 特定指令
        cls._system_prompt += (
            "\n\n---\n\n"
            "## Telegram 对话规则\n"
            "- 你正在通过 Telegram 跟主人对话，保持简短（手机屏幕小）\n"
            "- 不要用 emoji\n"
            "- 不要用 Markdown 标题（# ##），Telegram 不渲染\n"
            "- 可以用 *加粗* 和 `代码`\n"
            "- 你可以通过 dispatch_task 工具派发任务给 Orchestrator 的 Governor 执行\n"
            "- Governor 管六个部门：工部(engineering)、礼部(operations)、中书省(protocol)、兵部(security)、刑部(quality)、吏部(personnel)\n"
            "- 预定义场景：full_audit（全面审计）、system_health（健康检查）、deep_scan（深度扫描）\n"
            "- 主人说想做什么就直接派，不用问确认。执行结果会自动推送回来\n"
            "- 纯闲聊就正常聊，别什么都往任务上靠\n"
            "- 如果主人要求的操作超出你能力范围（比如需要交互式调试），建议他回 Claude Code 终端\n"
        )
        return cls._system_prompt

    # ── Tool 定义：让 Haiku 能派发任务 ──

    _TOOLS = [
        {
            "name": "dispatch_task",
            "description": (
                "派发任务给 Orchestrator Governor 执行。可以是预定义场景"
                "（full_audit / system_health / deep_scan），也可以是自由描述的任务。"
                "任务会经过完整的管线：preflight -> scrutiny -> execute -> verify gate。"
                "执行结果会自动推送回 Telegram。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "任务描述或场景名称。如 'full_audit' 或 '检查 Steam 采集器为什么没数据'",
                    },
                    "department": {
                        "type": "string",
                        "description": "目标部门：engineering / operations / protocol / security / quality / personnel。不确定就留空让 Governor 自动路由。",
                        "default": "",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "default": "medium",
                    },
                },
                "required": ["action"],
            },
        },
        {
            "name": "query_status",
            "description": "查询 Orchestrator 系统状态：健康检查、最近任务、采集器状态等。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": ["health", "tasks", "collectors", "channels"],
                        "description": "查询类型",
                    },
                },
                "required": ["query_type"],
            },
        },
    ]

    def _handle_chat(self, chat_id: str, text: str):
        """处理非命令消息 — 调 Claude API 对话（支持 tool use 派发任务）。"""
        thread = threading.Thread(
            target=self._do_chat,
            args=(chat_id, text),
            name="tg-chat",
            daemon=True,
        )
        thread.start()

    def _do_chat(self, chat_id: str, text: str):
        """在后台线程执行对话（避免阻塞 polling）。"""
        try:
            # 维护对话历史
            if chat_id not in self._chat_history:
                self._chat_history[chat_id] = deque(maxlen=self._HISTORY_MAX)
            history = self._chat_history[chat_id]
            history.append({"role": "user", "content": text})

            from src.core.config import get_anthropic_client
            client = get_anthropic_client()

            # 对话循环：处理 tool use
            messages = list(history)
            max_rounds = 3  # 防止无限循环

            for _ in range(max_rounds):
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1024,
                    system=self._get_system_prompt(),
                    messages=messages,
                    tools=self._TOOLS,
                )

                # 收集文本回复和 tool_use
                text_parts = []
                tool_calls = []
                for block in response.content:
                    if block.type == "text" and block.text.strip():
                        text_parts.append(block.text.strip())
                    elif block.type == "tool_use":
                        tool_calls.append(block)

                # 如果有文本回复，先发给用户
                if text_parts:
                    reply = "\n".join(text_parts)
                    if len(reply) > 4000:
                        reply = reply[:4000] + "\n\n(...截断)"
                    self._send_text(chat_id, reply)

                # 如果没有 tool call，对话结束
                if not tool_calls:
                    # 记录到历史
                    assistant_content = []
                    for block in response.content:
                        if block.type == "text":
                            assistant_content.append({"type": "text", "text": block.text})
                    if assistant_content:
                        history.append({"role": "assistant", "content": assistant_content[0]["text"] if len(assistant_content) == 1 else assistant_content})
                    break

                # 执行 tool calls
                # 把 assistant 消息（含 tool_use）加入 messages
                messages.append({"role": "assistant", "content": response.content})

                tool_results = []
                for tc in tool_calls:
                    result = self._execute_tool(tc.name, tc.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result,
                    })

                messages.append({"role": "user", "content": tool_results})

            else:
                # max_rounds 用完
                history.append({"role": "assistant", "content": "(任务已派发)"})

        except Exception as e:
            log.error(f"telegram: chat failed: {e}")
            self._send_text(chat_id, f"[ERR] 对话失败: {e}")

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """执行 tool call，返回结果字符串。"""
        if tool_name == "dispatch_task":
            return self._tool_dispatch_task(tool_input)
        elif tool_name == "query_status":
            return self._tool_query_status(tool_input)
        return f"未知工具: {tool_name}"

    def _tool_dispatch_task(self, params: dict) -> str:
        """派发任务到 Governor。"""
        action = params.get("action", "")
        department = params.get("department", "")
        priority = params.get("priority", "medium")

        if not action:
            return "action 不能为空"

        try:
            from src.core.event_bus import get_event_bus, Event, Priority as EvPriority

            # 先尝试作为预定义场景
            predefined = {"full_audit", "system_health", "deep_scan"}
            if action in predefined:
                bus = get_event_bus()
                bus.publish(Event(
                    event_type="channel.command.run",
                    payload={"scenario": action, "source": "telegram_chat"},
                    priority=EvPriority.HIGH,
                    source="channel:telegram:chat",
                ))
                return f"已提交预定义场景: {action}"

            # 自由任务 → 创建任务给 Governor
            from src.storage.events_db import EventsDB
            db = EventsDB()
            task_id = db.create_task(
                action=action,
                reason="Telegram 对话触发",
                priority=priority,
                spec={
                    "summary": action,
                    "department": department,
                    "problem": action,
                    "source": "telegram_chat",
                },
                source="channel",
            )

            # 异步执行
            import threading
            def _run():
                try:
                    from src.governance.governor import Governor
                    gov = Governor(db=EventsDB())
                    gov.execute_task(task_id)
                except Exception as e:
                    log.error(f"telegram: task {task_id} execution failed: {e}")

            threading.Thread(target=_run, name=f"tg-task-{task_id}", daemon=True).start()

            return f"任务已创建: #{task_id}（{action[:50]}）。执行中，结果会自动推送。"

        except Exception as e:
            return f"派发失败: {e}"

    def _tool_query_status(self, params: dict) -> str:
        """查询系统状态。"""
        query_type = params.get("query_type", "health")

        try:
            if query_type == "health":
                from src.core.health import HealthCheck
                hc = HealthCheck()
                report = hc.run()
                lines = [f"整体: {'正常' if report.get('healthy') else '异常'}"]
                for name, data in report.get("checks", {}).items():
                    status = "OK" if data.get("ok") else "ERR"
                    lines.append(f"  [{status}] {name}")
                return "\n".join(lines)

            elif query_type == "tasks":
                from src.storage.events_db import EventsDB
                db = EventsDB()
                tasks = db.query(
                    "SELECT task_id, department, status, summary "
                    "FROM tasks ORDER BY created_at DESC LIMIT 5"
                )
                if not tasks:
                    return "暂无任务记录"
                lines = []
                for t in tasks:
                    lines.append(f"[{t[2]}] #{t[0][:8]} [{t[1] or '?'}] {(t[3] or '')[:50]}")
                return "\n".join(lines)

            elif query_type == "collectors":
                from src.storage.events_db import EventsDB
                db = EventsDB()
                rows = db.query(
                    "SELECT name, data FROM collector_reputation ORDER BY name"
                )
                if not rows:
                    return "无采集器数据"
                lines = []
                for r in rows:
                    try:
                        d = json.loads(r[1])
                        lines.append(f"[{d.get('status','?')}] {d.get('name','?')}: {d.get('last_count',0)} events")
                    except Exception:
                        lines.append(f"{r[0]}: parse error")
                return "\n".join(lines)

            elif query_type == "channels":
                from src.channels.registry import get_channel_registry
                reg = get_channel_registry()
                status = reg.get_status()
                if not status:
                    return "无 channel 配置"
                lines = []
                for name, info in status.items():
                    tag = "[ON]" if info["enabled"] else "[OFF]"
                    lines.append(f"{tag} {name} ({info['type']})")
                return "\n".join(lines)

            return f"未知查询类型: {query_type}"

        except Exception as e:
            return f"查询失败: {e}"
