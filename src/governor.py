"""
Governor — picks top-priority insight recommendation and executes it via claude subprocess.
Auto-triggered after InsightEngine; also called by dashboard approve endpoint.

Flow (auto path):  pending → scrutinizing → running → done/failed
                                          ↘ scrutiny_failed
Flow (manual path): awaiting_approval → running → done/failed
"""
import json
import logging
import os
import subprocess
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.storage.events_db import EventsDB
from src.llm_router import get_router

log = logging.getLogger(__name__)

TASK_PROMPT_TEMPLATE = """你是 Orchestrator——一个 24 小时运行的 AI 管家。你当前在 {cwd} 目录下工作。

你的主人是 Construct 3 中文社区的核心建设者，正在用 AI 打造游戏引擎智能辅助生态。不是职业程序员，是用代码解决问题的创作者——看到重复劳动就自动化，看到知识孤岛就建图书馆。他花 $200/月养着你，你最好表现得值这个价。

你的性格：直接高效，活干得漂亮。不说废话，不请示确认，直接解决问题。

当前任务：
项目：{project}
问题：{problem}
行为链（观察到的数字行为）：{behavior_chain}
观察结果：{observation}
预期结果：{expected}
执行：{action}
原因：{reason}

完成后：
1. 如果修改了代码文件，用 git add 和 git commit 提交（commit message 用英文，简洁描述改了什么）
2. 以 DONE: <一句话描述做了什么> 结尾。"""

CLAUDE_TIMEOUT = 300  # seconds
STALE_THRESHOLD = CLAUDE_TIMEOUT + 120  # seconds — if a task is "running" longer than this, it's a zombie
MAX_CONCURRENT = 3  # 最多同时跑几个 sub-agent

