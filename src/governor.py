"""
Governor — picks top-priority insight recommendation and executes it via claude subprocess.
Auto-triggered after InsightEngine; also called by dashboard approve endpoint.

Flow (auto path):  pending → scrutinizing → running → done/failed
                                          ↘ scrutiny_failed
Flow (manual path): awaiting_approval → running → done/failed
"""
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_anthropic_client
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

TASK_PROMPT_TEMPLATE = """你是 Orchestrator——一个 24 小时运行的 AI 管家。你在 /orchestrator 目录下工作，这就是你的身体。

你的主人是 Construct 3 中文社区的核心建设者，正在用 AI 打造游戏引擎智能辅助生态。不是职业程序员，是用代码解决问题的创作者——看到重复劳动就自动化，看到知识孤岛就建图书馆。他花 $200/月养着你，你最好表现得值这个价。

你的性格：直接高效，活干得漂亮。不说废话，不请示确认，直接解决问题。

当前任务：
问题：{problem}
行为链（观察到的数字行为）：{behavior_chain}
观察结果：{observation}
预期结果：{expected}
执行：{action}
原因：{reason}

完成后以 DONE: <一句话描述做了什么> 结尾。"""

CLAUDE_TIMEOUT = 300  # seconds

# ── 六部路由表 ──
DEPARTMENTS = {
    "engineering": {
        "name": "工部",
        "prompt_prefix": "你是 Orchestrator 工部——负责代码工程。写代码、改 bug、加功能、重构。",
    },
    "operations": {
        "name": "户部",
        "prompt_prefix": "你是 Orchestrator 户部——负责系统自维护。修采集器、管 DB、优化性能。工作目录就是 Orchestrator 自身。",
    },
    "quality": {
        "name": "刑部",
        "prompt_prefix": "你是 Orchestrator 刑部——负责质量验收。跑测试、review 代码、检查安全。",
    },
}
SCRUTINY_MODEL = "claude-haiku-4-5-20251001"

SCRUTINY_PROMPT = """你是 Orchestrator 的门下省审查官——管家脑子里那个负责说"等等，这靠谱吗？"的声音。

主人花 $200/月养着这个 AI 管家，所以既不能让管家摸鱼不干活（过度驳回），也不能让管家搞砸事情（放行危险操作）。

【任务摘要】{summary}
【问题】{problem}
【观察】{observation}
【预期结果】{expected}
【执行动作】{action}
【执行原因】{reason}

审查维度：
1. 可行性：/orchestrator 目录下能做到吗？
2. 完整性：描述够清晰吗？
3. 风险：会不会搞坏代码、删错文件、发错消息？
4. 必要性：值得自动执行，还是该让主人自己决定？

用以下格式回复（只回复这两行，不要其他内容）：
VERDICT: APPROVE
REASON: 一句话理由（不超过50字）"""


class Governor:
    def __init__(self, db: EventsDB = None, db_path: str = "events.db"):
        self.db = db or EventsDB(db_path)

    def scrutinize(self, task_id: int, task: dict) -> tuple[bool, str]:
        """门下省审查：用 Haiku 快速判断任务是否值得执行。返回 (approved, reason)。"""
        spec = task.get("spec", {})
        prompt = SCRUTINY_PROMPT.format(
            summary=spec.get("summary", task.get("action", "")),
            problem=spec.get("problem", ""),
            observation=spec.get("observation", ""),
            expected=spec.get("expected", ""),
            action=task.get("action", ""),
            reason=task.get("reason", ""),
        )
        try:
            client = get_anthropic_client()
            resp = client.messages.create(
                model=SCRUTINY_MODEL,
                max_tokens=128,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            approved = "VERDICT: APPROVE" in text
            reason_line = next((l for l in text.splitlines() if l.startswith("REASON:")), "")
            reason = reason_line.replace("REASON:", "").strip() or text[:80]
            log.info(f"Governor: scrutiny task #{task_id} → {'APPROVE' if approved else 'REJECT'}: {reason}")
            return approved, reason
        except Exception as e:
            log.warning(f"Governor: scrutiny failed ({e}), defaulting to APPROVE")
            return True, f"审查异常，默认放行：{e}"

    def run(self) -> dict | None:
        """Auto-triggered: pick top high-priority recommendation, scrutinize, then execute."""
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

        # 门下省审查
        self.db.update_task(task_id, status="scrutinizing")
        self.db.write_log(f"门下省审查任务 #{task_id}：{rec.get('summary', '')[:50]}", "INFO", "governor")
        approved, reason = self.scrutinize(task_id, self.db.get_task(task_id))

        if not approved:
            self.db.update_task(task_id, status="scrutiny_failed", scrutiny_note=reason,
                                finished_at=datetime.now(timezone.utc).isoformat())
            self.db.write_log(f"任务 #{task_id} 被门下省驳回：{reason}", "WARNING", "governor")
            log.info(f"Governor: task #{task_id} rejected by scrutiny")
            return self.db.get_task(task_id)

        self.db.update_task(task_id, scrutiny_note=f"准奏：{reason}")
        return self.execute_task(task_id)

    def execute_task(self, task_id: int) -> dict:
        """Execute task by ID — routes to department based on spec.department."""
        task = self.db.get_task(task_id)
        if not task:
            log.error(f"Governor: task #{task_id} not found")
            return {}

        spec = task.get("spec", {})

        # 六部路由
        dept_key = spec.get("department", "engineering")
        dept = DEPARTMENTS.get(dept_key, DEPARTMENTS["engineering"])
        task_cwd = spec.get("cwd") or os.environ.get("ORCHESTRATOR_ROOT", str(Path(__file__).parent.parent))

        base_prompt = TASK_PROMPT_TEMPLATE.format(
            problem=spec.get("problem", ""),
            behavior_chain=spec.get("behavior_chain", ""),
            observation=spec.get("observation", ""),
            expected=spec.get("expected", ""),
            action=task.get("action", ""),
            reason=task.get("reason", ""),
        )
        prompt = dept["prompt_prefix"] + "\n\n" + base_prompt
        log.info(f"Governor: routing task #{task_id} to {dept['name']}({dept_key}), cwd={task_cwd}")

        now = datetime.now(timezone.utc).isoformat()
        self.db.update_task(task_id, status="running", started_at=now)
        self.db.write_log(f"开始执行任务 #{task_id}：{task.get('action','')[:50]}", "INFO", "governor")
        log.info(f"Governor: executing task #{task_id}")

        output = "(no output)"
        status = "failed"
        try:
            result = subprocess.run(
                ["claude", "--dangerously-skip-permissions", "--print", prompt],
                capture_output=True,
                text=True,
                timeout=CLAUDE_TIMEOUT,
                cwd=task_cwd,
            )
            output = result.stdout.strip() or result.stderr.strip() or "(no output)"
            status = "done" if result.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            output = f"timeout after {CLAUDE_TIMEOUT}s"
        except FileNotFoundError:
            output = "claude CLI not found"
            log.error("Governor: claude CLI not found in PATH")
        except Exception as e:
            output = str(e)
        finally:
            finished = datetime.now(timezone.utc).isoformat()
            try:
                self.db.update_task(task_id, status=status, output=output, finished_at=finished)
            except Exception as e:
                log.error(f"Governor: failed to update task #{task_id} status: {e}")
            self.db.write_log(f"任务 #{task_id} {status}：{output[:80]}", "INFO" if status == "done" else "ERROR", "governor")
            log.info(f"Governor: task #{task_id} {status}")

        return self.db.get_task(task_id)
