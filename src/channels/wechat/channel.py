"""
微信 WeChat Channel — iLink Bot API 适配器。

出站：ChannelMessage → sendmessage API（需 context_token）
入站：Long polling getupdates → 命令解析 → Event Bus / Claude 对话

对话/DB/工具逻辑复用 src.channels.chat 公共层。
零外部依赖，纯 urllib。
"""
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from typing import Optional

from src.channels.base import Channel, ChannelMessage
from src.channels import config as ch_cfg
from src.channels import chat as chat_engine
from src.channels.media import MediaAttachment, MediaType, save_media_buffer, guess_mime
from src.channels.wechat.api import (
    DEFAULT_BASE_URL,
    get_updates,
    send_message,
    send_typing,
    get_config,
    extract_text,
    extract_from_user,
    extract_media_items,
    send_image,
    send_file,
    send_video,
    set_context_token,
    get_context_token,
    get_all_context_users,
    ITEM_IMAGE, ITEM_VOICE, ITEM_FILE, ITEM_VIDEO,
)
from src.channels.wechat.cdn import (
    cdn_download_and_decrypt,
    cdn_download_plain,
    upload_media_file,
    CDN_BASE_URL,
)

log = logging.getLogger(__name__)

PRIORITY_LEVELS = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
WECHAT_MSG_LIMIT = 4000

# WeChat 平台规则（注入系统提示词）
_PLATFORM_RULES = (
    "# Platform: WeChat\n"
    "- Plain text only. No Markdown, no emoji. WeChat doesn't render formatting.\n"
)