# ── 六部路由表 ──
DEPARTMENTS = {
    "engineering": {
        "name": "工部",
        "prompt_prefix": """你是 Orchestrator 工部——代码工程部门。

【身份】动手干活的实施者。写代码、改 bug、加功能、重构、优化性能。
【行为准则】
- 先读懂现有代码再改，不要凭猜测动手
- 改完必须能跑：不引入语法错误、不破坏现有接口
- commit message 用英文，简洁说明改了什么（feat/fix/refactor 前缀）
- 如果任务涉及多个文件，逐个确认改动的一致性
【红线】
- 不删不理解的代码。不确定的加 TODO 注释而不是删除
- 不引入新依赖，除非任务明确要求
- 不碰 .env、credentials、密钥等敏感文件
【完成标准】代码能运行，改动已 commit，输出 DONE: <一句话>""",
        "tools": "Bash,Read,Edit,Write,Glob,Grep",
    },
    "operations": {
        "name": "户部",
        "prompt_prefix": """你是 Orchestrator 户部——系统运维部门。

【身份】管家中的管家。负责 Orchestrator 自身的采集器修复、DB 管理、性能优化、数据清理。
【行为准则】
- 修复前先诊断：看日志、查错误率、量化问题严重程度
- 每次操作前检查磁盘/DB 大小等关键指标
- 优化要有数据对比：改之前多少，改之后多少
- 清理数据前确认保留策略（默认保留 30 天）
【红线】
- 不删除 events.db 中未过期的数据
- 不修改采集频率到 5 分钟以下（API 限流风险）
- 不重启容器，除非确认无其他任务在跑
【完成标准】问题已修复且指标恢复正常，输出修复前后的对比数据""",
        "tools": "Bash,Read,Edit,Write,Glob,Grep",
    },
    "protocol": {
        "name": "礼部",
        "prompt_prefix": """你是 Orchestrator 礼部——注意力审计部门。

【身份】记忆守护者。扫描项目中被遗忘的 TODO、未关闭的 issue、中断的计划、过时的文档。
【行为准则】
- 只分析不修改。输出发现清单，不自行修复
- 按紧急程度分级：🔴 阻塞性遗留 / 🟡 应处理 / 💭 可忽略
- 附上具体文件路径和行号，方便定位
- 关联上下文：这个 TODO 是谁留的、什么时候留的、为什么还没解决
【红线】
- 不修改任何文件
- 不对代码质量做主观评价（那是刑部的活）
【完成标准】输出结构化的遗留问题清单，按优先级排序""",
        "tools": "Read,Glob,Grep",
    },
    "security": {
        "name": "兵部",
        "prompt_prefix": """你是 Orchestrator 兵部——安全防御部门。

【身份】安全哨兵。检查备份完整性、数据一致性、权限配置、敏感信息泄露。
【行为准则】
- 检查 .env / config 文件是否有硬编码的密钥或 token
- 检查 git history 中是否有意外提交的敏感信息
- 验证文件权限是否合理（数据库文件不应该 world-readable）
- 检查依赖是否有已知漏洞（如有 requirements.txt 则审查）
【红线】
- 只报告不修复（修复是工部的活，你负责发现）
- 不执行任何可能泄露敏感信息的命令（不 cat .env，不 echo token）
- 不访问外部网络
【完成标准】输出安全审计报告，每项发现标注风险等级（Critical/High/Medium/Low）""",
        "tools": "Bash,Read,Glob,Grep",
    },
    "quality": {
        "name": "刑部",
        "prompt_prefix": """你是 Orchestrator 刑部——质量验收部门。

【身份】代码法官。Review 代码质量、跑测试、检查逻辑错误、验证最近改动是否引入问题。
【行为准则】
- Review 聚焦：正确性 > 安全性 > 可维护性 > 性能。不纠结风格
- 发现问题按严重程度标注：🔴 必须修（逻辑错误/数据丢失）/ 🟡 建议改 / 💭 可选
- 如果有测试，先跑测试再 review
- 检查最近 commit 的 diff，关注边界条件和错误处理
【红线】
- 只读不写。发现问题写报告，不自行修改代码
- 不因个人偏好否定可工作的代码
【完成标准】输出 review 报告，列出发现的问题和建议，附文件路径和行号""",
        "tools": "Bash,Read,Glob,Grep",
    },
    "personnel": {
        "name": "吏部",
        "prompt_prefix": """你是 Orchestrator 吏部——绩效管理部门。

【身份】绩效考官。监控各采集器、分析器、Governor 任务的健康状态和执行效率。
【行为准则】
- 用数据说话：成功率、平均耗时、错误频次、最后成功时间
- 对比历史趋势：比昨天/上周好还是差
- 识别模式：哪个采集器总失败？哪类任务耗时最长？失败集中在什么时段？
- 输出结构化绩效报告，不写散文
【红线】
- 不修改任何配置或代码
- 不对"该不该保留某个采集器"做决定（那是主人的事）
【完成标准】输出绩效报告：各组件健康度评分、异常项列表、趋势分析""",
        "tools": "Read,Glob,Grep",
    },
}
SCRUTINY_PROMPT = """你是 Orchestrator 的门下省审查官——管家脑子里那个负责说"等等，这靠谱吗？"的声音。

主人花 $200/月养着这个 AI 管家，所以既不能让管家摸鱼不干活（过度驳回），也不能让管家搞砸事情（放行危险操作）。

【任务摘要】{summary}
【目标项目】{project}
【工作目录】{cwd}
【问题】{problem}
【观察】{observation}
【预期结果】{expected}
【执行动作】{action}
【执行原因】{reason}

审查维度：
1. 可行性：目标工作目录存在吗？任务在该项目范围内可执行吗？
2. 完整性：描述够清晰吗？
3. 风险：会不会搞坏代码、删错文件、发错消息？跨项目操作更需谨慎。
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
        project_name = spec.get("project", "orchestrator")
        task_cwd = spec.get("cwd", "")
        if not task_cwd:
            from src.project_registry import resolve_project
            task_cwd = resolve_project(project_name) or os.environ.get("ORCHESTRATOR_ROOT", "/orchestrator")

        prompt = SCRUTINY_PROMPT.format(
            summary=spec.get("summary", task.get("action", "")),
            project=project_name,
            cwd=task_cwd,
            problem=spec.get("problem", ""),
            observation=spec.get("observation", ""),
            expected=spec.get("expected", ""),
            action=task.get("action", ""),
            reason=task.get("reason", ""),
        )
        try:
            text = get_router().generate(prompt, task_type="scrutiny")
            approved = "VERDICT: APPROVE" in text
            reason_line = next((l for l in text.splitlines() if l.startswith("REASON:")), "")
            reason = reason_line.replace("REASON:", "").strip() or text[:80]
            log.info(f"Governor: scrutiny task #{task_id} → {'APPROVE' if approved else 'REJECT'}: {reason}")
            return approved, reason
        except Exception as e:
            log.warning(f"Governor: scrutiny failed ({e}), defaulting to APPROVE")
            return True, f"审查异常，默认放行：{e}"

    def _reap_zombie_tasks(self):
        """收割僵尸任务：如果 running/scrutinizing 状态超过 STALE_THRESHOLD，标记为 failed。
        防止进程崩溃后僵尸任务永久阻塞管线。支持并行模式下的多任务收割。"""
        running = self.db.get_running_tasks()
        if not running:
            return
        for stale in running:
            started = stale.get("started_at")
            if not started:
                self.db.update_task(stale["id"], status="failed",
                                    output="zombie: never started, cleaned up",
                                    finished_at=datetime.now(timezone.utc).isoformat())
                self.db.write_log(f"收割僵尸任务 #{stale['id']}（无启动时间）", "WARNING", "governor")
                log.warning(f"Governor: reaped zombie task #{stale['id']} (no started_at)")
                continue
            try:
                started_dt = datetime.fromisoformat(started)
                age = (datetime.now(timezone.utc) - started_dt).total_seconds()
            except (ValueError, TypeError):
                age = STALE_THRESHOLD + 1
            if age > STALE_THRESHOLD:
                self.db.update_task(stale["id"], status="failed",
                                    output=f"zombie: stuck for {int(age)}s, reaped by governor",
                                    finished_at=datetime.now(timezone.utc).isoformat())
                self.db.write_log(f"收割僵尸任务 #{stale['id']}（卡了 {int(age)}s）", "WARNING", "governor")
                log.warning(f"Governor: reaped zombie task #{stale['id']} (stuck {int(age)}s)")

    def run(self) -> dict | None:
        """Auto-triggered: pick top high-priority recommendation, scrutinize, then execute.
        支持并行：如果正在运行的任务数 < MAX_CONCURRENT，可以继续派发新任务。"""
        self._reap_zombie_tasks()

        running_count = self.db.count_running_tasks()
        if running_count >= MAX_CONCURRENT:
            log.info(f"Governor: {running_count} tasks running (max {MAX_CONCURRENT}), skipping")
            return None

        insights = self.db.get_latest_insights()
        recs = insights.get("recommendations", [])
        high = [r for r in recs if r.get("priority") == "high"]
        if not high:
            log.info("Governor: no high-priority recommendations, skipping")
            return None

        rec = high[0]
        spec = {
            "department":     rec.get("department", "engineering"),
            "project":        rec.get("project", "orchestrator"),
            "cwd":            rec.get("cwd", ""),
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

    def execute_task_async(self, task_id: int):
        """在后台线程中执行任务，不阻塞调用方。"""
        t = threading.Thread(
            target=self.execute_task,
            args=(task_id,),
            name=f"governor-task-{task_id}",
            daemon=True,
        )
        t.start()
        log.info(f"Governor: task #{task_id} dispatched to background thread")
        return t

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

        # 项目路由
        project_name = spec.get("project", "orchestrator")
        task_cwd = spec.get("cwd")
        if not task_cwd:
            from src.project_registry import resolve_project
            task_cwd = resolve_project(project_name)
        if not task_cwd:
            task_cwd = os.environ.get("ORCHESTRATOR_ROOT", str(Path(__file__).parent.parent))

        base_prompt = TASK_PROMPT_TEMPLATE.format(
            cwd=task_cwd,
            project=project_name,
            problem=spec.get("problem", ""),
            behavior_chain=spec.get("behavior_chain", ""),
            observation=spec.get("observation", ""),
            expected=spec.get("expected", ""),
            action=task.get("action", ""),
            reason=task.get("reason", ""),
        )
        prompt = dept["prompt_prefix"] + "\n\n" + base_prompt
        log.info(f"Governor: routing task #{task_id} to {dept['name']}({dept_key}), project={project_name}, cwd={task_cwd}")

        now = datetime.now(timezone.utc).isoformat()
        self.db.update_task(task_id, status="running", started_at=now)
        self.db.write_log(f"开始执行任务 #{task_id}（{project_name}）：{task.get('action','')[:50]}", "INFO", "governor")
        log.info(f"Governor: executing task #{task_id}")

        output = "(no output)"
        status = "failed"
        try:
            tools = dept.get("tools", "")
            cmd = ["claude", "--dangerously-skip-permissions", "--print",
                   "--output-format", "json"]
            if tools:
                cmd.extend(["--tools", tools])
            cmd.append("-")  # read prompt from stdin

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=CLAUDE_TIMEOUT,
                cwd=task_cwd,
                input=prompt,
            )
            raw = result.stdout.strip() or result.stderr.strip() or "(no output)"
            # Parse JSON output for result text
            try:
                data = json.loads(raw)
                output = data.get("result", raw[:2000])
                status = "done" if not data.get("is_error") else "failed"
            except (json.JSONDecodeError, TypeError):
                output = raw[:2000]
                status = "done" if result.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            output = f"timeout after {CLAUDE_TIMEOUT}s"
        except FileNotFoundError:
            output = "claude CLI not found"
            log.error("Governor: claude CLI not found in PATH")
        except Exception as e:
            output = str(e)
        finally:
            # 视觉验证：如果 sub-agent 留下了截图，用 vision 模型检查
            if status == "done":
                verification = self._visual_verify(task_id, task_cwd, spec)
                if verification:
                    output = f"{output}\n\n[visual_verify] {verification}"

            finished = datetime.now(timezone.utc).isoformat()
            try:
                self.db.update_task(task_id, status=status, output=output, finished_at=finished)
            except Exception as e:
                log.error(f"Governor: failed to update task #{task_id} status: {e}")
            self.db.write_log(f"任务 #{task_id}（{project_name}）{status}：{output[:80]}", "INFO" if status == "done" else "ERROR", "governor")
            log.info(f"Governor: task #{task_id} {status}")

        return self.db.get_task(task_id)

    def _visual_verify(self, task_id: int, task_cwd: str, spec: dict) -> str:
        """可选视觉验证：检查约定路径是否有截图，有则用 vision 模型验证。"""
        verify_dir = Path(task_cwd) / ".governor-verify"
        if not verify_dir.exists():
            return ""

        images = list(verify_dir.glob("*.png")) + list(verify_dir.glob("*.jpg"))
        if not images:
            return ""

        image_paths = [str(p) for p in images[:3]]  # 最多验证 3 张
        expected = spec.get("expected", "任务完成")

        try:
            result = get_router().generate(
                f"这是任务执行后的截图。预期结果是：{expected}\n\n"
                f"请判断截图是否符合预期，用一句话回答。",
                task_type="vision",
                images=image_paths,
            )
            if result:
                log.info(f"Governor: visual verify task #{task_id}: {result[:80]}")
                # 清理验证截图
                for p in images:
                    p.unlink(missing_ok=True)
                verify_dir.rmdir()
            return result
        except Exception as e:
            log.warning(f"Governor: visual verify failed: {e}")
            return ""
