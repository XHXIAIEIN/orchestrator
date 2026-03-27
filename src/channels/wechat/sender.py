"""WeChat outbound message methods (mixin)."""
import logging
import os

from src.channels.base import ChannelMessage
from src.channels.media import guess_mime
from src.channels.wechat.api import (
    send_message,
    get_context_token,
    get_all_context_users,
    send_image,
    send_file,
    send_video,
)
from src.channels.wechat.cdn import upload_media_file
from src.channels.wechat.utils import _split_message, _strip_markdown

log = logging.getLogger(__name__)

PRIORITY_LEVELS = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}


class WeChatSender:
    """Mixin: all outbound / send methods for WeChatChannel."""

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
