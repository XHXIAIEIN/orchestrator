"""
Channel 层配置 — 所有可调参数集中管理。

优先级：环境变量 > 此处默认值。
平台常量（如 Telegram 4096 字符限制）不在此处，留在各适配器中。
"""
import os

from src.core.llm_router import MODEL_HAIKU, MODEL_DEEPSEEK


def _int(key: str, default: int) -> int:
    return int(os.environ.get(key, default))


def _str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _list(key: str, default: str) -> list[str]:
    """逗号分隔的列表。"""
    raw = os.environ.get(key, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


# ── 对话模型 ──
CHAT_MODEL = _str("CHANNEL_CHAT_MODEL", MODEL_HAIKU)
CHAT_LOCAL_MODEL = _str("CHANNEL_CHAT_LOCAL_MODEL", MODEL_DEEPSEEK)  # Ollama model for casual chat
CHAT_LOCAL_ENABLED = _str("CHANNEL_CHAT_LOCAL_ENABLED", "true").lower() in ("true", "1", "yes")
CHAT_MAX_TOKENS = _int("CHANNEL_CHAT_MAX_TOKENS", 1024)
SUMMARIZE_MAX_TOKENS = _int("CHANNEL_SUMMARIZE_MAX_TOKENS", 600)

# ── 对话历史 ──
RECENT_TURNS = _int("CHANNEL_RECENT_TURNS", 20)
SUMMARIZE_THRESHOLD = _int("CHANNEL_SUMMARIZE_THRESHOLD", 30)
SUMMARIZE_MIN_MESSAGES = _int("CHANNEL_SUMMARIZE_MIN_MESSAGES", 10)
MAX_DB_MESSAGES = _int("CHANNEL_MAX_DB_MESSAGES", 500)
DB_PRUNE_EXTRA = _int("CHANNEL_DB_PRUNE_EXTRA", 10)

# ── 消息处理 ──
LONG_MSG_THRESHOLD = _int("CHANNEL_LONG_MSG_THRESHOLD", 500)
MAX_FILE_READ_BYTES = _int("CHANNEL_MAX_FILE_READ_BYTES", 1_000_000)
MAX_FILE_READ_CHARS = _int("CHANNEL_MAX_FILE_READ_CHARS", 8000)
SUMMARIZE_MAX_CHARS = _int("CHANNEL_SUMMARIZE_MAX_CHARS", 500)

# ── 网络超时（秒）──
SEND_TIMEOUT = _int("CHANNEL_SEND_TIMEOUT", 10)
POLL_TIMEOUT = _int("CHANNEL_POLL_TIMEOUT", 30)
WEBHOOK_TIMEOUT = _int("CHANNEL_WEBHOOK_TIMEOUT", 5)

# ── 安全 ──
READ_ALLOW_PATHS = _list("CHANNEL_READ_ALLOW_PATHS", "/orchestrator,/git-repos")
RATE_LIMIT_WINDOW = 2  # 秒，防刷，不可配置

# ── 用户权限 ──
# 格式: "chat_id:role,chat_id:role" — role: admin (full) / viewer (query+chat only)
# 向后兼容: 如果只设了 TELEGRAM_CHAT_ID 没设 ALLOWED_USERS，自动当 admin
ALLOWED_USERS: dict[str, str] = {}
_raw_users = _str("TELEGRAM_ALLOWED_USERS", "")
if _raw_users:
    for pair in _raw_users.split(","):
        pair = pair.strip()
        if ":" in pair:
            uid, role = pair.split(":", 1)
            ALLOWED_USERS[uid.strip()] = role.strip()
        elif pair:
            ALLOWED_USERS[pair] = "admin"  # no role = admin
else:
    # Fallback: legacy single TELEGRAM_CHAT_ID
    _legacy_id = _str("TELEGRAM_CHAT_ID", "")
    if _legacy_id:
        ALLOWED_USERS[_legacy_id] = "admin"

# Role permissions
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"chat", "query_status", "dispatch_task", "read_file", "wake_claude"},
    "viewer": {"chat", "query_status"},
}


def user_can(chat_id: str, action: str) -> bool:
    """Check if a chat_id has permission for an action."""
    role = ALLOWED_USERS.get(chat_id, "")
    if not role:
        return False
    return action in ROLE_PERMISSIONS.get(role, set())


def get_admin_chat_ids() -> list[str]:
    """Return all admin chat_ids (for broadcast notifications)."""
    return [uid for uid, role in ALLOWED_USERS.items() if role == "admin"]


def get_all_chat_ids() -> list[str]:
    """Return all allowed chat_ids."""
    return list(ALLOWED_USERS.keys())

# ── 预定义场景 ──
PREDEFINED_SCENARIOS = _list(
    "CHANNEL_PREDEFINED_SCENARIOS",
    "full_audit,system_health,deep_scan",
)

# ── 显示 ──
TASKS_DISPLAY_LIMIT = _int("CHANNEL_TASKS_DISPLAY_LIMIT", 5)
TOOL_USE_MAX_ROUNDS = _int("CHANNEL_TOOL_USE_MAX_ROUNDS", 3)

# ── Docker 路径映射 ──
# key=容器内前缀, value=宿主机路径（为空则直接用容器路径）
PATH_MAPPINGS: dict[str, str] = {}
_raw_mappings = _str("CHANNEL_PATH_MAPPINGS", "/git-repos=")
for pair in _raw_mappings.split(","):
    if "=" in pair:
        k, v = pair.split("=", 1)
        PATH_MAPPINGS[k.strip()] = v.strip()

# ── 媒体 ──
MEDIA_DIR = _str("CHANNEL_MEDIA_DIR", "tmp/media")
MEDIA_MAX_BYTES = _int("CHANNEL_MEDIA_MAX_BYTES", 50 * 1024 * 1024)
WECHAT_CDN_BASE_URL = _str("WECHAT_CDN_BASE_URL", "https://novac2c.cdn.weixin.qq.com/c2c")
