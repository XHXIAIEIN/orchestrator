"""Telegram inbound message handling methods (mixin)."""
import json
import logging
import threading
import time
import urllib.request

from src.channels import config as ch_cfg
from src.channels import chat as chat_engine
from src.channels.boundary_nonce import wrap_untrusted_block
from src.channels.media import (
    MediaAttachment, MediaType, download_url, extract_document_text,
)

log = logging.getLogger(__name__)


class TelegramHandler:
    """Mixin: all inbound / handler methods for TelegramChannel."""

    def _flush_pending(self, chat_id: str):
        """Debounce timer expired — process accumulated messages as one batch."""
        with self._pending_lock:
            buf = self._pending.pop(chat_id, None)
        if not buf:
            return
        texts = buf["texts"]
        attachments = buf["attachments"]
        text = "\n".join(texts) if texts else ""
        self._process_message(chat_id, text, attachments, msg_id=buf.get("msg_id"))

    def _process_message(self, chat_id: str, text: str,
                         attachments: list[MediaAttachment],
                         msg_id: int | None = None):
        """Route a (possibly batched) message to chat engine."""
        if not text and attachments:
            text = self._describe_media(attachments)

        # Security: wrap external input with nonce boundary to prevent injection
        text = wrap_untrusted_block(text, label="telegram_message",
                                    source=f"telegram/{chat_id}")

        if len(text) > ch_cfg.LONG_MSG_THRESHOLD:
            file_path, char_count = chat_engine.save_to_inbox(text)
            preview = text[:80].replace("\n", " ")
            ref = f'[用户发送了长消息 ({char_count}字)，已保存到 {file_path}，预览: "{preview}..."]'
            self._start_chat(chat_id, ref, original_text=text, media=attachments, msg_id=msg_id)
        else:
            self._start_chat(chat_id, text, media=attachments, msg_id=msg_id)

    def _handle_reaction(self, reaction: dict):
        """Handle user adding a reaction to a message — feed it into chat as context."""
        chat_id = str(reaction.get("chat", {}).get("id", ""))
        user = reaction.get("user", {})
        msg_id = reaction.get("message_id")

        if not chat_id or not msg_id:
            return
        if ch_cfg.ALLOWED_USERS and not ch_cfg.user_can(chat_id, "chat"):
            return

        # 提取新增的 emoji
        new_reactions = reaction.get("new_reaction", [])
        emojis = [r.get("emoji", "") for r in new_reactions if r.get("type") == "emoji"]
        if not emojis:
            return

        emoji_str = "".join(emojis)
        log.info(f"telegram: user reacted {emoji_str} on msg {msg_id}")

        text = f"[用户对消息添加了表情: {emoji_str}]"
        def react_fn(emoji: str):
            self._set_reaction(chat_id, msg_id, emoji)

        def _react_chat():
            chat_engine.do_chat(
                chat_id, text, "",
                self._get_system_prompt(),
                lambda cid, txt, **kw: self._reply_media(cid, txt, **kw),
                "telegram",
                permission_check_fn=lambda cid, tool: ch_cfg.user_can(cid, tool),
                react_fn=react_fn,
            )

        threading.Thread(target=_react_chat, name="tg-reaction", daemon=True).start()

    def _handle_callback_query(self, callback: dict):
        """Handle inline keyboard button press (approval decisions)."""
        callback_id = callback.get("id", "")
        data = callback.get("data", "")
        chat_id = str(callback.get("from", {}).get("id", ""))
        message_id = callback.get("message", {}).get("message_id")

        # Auth check
        if ch_cfg.ALLOWED_USERS and not ch_cfg.user_can(chat_id, "chat"):
            self._tg_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Unauthorized"})
            return

        # Parse callback_data: "approve:task-id" or "deny:task-id"
        if ":" not in data:
            return
        action, task_id = data.split(":", 1)
        if action not in ("approve", "deny"):
            return

        # Submit decision to approval gateway
        try:
            from src.governance.approval import get_approval_gateway
            gw = get_approval_gateway()
            gw.submit_decision(task_id, action, f"telegram:{chat_id}")
        except Exception as e:
            log.warning(f"telegram: approval callback failed: {e}")

        # Answer callback (removes loading spinner on button)
        label = "已批准" if action == "approve" else "已拒绝"
        self._tg_api("answerCallbackQuery", {
            "callback_query_id": callback_id,
            "text": f"{label}: {task_id}",
        })

        # Update the original message to show the decision
        if message_id:
            self._tg_api("editMessageReplyMarkup", {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": [[
                    {"text": f"{label} ✓", "callback_data": "noop"}
                ]]}
            })

        log.info(f"telegram: approval callback {action} for {task_id} from {chat_id}")

    def _download_tg_file(self, file_id: str, media_type: MediaType,
                          mime: str, duration_ms: int = 0) -> MediaAttachment | None:
        """Download a file from Telegram and wrap as MediaAttachment."""
        try:
            url = self._tg_get_file_url(file_id)
            if not url:
                return None
            local_path = download_url(url, "inbound")
            att = MediaAttachment(
                media_type=media_type, local_path=local_path,
                mime_type=mime, duration_ms=duration_ms,
            )
            # Auto-extract text from documents (parallel to voice transcription)
            if media_type == MediaType.FILE and not att.text:
                extracted = extract_document_text(local_path, mime)
                if extracted:
                    att.text = extracted
                    log.info(f"telegram: extracted {len(extracted)} chars from document")
            return att
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
                label = a.file_name or '未知'
                if a.text:
                    descs.append(f"[用户发送了文件: {label}，已提取内容]")
                else:
                    descs.append(f"[用户发送了文件: {label}]")
            elif a.media_type == MediaType.VIDEO:
                descs.append("[用户发送了一段视频]")
        return " ".join(descs) if descs else "[用户发送了媒体消息]"

    @staticmethod
    def _transcribe(file_path: str) -> str:
        """Transcribe audio file to text via faster-whisper."""
        try:
            from src.channels.transcribe import transcribe_audio
            return transcribe_audio(file_path)
        except Exception as e:
            log.warning(f"telegram: transcription failed: {e}")
            return ""

    def _keep_typing(self, chat_id: str) -> threading.Event:
        stop = threading.Event()
        def _loop():
            while not stop.is_set():
                self._send_typing(chat_id)
                stop.wait(timeout=4)
        threading.Thread(target=_loop, name="tg-typing", daemon=True).start()
        return stop

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
