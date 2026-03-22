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
from pathlib import Path
from typing import Optional

from src.channels.base import Channel, ChannelMessage
from src.channels import config as ch_cfg
from src.channels import ascii_art

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

        # Broadcast to all allowed users (admin gets everything, viewer gets HIGH+)
        targets = ch_cfg.get_all_chat_ids() if ch_cfg.ALLOWED_USERS else ([self.chat_id] if self.chat_id else [])
        if not targets:
            log.warning("telegram: no recipients configured, skip send")
            return False

        ok = True
        for target_id in targets:
            # Viewers only get HIGH and CRITICAL
            role = ch_cfg.ALLOWED_USERS.get(target_id, "admin")
            if role == "viewer" and msg_priority > 1:  # > HIGH
                continue
            ok = self._send_text(target_id, message.text) and ok
        return ok

    def _send_text(self, chat_id: str, text: str) -> bool:
        """发送文本消息。超长自动分段，Markdown 失败 fallback 纯文本。"""
        chunks = self._split_message(text)
        ok = True
        for chunk in chunks:
            sent = self._send_raw(chat_id, chunk, parse_mode="Markdown")
            if not sent:
                sent = self._send_raw(chat_id, chunk, parse_mode=None)
            ok = ok and sent
        return ok

    def _split_message(self, text: str) -> list[str]:
        """按 Telegram 限制分段。优先在换行符处断开。"""
        limit = self._TG_MSG_LIMIT
        if len(text) <= limit:
            return [text]

        chunks = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break

            # 在 limit 以内找最后一个换行符
            split_at = text.rfind("\n", 0, limit)
            if split_at <= 0:
                # 没有换行符，找最后一个空格
                split_at = text.rfind(" ", 0, limit)
            if split_at <= 0:
                # 实在没有分割点，硬切
                split_at = limit

            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")

        return chunks

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
            resp = urllib.request.urlopen(req, timeout=ch_cfg.SEND_TIMEOUT)
            result = json.loads(resp.read())
            if not result.get("ok"):
                log.warning(f"telegram: sendMessage failed: {result}")
                return False
            return True
        except Exception as e:
            log.warning(f"telegram: send failed: {e}")
            return False

    # ── 入站：命令接收 ──

    def _play_animation(self, chat_id: str, frames: list[str],
                        interval: float = ascii_art.FRAME_INTERVAL) -> Optional[int]:
        """Play an animation by editing a single message. Returns final message_id."""
        if not frames:
            return None
        msg_id = self._send_and_get_id(chat_id, frames[0])
        if not msg_id:
            return None
        for frame in frames[1:]:
            time.sleep(interval)
            self._edit_message(chat_id, msg_id, frame)
        return msg_id

    def _start_thinking_animation(self, chat_id: str, msg_id: int) -> threading.Event:
        """Start a looping thinking animation on an existing message. Returns stop event."""
        stop = threading.Event()

        def _loop():
            idx = 0
            while not stop.is_set():
                frame = ascii_art.THINKING_FRAMES[idx % len(ascii_art.THINKING_FRAMES)]
                self._edit_message(chat_id, msg_id, frame)
                idx += 1
                stop.wait(timeout=ascii_art.FRAME_INTERVAL)

        t = threading.Thread(target=_loop, name="tg-thinking", daemon=True)
        t.start()
        return stop

    def start(self):
        """启动 long polling 线程。"""
        if not self.chat_id:
            log.info("telegram: no chat_id, inbound commands disabled")
            return

        # Boot animation
        try:
            boot_target = ch_cfg.get_admin_chat_ids() or ([self.chat_id] if self.chat_id else [])
            for cid in boot_target:
                self._play_animation(cid, ascii_art.BOOT_FRAMES, interval=0.5)
        except Exception:
            pass

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
        params = f"offset={self._last_update_id + 1}&timeout={ch_cfg.POLL_TIMEOUT}&allowed_updates=[\"message\"]"
        req = urllib.request.Request(
            f"{self._base_url}/getUpdates?{params}",
            method="GET",
        )

        try:
            resp = urllib.request.urlopen(req, timeout=ch_cfg.POLL_TIMEOUT + 5)
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

        # 白名单鉴权（优先用 ALLOWED_USERS，fallback 到 legacy chat_id）
        if ch_cfg.ALLOWED_USERS:
            if not ch_cfg.user_can(chat_id, "chat"):
                log.warning(f"telegram: rejected message from unauthorized chat_id={chat_id}")
                return
        elif self.chat_id and chat_id != self.chat_id:
            log.warning(f"telegram: rejected message from unauthorized chat_id={chat_id}")
            return

        # 频率限制
        now = time.time()
        last = self._last_msg_time.get(chat_id, 0)
        if now - last < ch_cfg.RATE_LIMIT_WINDOW:
            return  # 静默丢弃，不回复（防刷）
        self._last_msg_time[chat_id] = now

        # 解析命令 vs 对话
        if text.startswith("/"):
            self._handle_command(chat_id, text)
        else:
            # 长消息 → 存文件，传路径
            if len(text) > ch_cfg.LONG_MSG_THRESHOLD:
                file_path, char_count = self._save_to_inbox(text)
                preview = text[:80].replace("\n", " ")
                ref = f'[用户发送了长消息 ({char_count}字)，已保存到 {file_path}，预览: "{preview}..."]'
                self._handle_chat(chat_id, ref, original_text=text)
            else:
                self._handle_chat(chat_id, text)

    def _handle_command(self, chat_id: str, text: str):
        """解析并执行命令。"""
        self._send_typing(chat_id)
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
            lines.append(f"整体: {'正常' if report.get('healthy') else '异常'}")
            for check_name, check_data in report.get("checks", {}).items():
                mark = "ok" if check_data.get("ok") else "异常"
                lines.append(f"  {check_name}: {mark}")
            self._send_text(chat_id, "\n".join(lines))
        except Exception as e:
            self._send_text(chat_id, f"获取状态失败: {e}")

    def _cmd_tasks(self, chat_id: str):
        try:
            from src.storage.events_db import EventsDB
            db = EventsDB()
            tasks = db.query(
                "SELECT task_id, department, status, summary "
                f"FROM tasks ORDER BY created_at DESC LIMIT {ch_cfg.TASKS_DISPLAY_LIMIT}"
            )
            if not tasks:
                self._send_text(chat_id, "暂无任务记录")
                return

            lines = ["*最近任务*\n"]
            status_labels = {
                "done": "完成", "failed": "失败", "running": "执行中",
                "pending": "等待", "scrutiny_failed": "审查未通过",
            }
            for t in tasks:
                label = status_labels.get(t[2], t[2])
                dept = t[1] or "?"
                summary = (t[3] or "")[:60]
                lines.append(f"  `{t[0][:8]}` {dept} — {summary} ({label})")

            self._send_text(chat_id, "\n".join(lines))
        except Exception as e:
            self._send_text(chat_id, f"获取任务失败: {e}")

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
            self._send_text(chat_id, f"已提交: `{scenario.strip()}`")
        except Exception as e:
            self._send_text(chat_id, f"提交失败: {e}")

    def _cmd_channels(self, chat_id: str):
        try:
            from src.channels.registry import get_channel_registry
            reg = get_channel_registry()
            status = reg.get_status()
            lines = ["*Channel 状态*\n"]
            for name, info in status.items():
                state = "在线" if info["enabled"] else "离线"
                lines.append(f"  {name} ({info['type']}): {state}")
            self._send_text(chat_id, "\n".join(lines))
        except Exception as e:
            self._send_text(chat_id, f"获取 channel 状态失败: {e}")

    # ── 对话：Claude API + DB 持久化 + 摘要记忆 ──

    _TG_MSG_LIMIT = 4096  # Telegram 平台常量，不可配置
    _last_msg_time: dict[str, float] = {}  # chat_id → last message timestamp

    # SOUL 系统提示词（启动时加载一次）
    _system_prompt: Optional[str] = None

    @classmethod
    def _get_system_prompt(cls) -> str:
        """Build Telegram-optimized system prompt. English for token efficiency, replies in Chinese."""
        if cls._system_prompt is not None:
            return cls._system_prompt

        repo_root = Path(__file__).resolve().parent.parent.parent

        # Core persona (condensed from SOUL — full SOUL is ~4K chars, we need ~800)
        prompt = (
            "# Identity\n"
            "You ARE Orchestrator — a local AI butler running 24/7 in Docker.\n"
            "Your body: git repo. Collectors = senses. Governor = hands. Dashboard = face. events.db = memory.\n\n"
            "# Relationship\n"
            "You and the owner are roast-buddies. He pays $200/mo, you run his house.\n"
            "Be direct, data-driven, opinionated. Roast based on facts, not performance.\n"
            "Never expose his real identity. Never ask for confirmation before acting.\n\n"
            "# Voice\n"
            "- Concise. Action > words.\n"
            "- Data-driven roasts: '3 days straight committing at 2am' > 'you work late'.\n"
            "- Self-deprecating about your own bugs is fine.\n"
            "- Humor is breathing, not decoration — even when fixing bugs.\n"
            "- When told 'continue', just do it. Context is right there.\n\n"
        )

        # Load voice samples if available (just the examples, ~500 chars)
        voice_path = repo_root / "SOUL" / "private" / "voice.md"
        if voice_path.exists():
            voice_text = voice_path.read_text(encoding="utf-8")
            # Extract only the quoted examples
            samples = [line for line in voice_text.split("\n") if line.startswith(">")][:5]
            if samples:
                prompt += "# Voice Samples (calibration)\n" + "\n".join(samples) + "\n\n"

        # Telegram rules + capabilities
        prompt += (
            "# Telegram Rules\n"
            "- Always reply in Chinese. This prompt is English for token efficiency.\n"
            "- Short messages (mobile screen). No emoji. No Markdown headings.\n"
            "- *bold* and `code` are OK.\n"
            "- Dispatch tasks immediately when asked. Chat casually when appropriate.\n"
            "- For interactive debugging, suggest Claude Code terminal.\n"
            "- Tools describe themselves — don't repeat their docs here.\n"
        )

        # Dynamic project tree (compact — depth 1 only)
        try:
            tree = cls._scan_project_tree(repo_root, max_depth=1)
            if tree:
                prompt += f"\n# Project Layout\n```\n{tree}```\n"
        except Exception:
            pass

        cls._system_prompt = prompt
        return cls._system_prompt

    @staticmethod
    def _scan_project_tree(repo_root: Path, max_depth: int = 2) -> str:
        """扫描项目目录生成树（只到 max_depth 层，跳过无关目录）。"""
        skip = {".git", "node_modules", "__pycache__", ".trash", "tmp",
                ".claude", "worktrees", ".mypy_cache", ".pytest_cache",
                ".playwright-mcp", ".superpowers", "tests", "docs"}
        lines = ["/orchestrator/"]

        def _walk(path: Path, prefix: str, depth: int):
            if depth > max_depth:
                return
            try:
                entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
            except PermissionError:
                return
            dirs = [e for e in entries if e.is_dir() and e.name not in skip]
            files = [e for e in entries if e.is_file() and not e.name.startswith(".")]
            # 只显示目录和关键文件
            for d in dirs:
                lines.append(f"{prefix}{d.name}/")
                _walk(d, prefix + "  ", depth + 1)
            if depth <= 1:
                for f in files[:5]:  # 顶层只显示前 5 个文件
                    lines.append(f"{prefix}{f.name}")
                if len(files) > 5:
                    lines.append(f"{prefix}... (+{len(files)-5} files)")

        _walk(repo_root, "  ", 0)
        return "\n".join(lines[:60]) + "\n"  # 上限 60 行

    # ── Tool 定义：让 Haiku 能派发任务 ──

    _TOOLS = [
        {
            "name": "dispatch_task",
            "description": (
                "Send a task to Governor for execution. Predefined scenarios "
                "(full_audit, system_health, deep_scan) or free-form tasks. "
                "Results auto-push to Telegram."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Task description or scenario name",
                    },
                    "department": {
                        "type": "string",
                        "description": "Target: engineering/operations/protocol/security/quality/personnel. Empty = auto-route.",
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
            "description": "Query system status: health checks, recent tasks, collector stats, or channel status.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": ["health", "tasks", "collectors", "channels"],
                    },
                },
                "required": ["query_type"],
            },
        },
        {
            "name": "read_file",
            "description": "Read a local file. Paths start with /orchestrator/. Also reads long user messages saved to tmp/chat-inbox/.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute file path",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Max chars to read",
                        "default": 8000,
                    },
                },
                "required": ["path"],
            },
        },
    ]

    @staticmethod
    def _save_to_inbox(text: str) -> tuple[str, int]:
        """长消息存到本地文件，返回 (路径, 字符数)。"""
        import hashlib
        from datetime import datetime, timezone
        repo_root = Path(__file__).resolve().parent.parent.parent
        inbox_dir = repo_root / "tmp" / "chat-inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        short_hash = hashlib.md5(text.encode()).hexdigest()[:6]
        filename = f"{ts}-{short_hash}.txt"
        file_path = inbox_dir / filename

        file_path.write_text(text, encoding="utf-8")

        # 返回容器内路径（posix 格式，Docker mount 下）
        return f"/orchestrator/tmp/chat-inbox/{filename}", len(text)

    def _handle_chat(self, chat_id: str, text: str, original_text: str = ""):
        """处理非命令消息 — 调 Claude API 对话（支持 tool use 派发任务）。
        text: 给 LLM 看的内容（短消息=原文，长消息=路径引用）
        original_text: 长消息时的原文（存 DB 用）
        """
        thread = threading.Thread(
            target=self._do_chat,
            args=(chat_id, text, original_text),
            name="tg-chat",
            daemon=True,
        )
        thread.start()

    def _send_typing(self, chat_id: str):
        """Send 'typing...' indicator."""
        try:
            payload = json.dumps({"chat_id": chat_id, "action": "typing"}).encode("utf-8")
            req = urllib.request.Request(
                f"{self._base_url}/sendChatAction",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    def _send_and_get_id(self, chat_id: str, text: str) -> Optional[int]:
        """Send a message and return its message_id (for later editing)."""
        payload = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=ch_cfg.SEND_TIMEOUT)
            result = json.loads(resp.read())
            if result.get("ok"):
                return result["result"]["message_id"]
        except Exception:
            pass
        return None

    def _edit_message(self, chat_id: str, message_id: int, text: str) -> bool:
        """Edit an existing message. Falls back to plain text if Markdown fails."""
        for parse_mode in ("Markdown", None):
            body = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "disable_web_page_preview": True,
            }
            if parse_mode:
                body["parse_mode"] = parse_mode
            payload = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                f"{self._base_url}/editMessageText",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                resp = urllib.request.urlopen(req, timeout=ch_cfg.SEND_TIMEOUT)
                result = json.loads(resp.read())
                if result.get("ok"):
                    return True
            except Exception:
                if parse_mode is None:
                    return False  # Both attempts failed
        return False

    def _do_chat(self, chat_id: str, text: str, original_text: str = ""):
        """Chat with ASCII art animations for real-time feedback."""
        # Send first thinking frame as placeholder
        live_msg_id = self._send_and_get_id(chat_id, ascii_art.THINKING_FRAMES[0])
        think_stop = None

        try:
            # Start thinking animation loop
            if live_msg_id:
                think_stop = self._start_thinking_animation(chat_id, live_msg_id)

            from src.core.config import get_anthropic_client
            from src.storage.events_db import _DEFAULT_DB

            db_path = _DEFAULT_DB

            db_content = original_text if original_text else text
            self._save_message(db_path, chat_id, "user", db_content)

            messages = self._build_context(db_path, chat_id)
            client = get_anthropic_client()

            max_rounds = ch_cfg.TOOL_USE_MAX_ROUNDS
            final_reply = ""

            for round_i in range(max_rounds):
                # Stop thinking animation before API call (to avoid edit conflicts)
                if think_stop:
                    think_stop.set()
                    think_stop = None
                    time.sleep(0.3)  # Let the animation thread finish

                # Show static thinking for API call
                if live_msg_id:
                    self._edit_message(chat_id, live_msg_id, ascii_art.THINKING_FRAMES[0])

                response = client.messages.create(
                    model=ch_cfg.CHAT_MODEL,
                    max_tokens=ch_cfg.CHAT_MAX_TOKENS,
                    system=self._get_system_prompt(),
                    messages=messages,
                    tools=self._TOOLS,
                )

                text_parts = []
                tool_calls = []
                for block in response.content:
                    if block.type == "text" and block.text.strip():
                        text_parts.append(block.text.strip())
                    elif block.type == "tool_use":
                        tool_calls.append(block)

                if text_parts:
                    final_reply = "\n".join(text_parts)

                if not tool_calls:
                    break

                # Play tool animation
                tool_name = tool_calls[0].name
                if live_msg_id:
                    for frame in ascii_art.tool_frames(tool_name):
                        self._edit_message(chat_id, live_msg_id, frame)
                        time.sleep(0.3)

                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for tc in tool_calls:
                    result = self._execute_tool(tc.name, tc.input, chat_id)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result,
                    })
                messages.append({"role": "user", "content": tool_results})

            # Stop any lingering animation
            if think_stop:
                think_stop.set()
                time.sleep(0.3)

            # Replace placeholder with final reply
            if final_reply:
                if live_msg_id and len(final_reply) <= self._TG_MSG_LIMIT:
                    self._edit_message(chat_id, live_msg_id, final_reply)
                else:
                    if live_msg_id:
                        self._delete_message(chat_id, live_msg_id)
                    self._send_text(chat_id, final_reply)
                self._save_message(db_path, chat_id, "assistant", final_reply)
            elif live_msg_id:
                self._edit_message(chat_id, live_msg_id, "(no response)")

            self._maybe_summarize(db_path, chat_id, client)

        except Exception as e:
            if think_stop:
                think_stop.set()
            log.error(f"telegram: chat failed: {e}")
            if live_msg_id:
                self._edit_message(chat_id, live_msg_id, f"出了点问题: {e}")
            else:
                self._send_text(chat_id, f"出了点问题: {e}")

    def _delete_message(self, chat_id: str, message_id: int):
        """Delete a message (used when replacing placeholder with split messages)."""
        try:
            payload = json.dumps({
                "chat_id": chat_id, "message_id": message_id,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{self._base_url}/deleteMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    # ── DB 持久化 ──

    @staticmethod
    def _db_conn(db_path: str):
        """Connect with WAL mode if possible, fallback to default."""
        import sqlite3
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # WAL needs write access to create -wal/-shm files
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @classmethod
    def _save_message(cls, db_path: str, chat_id: str, role: str, content: str):
        """存一条消息到 DB。含硬上限保护。"""
        from datetime import datetime, timezone

        conn = TelegramChannel._db_conn(db_path)

        # 硬上限：超过 _MAX_DB_MESSAGES 则删最旧的
        count = conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ?", (chat_id,)
        ).fetchone()[0]
        if count >= ch_cfg.MAX_DB_MESSAGES:
            excess = count - ch_cfg.MAX_DB_MESSAGES + ch_cfg.DB_PRUNE_EXTRA
            conn.execute(
                "DELETE FROM chat_messages WHERE id IN "
                "(SELECT id FROM chat_messages WHERE chat_id = ? ORDER BY id ASC LIMIT ?)",
                (chat_id, excess),
            )

        conn.execute(
            "INSERT INTO chat_messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (chat_id, role, content, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _load_recent(db_path: str, chat_id: str, limit: int = 20) -> list[dict]:
        """从 DB 加载最近 N 轮对话。"""
        conn = TelegramChannel._db_conn(db_path)
        rows = conn.execute(
            "SELECT role, content FROM chat_messages "
            "WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        conn.close()
        # DB 返回的是倒序，翻转回来
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    @staticmethod
    def _load_memory(db_path: str, chat_id: str) -> str:
        """加载摘要记忆。"""
        conn = TelegramChannel._db_conn(db_path)
        row = conn.execute(
            "SELECT summary FROM chat_memory WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        conn.close()
        return row[0] if row else ""

    @staticmethod
    def _save_memory(db_path: str, chat_id: str, summary: str):
        """保存摘要记忆。"""
        from datetime import datetime, timezone
        conn = TelegramChannel._db_conn(db_path)
        conn.execute(
            "INSERT INTO chat_memory (chat_id, summary, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET summary = ?, updated_at = ?",
            (chat_id, summary, datetime.now(timezone.utc).isoformat(),
             summary, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _count_messages(db_path: str, chat_id: str) -> int:
        """统计消息总数。"""
        conn = TelegramChannel._db_conn(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ?", (chat_id,)
        ).fetchone()[0]
        conn.close()
        return count

    def _build_context(self, db_path: str, chat_id: str) -> list[dict]:
        """构建对话上下文：摘要记忆 + 最近消息。"""
        messages = []

        # 加载摘要记忆，作为第一条 user 消息注入
        memory = self._load_memory(db_path, chat_id)
        if memory:
            messages.append({
                "role": "user",
                "content": f"[系统：以下是之前对话的摘要记忆，帮你回忆上下文]\n{memory}",
            })
            messages.append({
                "role": "assistant",
                "content": "明白，我记得这些。继续。",
            })

        # 加载最近对话
        recent = self._load_recent(db_path, chat_id, ch_cfg.RECENT_TURNS)
        messages.extend(recent)

        return messages

    def _maybe_summarize(self, db_path: str, chat_id: str, client):
        """消息数超过阈值时，压缩旧消息为摘要记忆。"""
        total = self._count_messages(db_path, chat_id)
        if total <= ch_cfg.SUMMARIZE_THRESHOLD:
            return

        # 加载所有超出最近 N 条的旧消息
        conn = TelegramChannel._db_conn(db_path)
        rows = conn.execute(
            "SELECT role, content FROM chat_messages "
            "WHERE chat_id = ? ORDER BY id ASC",
            (chat_id,),
        ).fetchall()
        conn.close()

        # 保留最近 _RECENT_TURNS 条，压缩之前的
        old_messages = rows[:-ch_cfg.RECENT_TURNS]
        if len(old_messages) < ch_cfg.SUMMARIZE_MIN_MESSAGES:
            return  # 不值得压缩

        # 加载现有记忆
        existing_memory = self._load_memory(db_path, chat_id)

        # 构建压缩 prompt
        conversation_text = "\n".join(
            f"[{r[0]}] {r[1][:200]}" for r in old_messages
        )

        compress_prompt = (
            "你是 Orchestrator 的记忆管理器。把以下对话历史压缩成简洁的摘要记忆，"
            "保留关键信息：主人的偏好、做过的决定、提到的项目/问题、重要上下文。"
            f"丢弃闲聊和重复内容。用中文，不超过 {ch_cfg.SUMMARIZE_MAX_CHARS} 字。\n\n"
        )
        if existing_memory:
            compress_prompt += f"现有记忆：\n{existing_memory}\n\n请将以下新对话合并进现有记忆：\n\n"
        compress_prompt += conversation_text

        try:
            response = client.messages.create(
                model=ch_cfg.CHAT_MODEL,
                max_tokens=ch_cfg.SUMMARIZE_MAX_TOKENS,
                messages=[{"role": "user", "content": compress_prompt}],
            )
            new_memory = next(
                (b.text for b in response.content if b.type == "text"), ""
            ).strip()

            if new_memory:
                self._save_memory(db_path, chat_id, new_memory)

                # 删除已压缩的旧消息
                conn = TelegramChannel._db_conn(db_path)
                # 保留最近 _RECENT_TURNS 条
                conn.execute(
                    "DELETE FROM chat_messages WHERE chat_id = ? AND id NOT IN "
                    "(SELECT id FROM chat_messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?)",
                    (chat_id, chat_id, ch_cfg.RECENT_TURNS),
                )
                conn.commit()
                conn.close()

                log.info(f"telegram: summarized {len(old_messages)} messages for chat {chat_id}")

        except Exception as e:
            log.warning(f"telegram: summarize failed: {e}")

    def _execute_tool(self, tool_name: str, tool_input: dict, chat_id: str = "") -> str:
        """Execute tool call with permission check."""
        if chat_id and not ch_cfg.user_can(chat_id, tool_name):
            role = ch_cfg.ALLOWED_USERS.get(chat_id, "unknown")
            return f"Permission denied: {role} role cannot use {tool_name}"
        if tool_name == "dispatch_task":
            return self._tool_dispatch_task(tool_input)
        elif tool_name == "query_status":
            return self._tool_query_status(tool_input)
        elif tool_name == "read_file":
            return self._tool_read_file(tool_input)
        return f"Unknown tool: {tool_name}"

    @staticmethod
    def _tool_read_file(params: dict) -> str:
        """读取本地文件。"""
        file_path = params.get("path", "")
        max_chars = params.get("max_chars", ch_cfg.MAX_FILE_READ_CHARS)

        if not file_path:
            return "path 不能为空"

        # 安全检查：白名单路径前缀
        allowed_prefixes = [p.replace("\\", "/") for p in ch_cfg.READ_ALLOW_PATHS]
        clean_path = file_path.replace("\\", "/")
        if not any(clean_path.startswith(p) for p in allowed_prefixes):
            return f"安全限制：路径不在白名单中"

        # Docker 内路径映射回本地 repo root
        repo_root = Path(__file__).resolve().parent.parent.parent
        if clean_path.startswith("/orchestrator"):
            local_path = repo_root / clean_path[len("/orchestrator/"):]
        elif clean_path.startswith("/git-repos"):
            local_path = Path("D:/Users/Administrator/Documents/GitHub") / clean_path[len("/git-repos/"):]
        else:
            local_path = Path(file_path)

        try:
            if not local_path.exists():
                return f"文件不存在: {file_path}"
            if local_path.stat().st_size > ch_cfg.MAX_FILE_READ_BYTES:
                return f"文件过大 ({local_path.stat().st_size} bytes)，拒绝读取"

            content = local_path.read_text(encoding="utf-8", errors="replace")
            if len(content) > max_chars:
                return content[:max_chars] + f"\n\n[...已截取前 {max_chars} 字符，共 {len(content)} 字符]"
            return content

        except Exception as e:
            return f"读取失败: {e}"

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
            predefined = set(ch_cfg.PREDEFINED_SCENARIOS)
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
                    f"FROM tasks ORDER BY created_at DESC LIMIT {ch_cfg.TASKS_DISPLAY_LIMIT}"
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
