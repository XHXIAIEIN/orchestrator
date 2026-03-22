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
        """发送文本消息。"""
        payload = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }).encode("utf-8")

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
            "- 如果主人问系统状态相关的，提醒他用 /status 或 /tasks 命令\n"
            "- 如果主人想跑任务，提醒他用 /run <scenario>\n"
            "- 你没有能力直接执行代码或修改文件，但可以建议主人回到 Claude Code 终端操作\n"
        )
        return cls._system_prompt

    def _handle_chat(self, chat_id: str, text: str):
        """处理非命令消息 — 调 Claude API 对话。"""
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

            # 调 Claude API
            from src.core.config import get_anthropic_client
            client = get_anthropic_client()

            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=self._get_system_prompt(),
                messages=list(history),
            )

            reply = next(
                (b.text for b in response.content if b.type == "text"), ""
            ).strip()

            if not reply:
                reply = "...（管家沉默了一下，可能在想怎么吐槽你）"

            # 记录 assistant 回复到历史
            history.append({"role": "assistant", "content": reply})

            # Telegram 消息长度限制 4096
            if len(reply) > 4000:
                reply = reply[:4000] + "\n\n(...截断了，话太多)"

            self._send_text(chat_id, reply)

        except Exception as e:
            log.error(f"telegram: chat failed: {e}")
            self._send_text(chat_id, f"[ERR] 对话失败: {e}")
