"""
微信 ClawBot 扫码登录 — token 持久化。

登录流程:
1. get_bot_qrcode → qrcode_img_content 是微信协议 URL
2. 编码为二维码 → 终端显示 / 浏览器弹窗
3. 用户从微信 ClawBot 插件扫码确认
4. get_qrcode_status 轮询 → 拿到 bot_token → 存 src/channels/wechat/credentials.json

可作为独立 CLI 工具: python -m src.channels.wechat.login
"""
import base64
import io
import json
import logging
import os
import tempfile
import time
import webbrowser
from pathlib import Path

from src.channels.wechat.api import (
    DEFAULT_BASE_URL,
    get_qrcode,
    get_qrcode_status,
)

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CREDENTIALS_PATH = Path(__file__).resolve().parent / "credentials.json"


def load_credentials() -> dict | None:
    """加载已保存的凭证。返回 {bot_token, base_url, user_id} 或 None。"""
    if not CREDENTIALS_PATH.exists():
        return None
    try:
        data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
        if data.get("bot_token"):
            return data
    except Exception as e:
        log.warning(f"wechat_login: failed to load credentials: {e}")
    return None


def save_credentials(bot_token: str, base_url: str = "", user_id: str = ""):
    """持久化凭证。"""
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "bot_token": bot_token,
        "base_url": base_url or DEFAULT_BASE_URL,
        "user_id": user_id,
    }
    CREDENTIALS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log.info(f"wechat_login: credentials saved to {CREDENTIALS_PATH}")


def _show_qr_browser(qr_url: str, poll_key: str):
    """在浏览器弹窗显示二维码。"""
    try:
        import qrcode  # type: ignore
    except ImportError:
        print(f"[微信 ClawBot] 需要 qrcode 库: pip install qrcode[pil]")
        print(f"[微信 ClawBot] 二维码链接: {qr_url}")
        return

    qr = qrcode.QRCode(version=1, box_size=12, border=4)
    qr.add_data(qr_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>WeChat ClawBot Login</title>
<style>
body {{ display:flex;flex-direction:column;align-items:center;justify-content:center;
       height:100vh;margin:0;background:#0d1117;font-family:system-ui;color:#e6edf3 }}
.card {{ background:#161b22;padding:40px;border-radius:16px;border:1px solid #30363d;text-align:center }}
h2 {{ margin:0 0 8px;font-size:22px }}
.sub {{ color:#8b949e;margin-bottom:24px;font-size:15px }}
img {{ width:300px;height:300px;border-radius:8px }}
.hint {{ color:#58a6ff;margin-top:20px;font-size:14px }}
.key {{ color:#484f58;margin-top:8px;font-size:11px }}
</style></head>
<body><div class="card">
<h2>微信 ClawBot 扫码登录</h2>
<p class="sub">微信 → ClawBot 插件 → 开始扫一扫</p>
<img src="data:image/png;base64,{b64}" />
<p class="hint">等待扫码中...</p>
<p class="key">{poll_key}</p>
</div></body></html>"""

    path = os.path.join(tempfile.gettempdir(), "wechat-qr.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    webbrowser.open(f"file:///{path}")


def login_interactive(base_url: str = DEFAULT_BASE_URL,
                      timeout_sec: int = 300) -> dict | None:
    """交互式扫码登录。浏览器弹窗显示二维码 + 终端 fallback。

    Returns: {bot_token, base_url, user_id} 或 None（超时/失败）。
    """
    print("\n[微信 ClawBot] 正在获取二维码...")

    try:
        qr_resp = get_qrcode(base_url)
    except Exception as e:
        print(f"[微信 ClawBot] 获取二维码失败: {e}")
        return None

    poll_key = qr_resp.get("qrcode", "")
    # qrcode_img_content 是微信协议 URL，不是图片！
    qr_url = qr_resp.get("qrcode_img_content", "")

    if not poll_key or not qr_url:
        print(f"[微信 ClawBot] 响应异常: {qr_resp}")
        return None

    # 浏览器弹窗显示
    _show_qr_browser(qr_url, poll_key)
    print(f"[微信 ClawBot] 二维码已在浏览器打开")

    # 终端也显示一份
    try:
        import qrcode  # type: ignore
        qr = qrcode.QRCode(box_size=1, border=1)
        qr.add_data(qr_url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except ImportError:
        pass

    print(f"\n[微信 ClawBot] 微信 → ClawBot 插件 → 开始扫一扫")
    print(f"[微信 ClawBot] 等待扫码确认（{timeout_sec}s 超时）...")
    deadline = time.time() + timeout_sec

    while time.time() < deadline:
        try:
            status_resp = get_qrcode_status(poll_key, base_url)
            status = status_resp.get("status", "")

            if status == "confirmed":
                bot_token = status_resp.get("bot_token", "")
                resp_base_url = status_resp.get("baseurl", base_url)
                user_id = (status_resp.get("ilink_bot_id", "")
                           or status_resp.get("bot_id", ""))

                if bot_token:
                    save_credentials(bot_token, resp_base_url, user_id)
                    print(f"\n[微信 ClawBot] 登录成功！")
                    return {
                        "bot_token": bot_token,
                        "base_url": resp_base_url,
                        "user_id": user_id,
                    }
                else:
                    print(f"[微信 ClawBot] 扫码确认但未返回 token: {status_resp}")
                    return None

            elif status == "scaned":
                print(f"[微信 ClawBot] 已扫码，等待确认...")

            elif status == "expired":
                print(f"[微信 ClawBot] 二维码已过期")
                return None

        except Exception as e:
            log.debug(f"wechat_login: poll error: {e}")

        time.sleep(2)

    print(f"[微信 ClawBot] 超时，未完成扫码")
    return None


# ── CLI 入口 ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = login_interactive()
    if result:
        print(f"Token: {result['bot_token'][:20]}...")
    else:
        print("登录失败")
        exit(1)
