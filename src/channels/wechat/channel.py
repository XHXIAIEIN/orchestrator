"""
微信 WeChat Channel — iLink Bot API 适配器。

出站：ChannelMessage → sendmessage API（需 context_token）
入站：Long polling getupdates → 命令解析 → Event Bus / Claude 对话

对话/DB/工具逻辑复用 src.channels.chat 公共层。
零外部依赖，纯 urllib。
"""
import logging
import os
import threading
from typing import Optional

from src.channels.base import Channel
from src.channels import chat as chat_engine
from src.channels.wechat.api import DEFAULT_BASE_URL, get_updates
from src.channels.wechat.cdn import CDN_BASE_URL
from src.channels.wechat.sender import WeChatSender, PRIORITY_LEVELS
from src.channels.wechat.handler import WeChatHandler
from src.channels.wechat.utils import _silk_to_wav, _split_message, _strip_markdown

log = logging.getLogger(__name__)

# WeChat 平台规则（注入系统提示词）
_PLATFORM_RULES = (
    "# Platform: WeChat\n"
    "- Plain text only. Absolutely NO formatting — no asterisks, no backticks, no HTML tags.\n"
    "- No Markdown, no emoji. WeChat doesn't render any formatting.\n"
    "- Max message length ~2048 chars; longer content is auto-split.\n"
    "- Images and voice arrive as separate messages. Reference them by order (第一张图/第二段语音).\n"
    "- When text follows images, it refers to those images.\n"
)

# WeChat 平台能力声明（供外部模块查询）
PLATFORM_CAPABILITIES = {
    "markdown": False,
    "html": False,
    "images": True,
    "voice": True,
    "max_message_length": 2048,
    "code_blocks": False,
}


class WeChatChannel(WeChatSender, WeChatHandler, Channel):
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
        self._debounce_sec = 8.0   # 每条消息重置窗口
        self._debounce_max = 45.0  # 最大等待上限

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

    # ── 平台提示 ──────────────────────────────────────────────────────────

    def get_platform_hints(self) -> str:
        """返回 WeChat 平台规则提示词。"""
        return _PLATFORM_RULES

    # ── 系统提示词 ──────────────────────────────────────────────────────────

    def _get_system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = chat_engine.build_system_prompt(_PLATFORM_RULES)
        return self._system_prompt
