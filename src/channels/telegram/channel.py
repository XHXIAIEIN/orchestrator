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
import os
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from src.channels.base import Channel, ChannelMessage
from src.channels import config as ch_cfg
from src.channels import chat as chat_engine
from src.channels.media import MediaAttachment, MediaType, download_url, guess_mime

log = logging.getLogger(__name__)

PRIORITY_LEVELS = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}

# Telegram 平台规则
_PLATFORM_RULES = (
    "# Platform: Telegram\n"
    "- *bold* and `code` OK. No Markdown headings. No emoji.\n"
)


class TelegramChannel(Channel):
    """Telegram Bot 适配器。"""

    name = "telegram"
    _TG_MSG_LIMIT = 4096

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

        # 消息防抖 — 连发多条消息时攒一批再处理
        self._pending: dict[str, dict] = {}  # chat_id → {texts, attachments, timer, start_ts}
        self._pending_lock = threading.Lock()
        self._debounce_sec = 8.0
        self._debounce_max = 45.0

    # ── 出站 ────────────────────────────────────────────────────────────────

    def send(self, message: ChannelMessage) -> bool:
        msg_priority = PRIORITY_LEVELS.get(message.priority, 2)
        if msg_priority > self.min_priority:
            return False

        targets = ch_cfg.get_all_chat_ids() if ch_cfg.ALLOWED_USERS else ([self.chat_id] if self.chat_id else [])
        if not targets:
            log.warning("telegram: no recipients configured, skip send")
            return False

        ok = True
        for target_id in targets:
            role = ch_cfg.ALLOWED_USERS.get(target_id, "admin")
            if role == "viewer" and msg_priority > 1:
                continue
            ok = self._send_text(target_id, message.text) and ok
        return ok

    def _send_text(self, chat_id: str, text: str) -> bool:
        chunks = self._split_message(text)
        ok = True
        for chunk in chunks:
            sent = self._send_raw(chat_id, chunk, parse_mode="Markdown")
            if not sent:
                sent = self._send_raw(chat_id, chunk, parse_mode=None)
            ok = ok and sent
        return ok

    def _split_message(self, text: str) -> list[str]:
        limit = self._TG_MSG_LIMIT
        if len(text) <= limit:
            return [text]
        chunks = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            split_at = text.rfind("\n", 0, limit)
            if split_at <= 0:
                split_at = text.rfind(" ", 0, limit)
            if split_at <= 0:
                split_at = limit
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        return chunks

    def _send_raw(self, chat_id: str, text: str, parse_mode: str = None) -> bool:
        body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
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

    # ── TG API 工具方法 ─────────────────────────────────────────────────────

    def _tg_api(self, method: str, params: dict) -> dict:
        """Call Telegram Bot API."""
        payload = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/{method}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=ch_cfg.SEND_TIMEOUT)
            return json.loads(resp.read())
        except Exception as e:
            log.warning(f"telegram: {method} failed: {e}")
            return {}

    def _tg_get_file_url(self, file_id: str) -> str:
        """Get download URL for a Telegram file."""
        resp = self._tg_api("getFile", {"file_id": file_id})
        if resp and resp.get("ok"):
            path = resp["result"]["file_path"]
            return f"https://api.telegram.org/file/bot{self.token}/{path}"
        return ""

    # ── 出站多媒体 ──────────────────────────────────────────────────────────

    def _send_photo(self, chat_id: str, photo_path: str, caption: str = "") -> bool:
        return self._send_multipart(chat_id, "sendPhoto", "photo", photo_path, caption)

    def _send_document(self, chat_id: str, doc_path: str, caption: str = "") -> bool:
        return self._send_multipart(chat_id, "sendDocument", "document", doc_path, caption)

    def _send_voice(self, chat_id: str, voice_path: str, caption: str = "") -> bool:
        return self._send_multipart(chat_id, "sendVoice", "voice", voice_path, caption)

    def _send_video(self, chat_id: str, video_path: str, caption: str = "") -> bool:
        return self._send_multipart(chat_id, "sendVideo", "video", video_path, caption)

    def _send_sticker(self, chat_id: str, sticker_path: str) -> bool:
        return self._send_multipart(chat_id, "sendSticker", "sticker", sticker_path)

    def _send_multipart(self, chat_id: str, method: str, field_name: str,
                        file_path: str, caption: str = "") -> bool:
        """Send file via multipart/form-data to Telegram."""
        import mimetypes
        boundary = "----OrchestratorBoundary"
        filename = os.path.basename(file_path)
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        body = bytearray()
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode()
        if caption:
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode()
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
        body += f"Content-Type: {mime}\r\n\r\n".encode()
        with open(file_path, "rb") as f:
            body += f.read()
        body += f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{self._base_url}/{method}",
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read())
            return result.get("ok", False)
        except Exception as e:
            log.warning(f"telegram: {method} failed: {e}")
            return False

    def _reply_media(self, chat_id: str, text: str,
                     media_path: str = "", media_type: str = "") -> bool:
        """Reply with media file if provided, otherwise plain text."""
        if media_path and os.path.exists(media_path):
            mime = media_type or guess_mime(media_path)
            caption = text[:1024] if text else ""
            if mime.startswith("image/"):
                return self._send_photo(chat_id, media_path, caption)
            elif mime.startswith("video/"):
                return self._send_video(chat_id, media_path, caption)
            elif mime.startswith("audio/"):
                return self._send_voice(chat_id, media_path, caption)
            else:
                return self._send_document(chat_id, media_path, caption)
        return self._send_text(chat_id, text)

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

    def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
            except Exception as e:
                log.debug(f"telegram: poll error: {e}")
            self._stop_event.wait(timeout=2)

    def _get_updates(self) -> list:
        params = f"offset={self._last_update_id + 1}&timeout={ch_cfg.POLL_TIMEOUT}&allowed_updates=[\"message\"]"
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
        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        if not chat_id:
            return

        # 鉴权
        if ch_cfg.ALLOWED_USERS:
            if not ch_cfg.user_can(chat_id, "chat"):
                return
        elif self.chat_id and chat_id != self.chat_id:
            return

        # 频率限制
        now = time.time()
        if now - self._last_msg_time.get(chat_id, 0) < ch_cfg.RATE_LIMIT_WINDOW:
            return
        self._last_msg_time[chat_id] = now

        text = (message.get("text") or message.get("caption") or "").strip()
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
                attachments.append(att)

        if "audio" in message:
            att = self._download_tg_file(
                message["audio"]["file_id"], MediaType.VOICE,
                message["audio"].get("mime_type", "audio/mpeg"),
                duration_ms=message["audio"].get("duration", 0) * 1000,
            )
            if att:
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

        if not has_media and not has_pending and not is_long:
            self._process_message(chat_id, text, attachments)
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
                }
            buf = self._pending[chat_id]
            buf["timer"] = threading.Timer(
                self._debounce_sec, self._flush_pending, args=(chat_id,)
            )
            buf["timer"].start()

    def _flush_pending(self, chat_id: str):
        """Debounce timer expired — process accumulated messages as one batch."""
        with self._pending_lock:
            buf = self._pending.pop(chat_id, None)
        if not buf:
            return
        texts = buf["texts"]
        attachments = buf["attachments"]
        text = "\n".join(texts) if texts else ""
        self._process_message(chat_id, text, attachments)

    def _process_message(self, chat_id: str, text: str,
                         attachments: list[MediaAttachment]):
        """Route a (possibly batched) message to chat engine."""
        if not text and attachments:
            text = self._describe_media(attachments)

        if len(text) > ch_cfg.LONG_MSG_THRESHOLD:
            file_path, char_count = chat_engine.save_to_inbox(text)
            preview = text[:80].replace("\n", " ")
            ref = f'[用户发送了长消息 ({char_count}字)，已保存到 {file_path}，预览: "{preview}..."]'
            self._start_chat(chat_id, ref, original_text=text, media=attachments)
        else:
            self._start_chat(chat_id, text, media=attachments)

    # ── 入站多媒体辅助 ─────────────────────────────────────────────────────

    def _download_tg_file(self, file_id: str, media_type: MediaType,
                          mime: str, duration_ms: int = 0) -> MediaAttachment | None:
        """Download a file from Telegram and wrap as MediaAttachment."""
        try:
            url = self._tg_get_file_url(file_id)
            if not url:
                return None
            local_path = download_url(url, "inbound")
            return MediaAttachment(
                media_type=media_type, local_path=local_path,
                mime_type=mime, duration_ms=duration_ms,
            )
        except Exception as e:
            log.warning(f"telegram: file download failed: {e}")
            return None

    @staticmethod
    def _describe_media(attachments: list[MediaAttachment]) -> str:
        """Generate human-readable description of attachments."""
        descs = []
        for a in attachments:
            if a.media_type == MediaType.IMAGE:
                descs.append("[用户发送了一张图片]")
            elif a.media_type == MediaType.VOICE:
                descs.append(f"[用户发送了一条语音{f': {a.text}' if a.text else ''}]")
            elif a.media_type == MediaType.FILE:
                descs.append(f"[用户发送了文件: {a.file_name or '未知'}]")
            elif a.media_type == MediaType.VIDEO:
                descs.append("[用户发送了一段视频]")
        return " ".join(descs) if descs else "[用户发送了媒体消息]"

    # ── 对话 ────────────────────────────────────────────────────────────────

    def _start_chat(self, chat_id: str, text: str, original_text: str = "",
                    media: list[MediaAttachment] | None = None):
        """启动对话线程（带 typing 指示器）。"""
        def _chat_with_typing():
            typing_stop = self._keep_typing(chat_id)
            try:
                chat_engine.do_chat(
                    chat_id, text, original_text,
                    self._get_system_prompt(),
                    lambda cid, txt, **kw: self._reply_media(cid, txt, **kw),
                    "telegram",
                    permission_check_fn=lambda cid, tool: ch_cfg.user_can(cid, tool),
                    media=media,
                )
            finally:
                typing_stop.set()

        threading.Thread(target=_chat_with_typing, name="tg-chat", daemon=True).start()

    # ── Typing 指示器 ──────────────────────────────────────────────────────

    def _send_typing(self, chat_id: str):
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

    def _keep_typing(self, chat_id: str) -> threading.Event:
        stop = threading.Event()
        def _loop():
            while not stop.is_set():
                self._send_typing(chat_id)
                stop.wait(timeout=4)
        threading.Thread(target=_loop, name="tg-typing", daemon=True).start()
        return stop

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
