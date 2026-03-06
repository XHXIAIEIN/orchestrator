"""
自动检测并加载 API key，优先级：
1. 环境变量 ANTHROPIC_API_KEY
2. .env 文件
3. Claude Code 的 OAuth credentials（~/.claude/.credentials.json）
"""
import json
import os
from pathlib import Path

ENV_FILE = Path(__file__).parent.parent / ".env"
CLAUDE_CREDS = Path.home() / ".claude" / ".credentials.json"


def load_api_key() -> str:
    # 1. 环境变量
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key

    # 2. .env 文件
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    os.environ["ANTHROPIC_API_KEY"] = key
                    return key

    # 3. Claude Code OAuth token（作为 Bearer token 使用）
    if CLAUDE_CREDS.exists():
        try:
            creds = json.loads(CLAUDE_CREDS.read_text(encoding="utf-8"))
            token = creds.get("claudeAiOauth", {}).get("accessToken", "")
            if token:
                os.environ["ANTHROPIC_API_KEY"] = token
                return token
        except Exception:
            pass

    return ""


def save_api_key(key: str):
    """将 API key 写入 .env 文件"""
    content = f"ANTHROPIC_API_KEY={key}\n"
    ENV_FILE.write_text(content, encoding="utf-8")
    os.environ["ANTHROPIC_API_KEY"] = key
