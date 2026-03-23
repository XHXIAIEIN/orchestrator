"""
微信 iLink Bot API client — 直接对接 ilinkai.weixin.qq.com。

5 个端点封装 + context_token 内存缓存。零外部依赖，纯 urllib。
协议参考: @tencent-weixin/openclaw-weixin 1.0.2 源码。
"""
import base64
import json
import logging
import os
import random
import threading
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
CHANNEL_VERSION = "1.0.2"


def _base_info() -> dict:
    """每个请求都要带的 base_info。"""
    return {"channel_version": CHANNEL_VERSION}

# ── context_token 缓存 ──────────────────────────────────────────────────────
# key = user_id, value = context_token
# 每次 getupdates 收到消息时更新，sendmessage 时读取。
_context_tokens: dict[str, str] = {}
_ctx_lock = threading.Lock()


def set_context_token(user_id: str, token: str):
    with _ctx_lock:
        _context_tokens[user_id] = token


def get_context_token(user_id: str) -> str | None:
    with _ctx_lock:
        return _context_tokens.get(user_id)


def get_all_context_users() -> list[str]:
    """返回所有有 context_token 的用户 ID。"""
    with _ctx_lock:
        return list(_context_tokens.keys())


# ── HTTP 基础 ────────────────────────────────────────────────────────────────

def _random_uin() -> str:
    """生成 X-WECHAT-UIN header: base64(str(random_uint32))"""
    return base64.b64encode(str(random.randint(0, 0xFFFFFFFF)).encode()).decode()


def _build_headers(bot_token: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {bot_token}",
        "X-WECHAT-UIN": _random_uin(),
    }


def _api_post(base_url: str, path: str, bot_token: str, body: dict,
              timeout: int = 10) -> dict:
    """通用 POST 请求。"""
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers=_build_headers(bot_token),
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:500]
        log.error(f"wechat_api: {path} HTTP {e.code}: {body_text}")
        raise
    except Exception as e:
        log.error(f"wechat_api: {path} failed: {e}")
        raise


def _api_get(base_url: str, path: str, bot_token: str | None = None,
             timeout: int = 10) -> dict:
    """通用 GET 请求。"""
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = _build_headers(bot_token) if bot_token else {}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except Exception as e:
        log.error(f"wechat_api: GET {path} failed: {e}")
        raise


# ── 5 个端点 ─────────────────────────────────────────────────────────────────

def get_qrcode(base_url: str = DEFAULT_BASE_URL, bot_type: int = 3) -> dict:
    """获取扫码二维码。返回 {qrcode, qrcode_img_content}。"""
    return _api_get(base_url, f"ilink/bot/get_bot_qrcode?bot_type={bot_type}")


def get_qrcode_status(qrcode: str, base_url: str = DEFAULT_BASE_URL) -> dict:
    """轮询扫码状态。成功返回 {status: 'confirmed', bot_token, baseurl}。"""
    return _api_get(base_url, f"ilink/bot/get_qrcode_status?qrcode={qrcode}")


def get_updates(bot_token: str, sync_cursor: str = "",
                base_url: str = DEFAULT_BASE_URL,
                timeout: int = 60) -> dict:
    """长轮询收消息。返回 {ret, msgs, get_updates_buf, longpolling_timeout_ms}。"""
    body = {"get_updates_buf": sync_cursor, "base_info": _base_info()}
    return _api_post(base_url, "ilink/bot/getupdates", bot_token, body,
                     timeout=timeout)


def _generate_client_id() -> str:
    """生成唯一消息 ID。"""
    import uuid
    return f"orchestrator-{uuid.uuid4().hex[:12]}"


def send_message(bot_token: str, to_user_id: str, text: str,
                 context_token: str,
                 base_url: str = DEFAULT_BASE_URL) -> dict:
    """发送文本消息。"""
    body = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": _generate_client_id(),
            "message_type": 2,   # BOT
            "message_state": 2,  # FINISH
            "context_token": context_token,
            "item_list": [
                {"type": 1, "text_item": {"text": text}},
            ],
        },
        "base_info": _base_info(),
    }
    return _api_post(base_url, "ilink/bot/sendmessage", bot_token, body)


def send_typing(bot_token: str, user_id: str, typing_ticket: str,
                status: int = 1,
                base_url: str = DEFAULT_BASE_URL) -> dict:
    """发送/取消输入状态。status: 1=typing, 2=cancel。"""
    body = {
        "ilink_user_id": user_id,
        "typing_ticket": typing_ticket,
        "status": status,
    }
    return _api_post(base_url, "ilink/bot/sendtyping", bot_token, body)


def get_config(bot_token: str, user_id: str = "",
               context_token: str = "",
               base_url: str = DEFAULT_BASE_URL) -> dict:
    """获取账号配置（typing_ticket 等）。"""
    body: dict = {}
    if user_id:
        body["ilink_user_id"] = user_id
    if context_token:
        body["context_token"] = context_token
    return _api_post(base_url, "ilink/bot/getconfig", bot_token, body)


# ── 消息解析工具 ─────────────────────────────────────────────────────────────

def extract_text(msg: dict) -> str:
    """从 WeixinMessage 提取文本内容。"""
    for item in msg.get("item_list") or []:
        if item.get("type") == 1 and item.get("text_item"):
            return item["text_item"].get("text", "")
        # 语音转文字
        if item.get("type") == 3 and item.get("voice_item", {}).get("text"):
            return item["voice_item"]["text"]
    return ""


def extract_from_user(msg: dict) -> str:
    """提取发送者 ID。"""
    return msg.get("from_user_id", "")
