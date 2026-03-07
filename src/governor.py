"""
Governor — picks top-priority insight recommendation and executes it via claude subprocess.
Auto-triggered after InsightEngine; also called by dashboard approve endpoint.
"""
import logging
import subprocess
from datetime import datetime, timezone

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

TASK_PROMPT_TEMPLATE = """你在 /orchestrator 目录下工作。

问题：{problem}

行为链（观察到的数字行为）：{behavior_chain}

观察结果：{observation}

预期结果（执行后应该变成什么样）：{expected}

任务：{action}

原因：{reason}

完成后以 DONE: <一句话描述做了什么> 结尾。"""

CLAUDE_TIMEOUT = 300  # seconds


class Governor:
    def __init__(self, db: EventsDB = None, db_path: str = "events.db"):
        self.db = db or EventsDB(db_path)

    def run(self) -> dict | None:
        """Auto-triggered: pick top high-priority recommendation and execute."""
        if self.db.get_running_task():
            log.info("Governor: task already running, skipping")
            return None

        insights = self.db.get_latest_insights()
        recs = insights.get("recommendations", [])
        high = [r for r in recs if r.get("priority") == "high"]
        if not high:
            log.info("Governor: no high-priority recommendations, skipping")
            return None

        rec = high[0]
        spec = {
            "problem":        rec.get("problem", ""),
            "behavior_chain": rec.get("behavior_chain", ""),
            "observation":    rec.get("observation", ""),
            "expected":       rec.get("expected", ""),
            "summary":        rec.get("summary", ""),
            "importance":     rec.get("importance", ""),
        }
        task_id = self.db.create_task(
            action=rec.get("action", ""),
            reason=rec.get("reason", ""),
            priority=rec.get("priority", "high"),
            spec=spec,
            source="auto",
        )
        log.info(f"Governor: created task #{task_id}: {rec.get('summary', '')}")
        return self.execute_task(task_id)

    def execute_task(self, task_id: int) -> dict:
        """Execute task by ID — used by both auto and manual paths."""
        task = self.db.get_task(task_id)
        if not task:
            log.error(f"Governor: task #{task_id} not found")
            return {}

        spec = task.get("spec", {})
        prompt = TASK_PROMPT_TEMPLATE.format(
            problem=spec.get("problem", ""),
            behavior_chain=spec.get("behavior_chain", ""),
            observation=spec.get("observation", ""),
            expected=spec.get("expected", ""),
            action=task.get("action", ""),
            reason=task.get("reason", ""),
        )

        now = datetime.now(timezone.utc).isoformat()
        self.db.update_task(task_id, status="running", started_at=now)
        log.info(f"Governor: executing task #{task_id}")

        try:
            result = subprocess.run(
                ["claude", "--dangerously-skip-permissions", "--print", prompt],
                capture_output=True,
                text=True,
                timeout=CLAUDE_TIMEOUT,
                cwd="/orchestrator",
            )
            output = result.stdout.strip() or result.stderr.strip() or "(no output)"
            status = "done" if result.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            output = f"timeout after {CLAUDE_TIMEOUT}s"
            status = "failed"
        except FileNotFoundError:
            output = "claude CLI not found"
            status = "failed"
            log.error("Governor: claude CLI not found in PATH")
        except Exception as e:
            output = str(e)
            status = "failed"

        finished = datetime.now(timezone.utc).isoformat()
        self.db.update_task(task_id, status=status, output=output, finished_at=finished)
        log.info(f"Governor: task #{task_id} {status}")
        return self.db.get_task(task_id)
