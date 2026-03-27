"""Telegram outbound message methods (mixin)."""
import json
import logging
import os
import re
import urllib.request

from src.channels.base import ChannelMessage
from src.channels import config as ch_cfg
from src.channels.media import guess_mime

log = logging.getLogger(__name__)

PRIORITY_LEVELS = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}

# ── 图片标记解析 ──────────────────────────────────────────────────────────
_RE_PHOTO = re.compile(r"<photo>(https?://\S+?)</photo>", re.I)
_RE_PREVIEW = re.compile(r"<preview>(https?://\S+?)</preview>", re.I)
_RE_THUMB = re.compile(r"<thumb>(https?://\S+?)</thumb>", re.I)


class TelegramSender:
    """Mixin: all outbound / send methods for TelegramChannel."""

    _TG_MSG_LIMIT = 4096

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
            # Approval requests get inline keyboard buttons
            if message.event_type == "approval.request":
                ok = self._send_approval_with_buttons(target_id, message.text) and ok
            else:
                ok = self._send_text(target_id, message.text) and ok
        return ok

    def _send_approval_with_buttons(self, chat_id: str, text: str) -> bool:
        """Send approval message with Approve/Deny inline keyboard."""
        # Extract task_id from the message text (format: Task: <code>xxx</code> or Task: `xxx`)
        match = re.search(r'Task:\s*(?:<code>([^<]+)</code>|`([^`]+)`)', text)
        task_id = (match.group(1) or match.group(2)) if match else "unknown"

        body = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "批准", "callback_data": f"approve:{task_id}"},
                    {"text": "拒绝", "callback_data": f"deny:{task_id}"},
                ]]
            }
        }
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
                log.warning(f"telegram: sendMessage (approval) failed: {result}")
                return False
            return True
        except Exception as e:
            log.warning(f"telegram: approval send failed: {e}")
            return False

    def _send_text(self, chat_id: str, text: str) -> bool:
        # ── Mode 1: <photo>URL</photo> → sendPhoto ──
        m = _RE_PHOTO.search(text)
        if m:
            url = m.group(1)
            caption = _RE_PHOTO.sub("", text).strip()
            if self._send_photo_url(chat_id, url, caption):
                return True
            # fallback: 去掉标记，走普通文本
            text = caption

        # ── Mode 2: <preview>URL</preview> → 大图预览在文字上方 ──
        m = _RE_PREVIEW.search(text)
        if m:
            url = m.group(1)
            clean = _RE_PREVIEW.sub("", text).strip()
            # 把 URL 隐藏在零宽字符链接里，触发 Telegram 的 link preview
            body_text = f'{clean}\n<a href="{url}">\u200d</a>' if clean else f'<a href="{url}">\u200d</a>'
            return self._send_raw(chat_id, body_text, parse_mode="HTML",
                                  preview_opts={"prefer_large_media": True, "show_above_text": True, "url": url})

        # ── Mode 3: <thumb>URL</thumb> → 小图预览在文字下方 ──
        m = _RE_THUMB.search(text)
        if m:
            url = m.group(1)
            clean = _RE_THUMB.sub("", text).strip()
            body_text = f'{clean}\n<a href="{url}">\u200d</a>' if clean else f'<a href="{url}">\u200d</a>'
            return self._send_raw(chat_id, body_text, parse_mode="HTML",
                                  preview_opts={"prefer_small_media": True, "show_above_text": False, "url": url})

        # ── 默认: 纯文本 ──
        chunks = self._split_message(text)
        ok = True
        for chunk in chunks:
            sent = self._send_raw(chat_id, chunk, parse_mode="HTML")
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

    def _send_raw(self, chat_id: str, text: str, parse_mode: str = None,
                  preview_opts: dict | None = None) -> bool:
        body: dict = {"chat_id": chat_id, "text": text}
        body["link_preview_options"] = preview_opts or {"is_disabled": True}
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

    def _set_reaction(self, chat_id: str, message_id: int, emoji: str) -> bool:
        """给消息加表情回应。"""
        result = self._tg_api("setMessageReaction", {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}],
        })
        ok = result.get("ok", False)
        if not ok:
            log.warning(f"telegram: setMessageReaction failed: {result}")
        return ok

    # ── 出站多媒体 ──────────────────────────────────────────────────────────

    def _send_photo(self, chat_id: str, photo_path: str, caption: str = "") -> bool:
        return self._send_multipart(chat_id, "sendPhoto", "photo", photo_path, caption)

    def _send_photo_url(self, chat_id: str, photo_url: str,
                        caption: str = "", parse_mode: str = "HTML") -> bool:
        """Send photo by URL (no download needed, Telegram fetches it)."""
        body: dict = {"chat_id": chat_id, "photo": photo_url}
        if caption:
            body["caption"] = caption[:1024]
        if parse_mode:
            body["parse_mode"] = parse_mode
        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/sendPhoto",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=ch_cfg.SEND_TIMEOUT)
            result = json.loads(resp.read())
            if not result.get("ok"):
                log.warning(f"telegram: sendPhoto (url) failed: {result}")
                return False
            return True
        except Exception as e:
            log.warning(f"telegram: sendPhoto (url) failed: {e}")
            return False

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
