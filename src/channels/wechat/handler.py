"""WeChat inbound message handling methods (mixin)."""
import logging
import threading
import time

from src.channels import config as ch_cfg
from src.channels import chat as chat_engine
from src.channels.boundary_nonce import wrap_untrusted_block
from src.channels.media import MediaAttachment, MediaType, save_media_buffer, guess_mime
from src.channels.wechat.api import (
    extract_text,
    extract_from_user,
    extract_media_items,
    set_context_token,
    get_context_token,
    get_config,
    send_typing,
    ITEM_IMAGE, ITEM_VOICE, ITEM_FILE, ITEM_VIDEO,
)
from src.channels.wechat.cdn import cdn_download_and_decrypt, cdn_download_plain
from src.channels.wechat.utils import _silk_to_wav

log = logging.getLogger(__name__)


class WeChatHandler:
    """Mixin: all inbound / handler methods for WeChatChannel."""

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

        # Security: wrap external input with nonce boundary to prevent injection
        text = wrap_untrusted_block(text, label="wechat_message",
                                    source=f"wechat/{user_id[:16]}")

        if len(text) > ch_cfg.LONG_MSG_THRESHOLD:
            file_path, char_count = chat_engine.save_to_inbox(text)
            preview = text[:80].replace("\n", " ")
            ref = f'[用户发送了长消息 ({char_count}字)，已保存到 {file_path}，预览: "{preview}..."]'
            self._start_chat(user_id, ref, original_text=text, media=attachments)
        else:
            self._start_chat(user_id, text, media=attachments)

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

    def _keep_typing(self, user_id: str) -> threading.Event:
        stop = threading.Event()
        def _loop():
            while not stop.is_set():
                self._send_typing_indicator(user_id, 1)
                stop.wait(timeout=5)
            self._send_typing_indicator(user_id, 2)  # cancel
        threading.Thread(target=_loop, name="wx-typing", daemon=True).start()
        return stop

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
