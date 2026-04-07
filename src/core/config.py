"""
自动检测并加载认证凭据，优先级：
1. Claude Code 的 OAuth credentials（~/.claude/.credentials.json）— 订阅用户
2. 环境变量 ANTHROPIC_API_KEY
3. .env 文件

OAuth token 过期时自动使用 refreshToken 刷新，并回写 credentials.json。
"""
import json
import logging
import os
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

ENV_FILE = Path(__file__).parent.parent / ".env"
CLAUDE_CREDS = Path(os.environ.get("CLAUDE_HOME", str(Path.home() / ".claude"))) / ".credentials.json"

# Claude Code OAuth constants (from claude-code source)
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_REFRESH_BUFFER_MS = 5 * 60 * 1000  # refresh 5 min before expiry

_refresh_lock = threading.Lock()


def _is_token_expiring(expires_at: int) -> bool:
    """Check if token expires within the buffer window."""
    now_ms = int(time.time() * 1000)
    return (now_ms + _REFRESH_BUFFER_MS) >= expires_at


def _refresh_oauth_token(creds: dict) -> dict | None:
    """Refresh OAuth token using refreshToken. Returns updated creds or None."""
    oauth = creds.get("claudeAiOauth", {})
    refresh_token = oauth.get("refreshToken", "")
    if not refresh_token:
        log.warning("oauth_refresh: no refreshToken available")
        return None

    scopes = oauth.get("scopes", [])
    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": _CLIENT_ID,
        "scope": " ".join(scopes) if scopes else "",
    }).encode()

    req = Request(_TOKEN_URL, data=body, headers={
        "Content-Type": "application/json",
        "User-Agent": "claude-code/1.0",
    }, method="POST")
    try:
        with urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                log.error("oauth_refresh: HTTP %d", resp.status)
                return None
            data = json.loads(resp.read())
    except (URLError, OSError, json.JSONDecodeError) as exc:
        log.error("oauth_refresh: request failed: %s", exc)
        return None

    new_access = data.get("access_token", "")
    new_refresh = data.get("refresh_token", refresh_token)
    expires_in = data.get("expires_in", 3600)
    new_scopes = data.get("scope", "").split() if data.get("scope") else scopes

    if not new_access:
        log.error("oauth_refresh: response missing access_token")
        return None

    expires_at = int(time.time() * 1000) + expires_in * 1000

    # Update creds in place
    oauth["accessToken"] = new_access
    oauth["refreshToken"] = new_refresh
    oauth["expiresAt"] = expires_at
    oauth["scopes"] = new_scopes
    creds["claudeAiOauth"] = oauth

    log.info("oauth_refresh: token refreshed, expires in %ds", expires_in)
    return creds


def _ensure_fresh_token() -> str:
    """Load OAuth token, refreshing if expired. Returns access token or empty string."""
    if not CLAUDE_CREDS.exists():
        return ""

    try:
        creds = json.loads(CLAUDE_CREDS.read_text(encoding="utf-8"))
    except Exception:
        return ""

    oauth = creds.get("claudeAiOauth", {})
    token = oauth.get("accessToken", "")
    expires_at = oauth.get("expiresAt", 0)

    if not token:
        return ""

    # Token still valid
    if expires_at and not _is_token_expiring(expires_at):
        return token

    # Need refresh — serialize to prevent thundering herd
    with _refresh_lock:
        # Double-check: another thread may have refreshed while we waited
        try:
            creds = json.loads(CLAUDE_CREDS.read_text(encoding="utf-8"))
        except Exception:
            return token  # fallback to possibly-expired token
        oauth = creds.get("claudeAiOauth", {})
        expires_at = oauth.get("expiresAt", 0)
        if expires_at and not _is_token_expiring(expires_at):
            return oauth.get("accessToken", token)

        # Actually refresh
        log.info("oauth_refresh: token expiring, refreshing...")
        updated = _refresh_oauth_token(creds)
        if updated:
            try:
                CLAUDE_CREDS.write_text(json.dumps(updated, indent=2), encoding="utf-8")
            except OSError as exc:
                log.warning("oauth_refresh: failed to write credentials: %s", exc)
            return updated["claudeAiOauth"]["accessToken"]

        log.warning("oauth_refresh: refresh failed, using existing token")
        return token


def load_credentials() -> tuple[str, bool]:
    """返回 (token, is_oauth)。is_oauth=True 表示订阅 OAuth token。"""
    # 1. Claude Code OAuth token（自动刷新）
    oauth_token = _ensure_fresh_token()
    if oauth_token:
        return oauth_token, True

    # 2. 环境变量
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key, False

    # 3. .env 文件
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return key, False

    return "", False


def load_api_key() -> str:
    """兼容旧接口，返回 token 字符串。"""
    token, _ = load_credentials()
    return token


def get_anthropic_client():
    """返回已配置好认证的 anthropic.Anthropic 实例。所有模块统一用这个。"""
    import anthropic
    token, is_oauth = load_credentials()
    if not token:
        raise RuntimeError("未找到认证凭据：请配置 ANTHROPIC_API_KEY 或使用 Claude 订阅登录。")
    # sk-ant-oat01-* OAuth tokens 和普通 API key 都走 x-api-key 头
    return anthropic.Anthropic(api_key=token)


def save_api_key(key: str):
    """将 API key 写入 .env 文件"""
    content = f"ANTHROPIC_API_KEY={key}\n"
    ENV_FILE.write_text(content, encoding="utf-8")
    os.environ["ANTHROPIC_API_KEY"] = key
