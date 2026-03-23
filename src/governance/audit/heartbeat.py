"""
Heartbeat Protocol — 标准化的 agent 心跳。

Paperclip 启发：9 步心跳规范，靠 prompt 注入不硬编码。

心跳用途：
  1. 检测僵尸任务（heartbeat 超时 → 标记为 zombie）
  2. 进度追踪（progress_pct 从 0→100）
  3. 上下文恢复（session data 持久化）

集成：Governor._run_agent_session 中周期性检查。
"""
import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT_S = 120  # 心跳超时（秒）
ZOMBIE_THRESHOLD_S = 300   # 僵尸阈值（秒）


# ── Heartbeat Prompt Injection ──
# 注入到 agent prompt，让 agent 定期汇报进度

HEARTBEAT_PROMPT = """
## 执行规范
在执行过程中，每完成一个主要步骤后，输出一行进度标记：
PROGRESS: <0-100>% <当前在做什么>

例如：
PROGRESS: 20% 正在分析代码结构
PROGRESS: 50% 修改完成，准备测试
PROGRESS: 90% 测试通过，整理输出

这不影响你的工作方式，只是帮助系统追踪进度。
"""


def check_zombie_tasks(db, timeout_s: int = ZOMBIE_THRESHOLD_S) -> list[dict]:
    """检测僵尸任务：running 状态但心跳超时。"""
    running_tasks = db.get_running_tasks()
    zombies = []

    for task in running_tasks:
        started = task.get("started_at", "")
        if not started:
            continue

        try:
            started_dt = datetime.fromisoformat(started)
        except ValueError:
            continue

        # 检查最后心跳
        last_hb = db.get_last_heartbeat(task["id"])
        if last_hb:
            try:
                hb_time = datetime.fromisoformat(last_hb.get("created_at", ""))
                elapsed = (datetime.now(timezone.utc) - hb_time).total_seconds()
            except ValueError:
                elapsed = float("inf")
        else:
            elapsed = (datetime.now(timezone.utc) - started_dt).total_seconds()

        if elapsed > timeout_s:
            zombies.append({
                "task_id": task["id"],
                "action": task.get("action", ""),
                "elapsed_s": int(elapsed),
                "last_heartbeat": last_hb.get("created_at", "") if last_hb else "",
            })

    return zombies


def parse_progress(output: str) -> int:
    """从 agent 输出中提取最新的 PROGRESS 百分比。"""
    import re
    matches = re.findall(r'PROGRESS:\s*(\d+)%', output)
    if matches:
        return min(100, int(matches[-1]))
    return 0
