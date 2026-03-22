"""
Wake — 从 Telegram 唤醒宿主机的 Claude Code 会话。

流程：
1. Bot 写 JSON 到 tmp/wake/{timestamp}.json
2. 宿主机 watcher 脚本检测到新文件
3. Watcher 打开终端启动 claude code，传入任务上下文
4. Claude Code 完成后写 response 文件
5. Bot 读 response 推回 Telegram

共享目录：tmp/wake/（Docker volume mount，容器和宿主机都能访问）
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WAKE_DIR = _REPO_ROOT / "tmp" / "wake"


def write_wake_request(task: str, context: str = "", priority: str = "normal",
                        chat_id: str = "") -> str:
    """写一个唤醒请求文件，返回文件名。"""
    WAKE_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc)
    filename = f"{ts.strftime('%Y%m%d-%H%M%S')}.json"
    filepath = WAKE_DIR / filename

    request = {
        "task": task,
        "context": context,
        "priority": priority,
        "chat_id": chat_id,
        "status": "pending",
        "created_at": ts.isoformat(),
    }

    filepath.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"wake: request written to {filepath}")
    return filename


def read_response(filename: str) -> dict | None:
    """读取响应文件（watcher 写的）。"""
    resp_path = WAKE_DIR / filename.replace(".json", ".response.json")
    if not resp_path.exists():
        return None
    try:
        return json.loads(resp_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_pending() -> list[dict]:
    """列出所有 pending 的唤醒请求。"""
    WAKE_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for f in sorted(WAKE_DIR.glob("*.json")):
        if f.name.endswith(".response.json"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("status") == "pending":
                data["filename"] = f.name
                results.append(data)
        except Exception:
            pass
    return results