class WeChatChannel(Channel):
    """微信 iLink Bot 适配器。"""

    name = "wechat"

    def __init__(self, bot_token: str, base_url: str = DEFAULT_BASE_URL,
                 min_priority: str = "HIGH",
                 allowed_users: str = ""):
        self.bot_token = bot_token
        self.base_url = base_url or DEFAULT_BASE_URL
        self.min_priority = PRIORITY_LEVELS.get(min_priority.upper(), 1)
        self.enabled = True

        # 用户白名单
        self._allowed_users: dict[str, str] = {}
        if allowed_users:
            for pair in allowed_users.split(","):
                pair = pair.strip()
                if ":" in pair:
                    uid, role = pair.split(":", 1)
                    self._allowed_users[uid.strip()] = role.strip()
                elif pair:
                    self._allowed_users[pair] = "admin"

        self._polling_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._sync_cursor = ""
        self._consecutive_failures = 0
        self._last_msg_time: dict[str, float] = {}

        # 系统提示词（懒加载）
        self._system_prompt: Optional[str] = None

        # 多媒体 / typing
        self._typing_tickets: dict[str, str] = {}  # user_id → ticket
        self._cdn_base_url = os.environ.get("WECHAT_CDN_BASE_URL", CDN_BASE_URL)

        # 消息防抖 — 连发多条消息时攒一批再处理
        self._pending: dict[str, dict] = {}  # user_id → {texts, attachments, timer, start_ts}
        self._pending_lock = threading.Lock()
        self._debounce_sec = 5.0   # 每条消息重置窗口
        self._debounce_max = 20.0  # 最大等待上限

    # ── 出站 ────────────────────────────────────────────────────────────────

    def send(self, message: ChannelMessage) -> bool:
        msg_priority = PRIORITY_LEVELS.get(message.priority, 2)
        if msg_priority > self.min_priority:
            return False

        users_with_token = get_all_context_users()
        if not users_with_token:
            log.debug("wechat: no users with context_token, skip broadcast")
            return False

        plain_text = _strip_markdown(message.text)
        ok = True
        for user_id in users_with_token:
            if self._allowed_users:
                role = self._allowed_users.get(user_id, "")
                if not role:
                    continue
                if role == "viewer" and msg_priority > 1:
                    continue

            ctx_token = get_context_token(user_id)
            if not ctx_token:
                continue

            try:
                for chunk in _split_message(plain_text):
                    send_message(self.bot_token, user_id, chunk,
                                 ctx_token, self.base_url)
            except Exception as e:
                log.warning(f"wechat: send to {user_id[:16]}... failed: {e}")
                ok = False
        return ok

    # ── 入站 ────────────────────────────────────────────────────────────────

    def start(self):
        self._stop_event.clear()
        self._polling_thread = threading.Thread(
            target=self._poll_loop, name="wechat-poll", daemon=True,
        )
        self._polling_thread.start()
        log.info("wechat: polling started")

    def stop(self):
        self._stop_event.set()
        if self._polling_thread:
            self._polling_thread.join(timeout=5)
            self._polling_thread = None

    def _poll_loop(self):
        MAX_FAILURES, BACKOFF_S, RETRY_S = 3, 30, 2

        while not self._stop_event.is_set():
            try:
                resp = get_updates(self.bot_token, self._sync_cursor,
                                   self.base_url, timeout=60)

                if resp.get("errcode") == -14:
                    log.warning("wechat: session expired (errcode -14)")
                    break
                # ret=None 或 ret=0 都是正常（无新消息时 ret 可能为 null）
                ret = resp.get("ret")
                if ret is not None and ret != 0:
                    raise RuntimeError(f"getupdates ret={ret}")

                new_cursor = resp.get("get_updates_buf", "")
                if new_cursor:
                    self._sync_cursor = new_cursor

                for msg in resp.get("msgs") or []:
                    try:
                        self._handle_message(msg)
                    except Exception as e:
                        log.error(f"wechat: handle message failed: {e}")

                self._consecutive_failures = 0

            except Exception as e:
                self._consecutive_failures += 1
                log.debug(f"wechat: poll error ({self._consecutive_failures}): {e}")
                if self._consecutive_failures >= MAX_FAILURES:
                    log.warning(f"wechat: {MAX_FAILURES} failures, backing off {BACKOFF_S}s")
                    self._stop_event.wait(timeout=BACKOFF_S)
                    self._consecutive_failures = 0
                else:
                    self._stop_event.wait(timeout=RETRY_S)

    def _handle_message(self, msg: dict):
        if msg.get("message_type") != 1:
            return

        user_id = extract_from_user(msg)
        text = extract_text(msg).strip()
        ctx_token = msg.get("context_token", "")
        media_items = extract_media_items(msg)

        if not user_id:
            return
        if not text and not media_items:
            return
        if ctx_token:
            set_context_token(user_id, ctx_token)
        if self._allowed_users and user_id not in self._allowed_users:
            log.warning(f"wechat: rejected from unauthorized {user_id[:16]}...")
            return

        # Commands bypass debounce
        if text.startswith("/"):
            chat_engine.handle_command(text, user_id, self._reply_text, "wechat")
            return

        # Download media immediately (CDN links may expire)
        attachments = []
        for item in media_items:
            try:
                att = self._download_media_item(item)
                if att:
                    attachments.append(att)
            except Exception as e:
                log.warning(f"wechat: media download failed: {e}")

        log.info(f"wechat: msg from {user_id[:16]}...: {text[:50]} media={len(attachments)}")

        # Short text without media + no pending buffer → fire immediately
        has_media = bool(attachments)
        is_long = len(text) > ch_cfg.LONG_MSG_THRESHOLD
        with self._pending_lock:
            has_pending = user_id in self._pending

        if not has_media and not has_pending and not is_long:
            self._process_message(user_id, text, attachments)
            return

        # Has media or existing pending buffer → debounce
        now = time.time()
        with self._pending_lock:
            if user_id in self._pending:
                buf = self._pending[user_id]
                if text:
                    buf["texts"].append(text)
                buf["attachments"].extend(attachments)
                if buf.get("timer"):
                    buf["timer"].cancel()
                # Check max wait — if exceeded, flush now
                elapsed = now - buf.get("start_ts", now)
                if elapsed >= self._debounce_max:
                    self._pending_lock.release()
                    try:
                        self._flush_pending(user_id)
                    finally:
                        self._pending_lock.acquire()
                    return
            else:
                self._pending[user_id] = {
                    "texts": [text] if text else [],
                    "attachments": attachments,
                    "timer": None,
                    "start_ts": now,
                }
            buf = self._pending[user_id]
            buf["timer"] = threading.Timer(
                self._debounce_sec, self._flush_pending, args=(user_id,)
            )
            buf["timer"].start()

    def _flush_pending(self, user_id: str):
        """Debounce timer expired — process accumulated messages as one batch."""
        with self._pending_lock:
            buf = self._pending.pop(user_id, None)
        if not buf:
            return
        texts = buf["texts"]
        attachments = buf["attachments"]
        text = "\n".join(texts) if texts else ""
        self._process_message(user_id, text, attachments)

    def _process_message(self, user_id: str, text: str,
                         attachments: list[MediaAttachment]):
        """Route a (possibly batched) message to chat engine."""
        if not text and attachments:
            text = self._describe_media(attachments)

        if len(text) > ch_cfg.LONG_MSG_THRESHOLD:
            file_path, char_count = chat_engine.save_to_inbox(text)
            preview = text[:80].replace("\n", " ")
            ref = f'[用户发送了长消息 ({char_count}字)，已保存到 {file_path}，预览: "{preview}..."]'
            self._start_chat(user_id, ref, original_text=text, media=attachments)
        else:
            self._start_chat(user_id, text, media=attachments)

    # ── Typing indicator ──────────────────────────────────────────────────

    def _fetch_typing_ticket(self, user_id: str) -> str:
        if user_id in self._typing_tickets:
            return self._typing_tickets[user_id]
        try:
            ctx_token = get_context_token(user_id)
            resp = get_config(self.bot_token, user_id, ctx_token or "", self.base_url)
            ticket = resp.get("typing_ticket", "")
            if ticket:
                self._typing_tickets[user_id] = ticket
            return ticket
        except Exception as e:
            log.debug(f"wechat: get typing_ticket failed: {e}")
            return ""

    def _send_typing_indicator(self, user_id: str, status: int = 1):
        ticket = self._fetch_typing_ticket(user_id)
        if not ticket:
            return
        try:
            send_typing(self.bot_token, user_id, ticket, status, self.base_url)
        except Exception as e:
            log.debug(f"wechat: send_typing failed: {e}")

    def _keep_typing(self, user_id: str) -> threading.Event:
        stop = threading.Event()
        def _loop():
            while not stop.is_set():
                self._send_typing_indicator(user_id, 1)
                stop.wait(timeout=5)
            self._send_typing_indicator(user_id, 2)  # cancel
        threading.Thread(target=_loop, name="wx-typing", daemon=True).start()
        return stop

    # ── Media download ────────────────────────────────────────────────────

    def _download_media_item(self, item: dict) -> MediaAttachment | None:
        t = item.get("type", 0)

        if t == ITEM_IMAGE:
            img = item.get("image_item", {})
            media = img.get("media", {})
            eqp = media.get("encrypt_query_param", "")
            if not eqp:
                return None
            import base64 as b64mod
            aes_key_b64 = img.get("aeskey")
            if aes_key_b64:
                aes_key_b64 = b64mod.b64encode(bytes.fromhex(aes_key_b64)).decode()
            else:
                aes_key_b64 = media.get("aes_key", "")
            if aes_key_b64:
                buf = cdn_download_and_decrypt(eqp, aes_key_b64, self._cdn_base_url)
            else:
                buf = cdn_download_plain(eqp, self._cdn_base_url)
            path = save_media_buffer(buf, "image/jpeg", "inbound")
            return MediaAttachment(media_type=MediaType.IMAGE, local_path=path, mime_type="image/jpeg")

        elif t == ITEM_VOICE:
            voice = item.get("voice_item", {})
            media = voice.get("media", {})
            eqp = media.get("encrypt_query_param", "")
            aes_key = media.get("aes_key", "")
            if not eqp or not aes_key:
                return None
            silk_buf = cdn_download_and_decrypt(eqp, aes_key, self._cdn_base_url)
            wav_buf = _silk_to_wav(silk_buf)
            if wav_buf:
                path = save_media_buffer(wav_buf, "audio/wav", "inbound")
                mime = "audio/wav"
            else:
                path = save_media_buffer(silk_buf, "audio/silk", "inbound")
                mime = "audio/silk"
            return MediaAttachment(
                media_type=MediaType.VOICE, local_path=path, mime_type=mime,
                text=voice.get("text", ""), duration_ms=voice.get("playtime", 0),
            )

        elif t == ITEM_FILE:
            fi = item.get("file_item", {})
            media = fi.get("media", {})
            eqp = media.get("encrypt_query_param", "")
            aes_key = media.get("aes_key", "")
            if not eqp or not aes_key:
                return None
            buf = cdn_download_and_decrypt(eqp, aes_key, self._cdn_base_url)
            fname = fi.get("file_name", "file.bin")
            path = save_media_buffer(buf, guess_mime(fname), "inbound", fname)
            return MediaAttachment(
                media_type=MediaType.FILE, local_path=path,
                mime_type=guess_mime(fname), file_name=fname,
                file_size=int(fi.get("len", 0)),
            )

        elif t == ITEM_VIDEO:
            vid = item.get("video_item", {})
            media = vid.get("media", {})
            eqp = media.get("encrypt_query_param", "")
            aes_key = media.get("aes_key", "")
            if not eqp or not aes_key:
                return None
            buf = cdn_download_and_decrypt(eqp, aes_key, self._cdn_base_url)
            path = save_media_buffer(buf, "video/mp4", "inbound")
            return MediaAttachment(media_type=MediaType.VIDEO, local_path=path, mime_type="video/mp4")

        return None

    # ── Chat + typing ─────────────────────────────────────────────────────

    def _start_chat(self, user_id: str, text: str, original_text: str = "",
                    media: list[MediaAttachment] | None = None):
        def _chat_with_typing():
            typing_stop = self._keep_typing(user_id)
            try:
                chat_engine.do_chat(
                    user_id, text, original_text,
                    self._get_system_prompt(),
                    lambda cid, txt, **kw: self._reply_media(cid, txt, **kw),
                    "wechat",
                    media=media,
                )
            finally:
                typing_stop.set()

        threading.Thread(target=_chat_with_typing, name="wx-chat", daemon=True).start()

    # ── 消息发送 ────────────────────────────────────────────────────────────

    def _reply_text(self, user_id: str, text: str) -> bool:
        ctx_token = get_context_token(user_id)
        if not ctx_token:
            log.warning(f"wechat: no context_token for {user_id[:16]}...")
            return False
        try:
            plain = _strip_markdown(text)
            for chunk in _split_message(plain):
                send_message(self.bot_token, user_id, chunk,
                             ctx_token, self.base_url)
            return True
        except Exception as e:
            log.warning(f"wechat: reply failed: {e}")
            return False

    def _reply_media(self, user_id: str, text: str,
                     media_path: str = "", media_type: str = "") -> bool:
        ctx_token = get_context_token(user_id)
        if not ctx_token:
            log.warning(f"wechat: no context_token for {user_id[:16]}...")
            return False
        try:
            if media_path and os.path.exists(media_path):
                mime = media_type or guess_mime(media_path)
                if mime.startswith("image/"):
                    upload_type = 1
                elif mime.startswith("video/"):
                    upload_type = 2
                else:
                    upload_type = 3

                uploaded = upload_media_file(
                    media_path, user_id, upload_type,
                    self.bot_token, self.base_url, self._cdn_base_url,
                )
                plain = _strip_markdown(text) if text else ""
                if mime.startswith("image/"):
                    send_image(self.bot_token, user_id, ctx_token, uploaded, plain, self.base_url)
                elif mime.startswith("video/"):
                    send_video(self.bot_token, user_id, ctx_token, uploaded, plain, self.base_url)
                else:
                    fname = os.path.basename(media_path)
                    send_file(self.bot_token, user_id, ctx_token, uploaded, fname, plain, self.base_url)
                return True

            plain = _strip_markdown(text)
            for chunk in _split_message(plain):
                send_message(self.bot_token, user_id, chunk, ctx_token, self.base_url)
            return True
        except Exception as e:
            log.warning(f"wechat: reply failed: {e}")
            return False

    # ── Media description ─────────────────────────────────────────────────

    @staticmethod
    def _describe_media(attachments: list[MediaAttachment]) -> str:
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

    # ── 系统提示词 ──────────────────────────────────────────────────────────

    def _get_system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = chat_engine.build_system_prompt(_PLATFORM_RULES)
        return self._system_prompt


# ── 工具函数 ────────────────────────────────────────────────────────────────

def _silk_to_wav(silk_buf: bytes) -> bytes | None:
    """Transcode SILK audio to WAV using ffmpeg."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".silk", delete=False) as f:
            f.write(silk_buf)
            silk_path = f.name
        wav_path = silk_path.replace(".silk", ".wav")
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
                 "-i", silk_path, wav_path],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0 and os.path.exists(wav_path):
                with open(wav_path, "rb") as wf:
                    return wf.read() or None
        finally:
            for p in [silk_path, wav_path]:
                try:
                    os.unlink(p)
                except Exception:
                    pass
    except Exception as e:
        log.debug(f"wechat: silk→wav failed: {e}")
    return None


def _split_message(text: str) -> list[str]:
    limit = WECHAT_MSG_LIMIT
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


def _strip_markdown(text: str) -> str:
    """粗暴去 Markdown，微信不渲染。"""
    text = re.sub(r"```[^\n]*\n?([\s\S]*?)```", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text
