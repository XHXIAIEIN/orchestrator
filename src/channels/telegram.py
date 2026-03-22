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

        # 频率限制
        now = time.time()
        last = self._last_msg_time.get(chat_id, 0)
        if now - last < self._RATE_LIMIT_WINDOW:
            return  # 静默丢弃，不回复（防刷）
        self._last_msg_time[chat_id] = now

        # 解析命令 vs 对话
        if text.startswith("/"):
            self._handle_command(chat_id, text)
        else:
            # 长消息 → 存文件，传路径
            if len(text) > self._LONG_MSG_THRESHOLD:
                file_path, char_count = self._save_to_inbox(text)
                preview = text[:80].replace("\n", " ")
                ref = f'[用户发送了长消息 ({char_count}字)，已保存到 {file_path}，预览: "{preview}..."]'
                self._handle_chat(chat_id, ref, original_text=text)
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

    # ── 对话：Claude API + DB 持久化 + 摘要记忆 ──

    _RECENT_TURNS = 20         # 最近 N 轮完整对话
    _SUMMARIZE_THRESHOLD = 30  # 超过 N 条消息时触发摘要压缩
    _MAX_DB_MESSAGES = 500     # 单个 chat 最多存 500 条（硬上限，防撑爆 DB）
    _RATE_LIMIT_WINDOW = 2     # 秒，同一 chat 的最小消息间隔（防刷）
    _TG_MSG_LIMIT = 4096       # Telegram 单条消息字符上限
    _LONG_MSG_THRESHOLD = 500  # 超过此长度的消息存文件，LLM 拿路径
    _last_msg_time: dict[str, float] = {}  # chat_id → last message timestamp

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
        {
            "name": "read_file",
            "description": (
                "读取本地文件内容。用于读取用户发送的长消息（已保存为文件）。"
                "路径通常类似 /orchestrator/tmp/chat-inbox/xxx.txt。"
                "也可以读取项目中的任何文件来回答用户问题。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "最多读取的字符数，默认 8000",
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

    def _do_chat(self, chat_id: str, text: str, original_text: str = ""):
        """在后台线程执行对话（避免阻塞 polling）。"""
        try:
            import sqlite3
            from src.core.config import get_anthropic_client

            repo_root = Path(__file__).resolve().parent.parent.parent
            db_path = str(repo_root / "data" / "events.db")

            # 存入用户消息（DB 存 LLM 看到的引用，不存大段原文）
            self._save_message(db_path, chat_id, "user", text)

            # 构建上下文：摘要记忆 + 最近对话
            messages = self._build_context(db_path, chat_id)

            client = get_anthropic_client()

            # 对话循环：处理 tool use
            max_rounds = 3
            final_reply = ""

            for _ in range(max_rounds):
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1024,
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
                    reply = "\n".join(text_parts)
                    self._send_text(chat_id, reply)
                    final_reply = reply

                if not tool_calls:
                    break

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

            # 存入 assistant 回复
            if final_reply:
                self._save_message(db_path, chat_id, "assistant", final_reply)

            # 检查是否需要摘要压缩
            self._maybe_summarize(db_path, chat_id, client)

        except Exception as e:
            log.error(f"telegram: chat failed: {e}")
            self._send_text(chat_id, f"[ERR] 对话失败: {e}")

    # ── DB 持久化 ──

    @classmethod
    def _save_message(cls, db_path: str, chat_id: str, role: str, content: str):
        """存一条消息到 DB。含硬上限保护。"""
        import sqlite3
        from datetime import datetime, timezone

        conn = sqlite3.connect(db_path)

        # 硬上限：超过 _MAX_DB_MESSAGES 则删最旧的
        count = conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ?", (chat_id,)
        ).fetchone()[0]
        if count >= cls._MAX_DB_MESSAGES:
            excess = count - cls._MAX_DB_MESSAGES + 10  # 多删 10 条留余量
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
        import sqlite3
        conn = sqlite3.connect(db_path)
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
        import sqlite3
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT summary FROM chat_memory WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        conn.close()
        return row[0] if row else ""

    @staticmethod
    def _save_memory(db_path: str, chat_id: str, summary: str):
        """保存摘要记忆。"""
        import sqlite3
        from datetime import datetime, timezone
        conn = sqlite3.connect(db_path)
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
        import sqlite3
        conn = sqlite3.connect(db_path)
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
        recent = self._load_recent(db_path, chat_id, self._RECENT_TURNS)
        messages.extend(recent)

        return messages

    def _maybe_summarize(self, db_path: str, chat_id: str, client):
        """消息数超过阈值时，压缩旧消息为摘要记忆。"""
        total = self._count_messages(db_path, chat_id)
        if total <= self._SUMMARIZE_THRESHOLD:
            return

        # 加载所有超出最近 N 条的旧消息
        import sqlite3
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT role, content FROM chat_messages "
            "WHERE chat_id = ? ORDER BY id ASC",
            (chat_id,),
        ).fetchall()
        conn.close()

        # 保留最近 _RECENT_TURNS 条，压缩之前的
        old_messages = rows[:-self._RECENT_TURNS]
        if len(old_messages) < 10:
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
            "丢弃闲聊和重复内容。用中文，不超过 500 字。\n\n"
        )
        if existing_memory:
            compress_prompt += f"现有记忆：\n{existing_memory}\n\n请将以下新对话合并进现有记忆：\n\n"
        compress_prompt += conversation_text

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                messages=[{"role": "user", "content": compress_prompt}],
            )
            new_memory = next(
                (b.text for b in response.content if b.type == "text"), ""
            ).strip()

            if new_memory:
                self._save_memory(db_path, chat_id, new_memory)

                # 删除已压缩的旧消息
                import sqlite3
                conn = sqlite3.connect(db_path)
                # 保留最近 _RECENT_TURNS 条
                conn.execute(
                    "DELETE FROM chat_messages WHERE chat_id = ? AND id NOT IN "
                    "(SELECT id FROM chat_messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?)",
                    (chat_id, chat_id, self._RECENT_TURNS),
                )
                conn.commit()
                conn.close()

                log.info(f"telegram: summarized {len(old_messages)} messages for chat {chat_id}")

        except Exception as e:
            log.warning(f"telegram: summarize failed: {e}")

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """执行 tool call，返回结果字符串。"""
        if tool_name == "dispatch_task":
            return self._tool_dispatch_task(tool_input)
        elif tool_name == "query_status":
            return self._tool_query_status(tool_input)
        elif tool_name == "read_file":
            return self._tool_read_file(tool_input)
        return f"未知工具: {tool_name}"

    @staticmethod
    def _tool_read_file(params: dict) -> str:
        """读取本地文件。"""
        file_path = params.get("path", "")
        max_chars = params.get("max_chars", 8000)

        if not file_path:
            return "path 不能为空"

        # 安全检查：白名单路径前缀（从环境变量读取，逗号分隔）
        default_prefixes = "/orchestrator,/git-repos"
        allowed_str = os.environ.get("CHANNEL_READ_ALLOW_PATHS", default_prefixes)
        allowed_prefixes = [p.strip().replace("\\", "/") for p in allowed_str.split(",") if p.strip()]
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
            if local_path.stat().st_size > 1_000_000:  # 1MB 硬上限
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
