"""
Telegram Channel — Bot API 适配器。

出站：ChannelMessage → sendMessage API
入站：Long polling getUpdates → 命令解析 → Event Bus
对话：Claude API（带 SOUL 人格）→ 回复
多媒体：收发图片、语音、文件、视频、贴纸。

对话/DB/工具逻辑复用 src.channels.chat 公共层。
零外部依赖，纯 urllib。
"""
import json
import logging
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

from src.channels.base import Channel
from src.channels import config as ch_cfg
from src.channels import chat as chat_engine
from src.channels.media import MediaType

from src.channels.telegram.tg_api import TelegramAPI
from src.channels.telegram.sender import TelegramSender, PRIORITY_LEVELS
from src.channels.telegram.handler import TelegramHandler

log = logging.getLogger(__name__)

# Telegram 平台规则
_PLATFORM_RULES = (
    "# Platform: Telegram (HTML mode)\n"
    "- Use <b>bold</b> and <code>code</code>. No Markdown syntax.\n"
    "- No Markdown headings (#). No emoji.\n"
    "- Max message length: 4096 chars. Split longer content into multiple messages.\n"
    "- Code blocks use <pre><code class=\"language-xxx\">...</code></pre>.\n"
    "- Inline links: <a href=\"url\">text</a>.\n"
    "- NEVER fabricate image/file URLs. Only use real, accessible URLs.\n"
    "\n"
    "## Image modes (pick ONE per message, or omit for plain text):\n"
    "1. <photo>URL</photo>  — Send as native photo (best for sharing images).\n"
    "   Text outside the tag becomes the caption (max 1024 chars).\n"
    "2. <preview>URL</preview>  — Large link-preview above text (articles, dashboards).\n"
    "3. <thumb>URL</thumb>  — Small link-preview below text (subtle reference).\n"
)

# Telegram 平台能力声明（供外部模块查询）
PLATFORM_CAPABILITIES = {
    "markdown": False,
    "html": True,
    "images": True,
    "voice": True,
    "max_message_length": 4096,
    "code_blocks": True,
}


