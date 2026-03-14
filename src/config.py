"""
自动检测并加载认证凭据，优先级：
1. Claude Code 的 OAuth credentials（~/.claude/.credentials.json）— 订阅用户
2. 环境变量 ANTHROPIC_API_KEY
3. .env 文件
"""
import json
import os
from pathlib import Path

ENV_FILE = Path(__file__).parent.parent / ".env"
CLAUDE_CREDS = Path.home() / ".claude" / ".credentials.json"


def load_credentials() -> tuple[str, bool]:
    """返回 (token, is_oauth)。is_oauth=True 表示订阅 OAuth token，需用 Bearer 认证。"""
    # 1. Claude Code OAuth token（订阅优先）
    if CLAUDE_CREDS.exists():
        try:
            creds = json.loads(CLAUDE_CREDS.read_text(encoding="utf-8"))
            token = creds.get("claudeAiOauth", {}).get("accessToken", "")
            if token:
                return token, True
        except Exception:
            pass

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
    if is_oauth:
        return anthropic.Anthropic(
            api_key="oauth-token",
            default_headers={"Authorization": f"Bearer {token}"},
        )
    return anthropic.Anthropic(api_key=token)


def save_api_key(key: str):
    """将 API key 写入 .env 文件"""
    content = f"ANTHROPIC_API_KEY={key}\n"
    ENV_FILE.write_text(content, encoding="utf-8")
    os.environ["ANTHROPIC_API_KEY"] = key