class TelegramChannel(TelegramSender, TelegramHandler, TelegramAPI, Channel):
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
        self._last_msg_time: dict[str, float] = {}
        self._system_prompt: Optional[str] = None

        # message_id 去重缓存 — TTL 60s，防止同一消息触发多次处理
        self._msg_id_cache: dict[int, float] = {}  # message_id → timestamp
        self._msg_id_ttl = 60.0
        self._dedup_count = 0  # 累计去重次数

        # 消息防抖 — 连发多条消息时攒一批再处理
        self._pending: dict[str, dict] = {}  # chat_id → {texts, attachments, timer, start_ts}
        self._pending_lock = threading.Lock()
        self._debounce_sec = 8.0
        self._debounce_max = 45.0

    # ── 入站 ────────────────────────────────────────────────────────────────

    def start(self):
        if not self.chat_id:
            log.info("telegram: no chat_id, inbound commands disabled")
            return
        self._stop_event.clear()
        self._polling_thread = threading.Thread(
            target=self._poll_loop, name="telegram-poll", daemon=True,
        )
        self._polling_thread.start()
        log.info("telegram: polling started")

    def stop(self):
        self._stop_event.set()
        if self._polling_thread:
            self._polling_thread.join(timeout=5)
            self._polling_thread = None

    def _purge_msg_id_cache(self, now: float = None):
        """Remove expired entries from message_id dedup cache."""
        now = now or time.time()
        expired = [mid for mid, ts in self._msg_id_cache.items()
                   if now - ts >= self._msg_id_ttl]
        for mid in expired:
            del self._msg_id_cache[mid]

    def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
            except Exception as e:
                log.warning(f"telegram: poll error: {e}")
            self._stop_event.wait(timeout=2)

    def _get_updates(self) -> list:
        params = f"offset={self._last_update_id + 1}&timeout={ch_cfg.POLL_TIMEOUT}&allowed_updates=[\"message\",\"callback_query\",\"message_reaction\"]"
        req = urllib.request.Request(
            f"{self._base_url}/getUpdates?{params}", method="GET",
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
        self._last_update_id = update.get("update_id", self._last_update_id)

        # Handle inline keyboard callback (approval buttons)
        callback = update.get("callback_query")
        if callback:
            self._handle_callback_query(callback)
            return

        # Handle user reactions on messages
        reaction = update.get("message_reaction")
        if reaction:
            self._handle_reaction(reaction)
            return

        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        if not chat_id:
            return

        # 鉴权
        if ch_cfg.ALLOWED_USERS:
            if not ch_cfg.user_can(chat_id, "chat"):
                log.info("telegram: unauthorized chat_id=%s (ALLOWED_USERS mode)", chat_id)
                return
        elif self.chat_id and chat_id != self.chat_id:
            log.info("telegram: unauthorized chat_id=%s (legacy mode, expected %s)", chat_id, self.chat_id)
            return

        # 连续消息检测 → burst 时强制走 debounce 合并，不丢弃
        now = time.time()
        is_burst = (now - self._last_msg_time.get(chat_id, 0)) < ch_cfg.BURST_WINDOW
        self._last_msg_time[chat_id] = now

        text = (message.get("text") or message.get("caption") or "").strip()
        msg_id = message.get("message_id")  # 用于 reaction

        # ── message_id 去重 ──────────────────────────────────────────────
        if msg_id is not None:
            if msg_id in self._msg_id_cache and (now - self._msg_id_cache[msg_id]) < self._msg_id_ttl:
                self._dedup_count += 1
                log.info(f"telegram: deduplicated message_id={msg_id} "
                         f"(deduplicated_count={self._dedup_count})")
                return
            self._msg_id_cache[msg_id] = now
            # 惰性清理过期条目
            self._purge_msg_id_cache(now)

        attachments = []

        if "photo" in message:
            photo = message["photo"][-1]  # largest size
            att = self._download_tg_file(photo["file_id"], MediaType.IMAGE, "image/jpeg")
            if att:
                attachments.append(att)

        if "voice" in message:
            att = self._download_tg_file(
                message["voice"]["file_id"], MediaType.VOICE, "audio/ogg",
                duration_ms=message["voice"].get("duration", 0) * 1000,
            )
            if att:
                att.text = self._transcribe(att.local_path)
                attachments.append(att)

        if "audio" in message:
            att = self._download_tg_file(
                message["audio"]["file_id"], MediaType.VOICE,
                message["audio"].get("mime_type", "audio/mpeg"),
                duration_ms=message["audio"].get("duration", 0) * 1000,
            )
            if att:
                att.text = self._transcribe(att.local_path)
                attachments.append(att)

        if "document" in message:
            doc = message["document"]
            att = self._download_tg_file(
                doc["file_id"], MediaType.FILE,
                doc.get("mime_type", "application/octet-stream"),
            )
            if att:
                att.file_name = doc.get("file_name", "")
                attachments.append(att)

        if "sticker" in message:
            att = self._download_tg_file(
                message["sticker"]["file_id"], MediaType.IMAGE, "image/webp",
            )
            if att:
                attachments.append(att)

        if "video" in message:
            vid = message["video"]
            att = self._download_tg_file(
                vid["file_id"], MediaType.VIDEO, "video/mp4",
                duration_ms=vid.get("duration", 0) * 1000,
            )
            if att:
                attachments.append(att)

        if "video_note" in message:
            vn = message["video_note"]
            att = self._download_tg_file(
                vn["file_id"], MediaType.VIDEO, "video/mp4",
                duration_ms=vn.get("duration", 0) * 1000,
            )
            if att:
                attachments.append(att)

        if not text and not attachments:
            return

        # Commands bypass debounce
        if text and text.startswith("/"):
            self._send_typing(chat_id)
            chat_engine.handle_command(text, chat_id, self._send_text, "telegram")
            return

        # Short text without media + no pending buffer → fire immediately
        has_media = bool(attachments)
        is_long = len(text) > ch_cfg.LONG_MSG_THRESHOLD
        with self._pending_lock:
            has_pending = chat_id in self._pending

        if not has_media and not has_pending and not is_long and not is_burst:
            self._process_message(chat_id, text, attachments, msg_id=msg_id)
            return

        # Has media or existing pending buffer → debounce
        now = time.time()
        with self._pending_lock:
            if chat_id in self._pending:
                buf = self._pending[chat_id]
                if text:
                    buf["texts"].append(text)
                buf["attachments"].extend(attachments)
                if buf.get("timer"):
                    buf["timer"].cancel()
                elapsed = now - buf.get("start_ts", now)
                if elapsed >= self._debounce_max:
                    self._pending_lock.release()
                    try:
                        self._flush_pending(chat_id)
                    finally:
                        self._pending_lock.acquire()
                    return
            else:
                self._pending[chat_id] = {
                    "texts": [text] if text else [],
                    "attachments": attachments,
                    "timer": None,
                    "start_ts": now,
                    "msg_id": msg_id,
                }
            buf = self._pending[chat_id]
            buf["timer"] = threading.Timer(
                self._debounce_sec, self._flush_pending, args=(chat_id,)
            )
            buf["timer"].start()

    # ── 对话 ────────────────────────────────────────────────────────────────

    def _do_chat_with_streaming(self, chat_id: str, text: str,
                                original_text: str = "",
                                media: list | None = None,
                                msg_id: int | None = None,
                                cancelled_fn=None):
        """Core chat logic with typing indicator + R49 BlockStreamer.

        Runs synchronously — caller is responsible for threading.
        """
        # 构建 react 回调
        def react_fn(emoji: str):
            if msg_id:
                self._set_reaction(chat_id, msg_id, emoji)

        typing_stop = self._keep_typing(chat_id)

        # R49: BlockStreamer for progressive delivery
        streamer = None
        on_chunk = None
        if ch_cfg.BLOCK_STREAMING == "on":
            from src.channels.block_streamer import BlockStreamer
            streamer = BlockStreamer(
                send_fn=lambda txt: self._send_text(chat_id, txt),
                min_chars=ch_cfg.BLOCK_STREAMING_MIN_CHARS,
                max_chars=ch_cfg.BLOCK_STREAMING_MAX_CHARS,
                idle_s=ch_cfg.BLOCK_STREAMING_IDLE_S,
                lookahead=ch_cfg.BLOCK_STREAMING_LOOKAHEAD,  # R52: overlap buffer
            )
            on_chunk = streamer.push

        try:
            chat_engine.do_chat(
                chat_id, text, original_text,
                self._get_system_prompt(),
                lambda cid, txt, **kw: self._reply_media(cid, txt, **kw),
                "telegram",
                permission_check_fn=lambda cid, tool: ch_cfg.user_can(cid, tool),
                media=media,
                react_fn=react_fn,
                on_chunk=on_chunk,
                cancelled_fn=cancelled_fn,
            )
            # R49: Flush any remaining buffered text
            if streamer:
                streamer.flush_sync()
        finally:
            typing_stop.set()

    def _start_chat_sync(self, chat_id: str, text: str, original_text: str = "",
                         media: list | None = None,
                         msg_id: int | None = None,
                         cancelled_fn=None):
        """Synchronous chat — called from dispatch thread (R49).

        Used by _process_message which manages its own threading + lock lifecycle.
        """
        self._do_chat_with_streaming(chat_id, text, original_text, media, msg_id, cancelled_fn)

    def _start_chat(self, chat_id: str, text: str, original_text: str = "",
                    media: list | None = None,
                    msg_id: int | None = None,
                    cancelled_fn=None):
        """Async chat — spawns a thread. Used for non-dispatch paths (reactions, etc)."""
        def _run():
            self._do_chat_with_streaming(chat_id, text, original_text, media, msg_id, cancelled_fn)
        threading.Thread(target=_run, name="tg-chat", daemon=True).start()

    # ── 平台提示 ──────────────────────────────────────────────────────────

    def get_platform_hints(self) -> str:
        """返回 Telegram 平台规则提示词。"""
        return _PLATFORM_RULES

    # ── 系统提示词 ──────────────────────────────────────────────────────────

    def _get_system_prompt(self) -> str:
        if self._system_prompt is not None:
            return self._system_prompt

        prompt = chat_engine.build_system_prompt(_PLATFORM_RULES)

        # Telegram 专属：项目目录树
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        try:
            tree = self._scan_project_tree(repo_root, max_depth=1)
            if tree:
                prompt += f"\n# Project Layout\n```\n{tree}```\n"
        except Exception:
            pass

        self._system_prompt = prompt
        return self._system_prompt

    @staticmethod
    def _scan_project_tree(repo_root: Path, max_depth: int = 2) -> str:
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
            for d in dirs:
                lines.append(f"{prefix}{d.name}/")
                _walk(d, prefix + "  ", depth + 1)
            if depth <= 1:
                for f in files[:5]:
                    lines.append(f"{prefix}{f.name}")
                if len(files) > 5:
                    lines.append(f"{prefix}... (+{len(files)-5} files)")

        _walk(repo_root, "  ", 0)
        return "\n".join(lines[:60]) + "\n"
