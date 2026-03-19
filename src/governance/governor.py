"""
Governor — picks top-priority insight recommendation and executes it via Agent SDK.
Auto-triggered after InsightEngine; also called by dashboard approve endpoint.

Flow (auto path):  pending → scrutinizing → running → done/failed
                                          ↘ scrutiny_failed
Flow (manual path): awaiting_approval → running → done/failed
"""
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

import anyio
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

from src.storage.events_db import EventsDB
from src.core.llm_router import get_router
from src.governance.run_logger import append_run_log, load_recent_runs, format_runs_for_context
from src.governance.context_assembler import assemble_context

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
MAX_AGENT_TURNS = 25  # Agent SDK 最大交互轮数（防止无限循环）

# ── Parallel dispatch scenarios ──
# Defines which department combinations can run in parallel for common workflows.
# Governor.run_parallel_scenario() uses this to dispatch multi-department tasks at once.
PARALLEL_SCENARIOS = {
    "full_audit": {
        "description": "Full system audit: security + quality + protocol in parallel",
        "departments": ["security", "quality", "protocol"],
    },
    "code_and_review": {
        "description": "Engineering fix + quality review on different projects",
        "departments": ["engineering", "quality"],
    },
    "system_health": {
        "description": "Operations health check + personnel performance report",
        "departments": ["operations", "personnel"],
    },
    "deep_scan": {
        "description": "Protocol debt scan + security audit + personnel metrics",
        "departments": ["protocol", "security", "personnel"],
    },
    "full_pipeline": {
        "description": "All read-only departments scan simultaneously",
        "departments": ["protocol", "security", "quality", "personnel"],
    },
}


# ── 认知模式 ──

def classify_cognitive_mode(task: dict) -> str:
    """根据任务特征选择认知模式。

    - direct: 简单任务，直接执行
    - react: 中等复杂，边做边想 (Think-Act-Observe)
    - hypothesis: 诊断类，先假设后验证
    - designer: 大型改动，先设计后实现
    """
    action = (task.get("action") or "").lower()
    spec = task.get("spec", {})
    problem = (spec.get("problem") or "").lower()
    summary = (spec.get("summary") or "").lower()
    combined = f"{action} {problem} {summary}"

    # 诊断类关键词 → hypothesis
    diagnostic_signals = ["为什么", "why", "原因", "cause", "失败率",
                          "不工作", "not working", "异常", "anomaly",
                          "诊断", "diagnose", "排查", "investigate"]
    if any(s in combined for s in diagnostic_signals):
        return "hypothesis"

    # 大型改动 → designer
    designer_signals = ["重构", "refactor", "新增子系统", "redesign", "架构",
                       "architecture", "新模块", "new module", "迁移", "migrate"]
    if any(s in combined for s in designer_signals):
        return "designer"

    # 简单操作 → direct
    simple_signals = ["typo", "改名", "rename", "删除", "清理", "cleanup",
                      "更新版本", "bump", "调整参数", "config", "格式化",
                      "format", "注释", "comment"]
    if any(s in combined for s in simple_signals):
        return "direct"

    # 默认 → react
    return "react"


COGNITIVE_MODE_PROMPTS = {
    "direct": "",  # 简单任务不加额外指令

    "react": """
【思维模式：边做边想 (Think-Act-Observe)】
每完成一个步骤后，先观察结果：
1. 这步做对了吗？有没有意外？
2. 原来的计划还成立吗？需要调整吗？
3. 下一步应该做什么？
不要一口气做完所有事。每步都停下来想。""",

    "hypothesis": """
【思维模式：先诊断后治疗 (Hypothesis-Driven)】
在动手修复之前，必须先完成诊断：
1. 列出 2-3 个可能的原因
2. 说明你认为最可能的是哪个，以及为什么
3. 设计一个验证步骤（不改代码，只检查/测试）
4. 执行验证，确认或推翻假设
5. 假设被确认后才开始修复
如果第一个假设被推翻，不要硬修——换下一个假设重来。""",

    "designer": """
【思维模式：先设计后实现 (Design-First)】
在写任何代码之前，先输出完整的改动方案：
1. 要改哪些文件
2. 每个文件的改动意图（一句话）
3. 改动之间的依赖关系（先改 A 才能改 B）
4. 风险评估：哪个改动最可能出错
方案输出后，逐个文件实现。每改完一个文件确认无误再改下一个。""",
}


def estimate_blast_radius(spec: dict) -> str:
    """评估任务的爆炸半径——出错时影响范围有多大。"""
    problem = (spec.get("problem") or "").lower()
    action = (spec.get("action") or "").lower() if spec.get("action") else ""
    combined = f"{problem} {action}"

    high_risk = ["schema", "migration", "database", "events.db", "docker",
                 "重启", "restart", "删除", "delete", "清理数据", "credentials", "密钥"]
    if any(k in combined for k in high_risk):
        return "HIGH — 数据/基础设施级别，不可逆或难以恢复"

    medium_risk = ["重构", "refactor", "多个文件", "接口", "api", "config"]
    if any(k in combined for k in medium_risk):
        return "MEDIUM — 多文件改动，可能引入回归"

    return "LOW — 局部改动，容易回滚"


def _in_async_context() -> bool:
    """检测当前是否已在 async event loop 中（线程池 vs 主线程）。"""
    try:
        import sniffio
        sniffio.current_async_library()
        return True
    except (ImportError, sniffio.AsyncLibraryNotFoundError):
        return False

# ── 六部路由表 ──
DEPARTMENTS = {
    "engineering": {
        "name": "工部",
        "skill_path": "departments/engineering/SKILL.md",
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
        "skill_path": "departments/operations/SKILL.md",
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
        "skill_path": "departments/protocol/SKILL.md",
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
        "skill_path": "departments/security/SKILL.md",
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
        "skill_path": "departments/quality/SKILL.md",
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
【完成标准】
1. 输出 review 报告，列出发现的问题和建议，附文件路径和行号
2. 最后一行必须输出裁决（二选一）：
   VERDICT: PASS — 代码质量合格，无阻塞性问题
   VERDICT: FAIL — 存在 🔴 级别问题，需工部返工。附一句话说明原因""",
        "tools": "Bash,Read,Glob,Grep",
    },
    "personnel": {
        "name": "吏部",
        "skill_path": "departments/personnel/SKILL.md",
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

def load_department(name: str) -> str | None:
    """从 departments/{name}/SKILL.md 加载部门 prompt。文件不存在时返回 None（fallback 到 DEPARTMENTS dict）。"""
    skill_path = Path(__file__).parent.parent / "departments" / name / "SKILL.md"
    try:
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")
    except Exception as e:
        log.warning(f"Governor: failed to load SKILL.md for {name}: {e}")
    return None


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
【认知模式】{cognitive_mode}
【爆炸半径】{blast_radius}

审查维度：
1. 可行性：目标工作目录存在吗？任务在该项目范围内可执行吗？
2. 完整性：描述够清晰吗？
3. 风险：会不会搞坏代码、删错文件、发错消息？跨项目操作更需谨慎。
4. 必要性：值得自动执行，还是该让主人自己决定？
5. 模式匹配：认知模式选对了吗？（direct/react/hypothesis/designer）
6. 逆推：如果执行结果与预期相反，最坏情况是什么？

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
            from src.core.project_registry import resolve_project
            task_cwd = resolve_project(project_name) or os.environ.get("ORCHESTRATOR_ROOT", "/orchestrator")

        cognitive_mode = classify_cognitive_mode(task)
        blast_radius = estimate_blast_radius(spec)
        prompt = SCRUTINY_PROMPT.format(
            summary=spec.get("summary", task.get("action", "")),
            project=project_name,
            cwd=task_cwd,
            problem=spec.get("problem", ""),
            observation=spec.get("observation", ""),
            expected=spec.get("expected", ""),
            action=task.get("action", ""),
            reason=task.get("reason", ""),
            cognitive_mode=cognitive_mode,
            blast_radius=blast_radius,
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
        """Auto-triggered: pick one recommendation, scrutinize, then execute.
        Legacy single-task method — use run_batch() for parallel dispatch."""
        results = self.run_batch(max_dispatch=1)
        return results[0] if results else None

    def run_batch(self, max_dispatch: int = MAX_CONCURRENT) -> list[dict]:
        """Pick multiple high-priority recommendations and dispatch in parallel.

        Rules:
        - Respects MAX_CONCURRENT global limit
        - Same department + same project/cwd cannot run in parallel (file conflict risk)
        - Same department + different projects CAN run in parallel
        - Each task goes through scrutiny before dispatch
        - Returns list of dispatched task dicts
        """
        self._reap_zombie_tasks()

        running_count = self.db.count_running_tasks()
        slots = min(max_dispatch, MAX_CONCURRENT - running_count)
        if slots <= 0:
            log.info(f"Governor: {running_count} tasks running (max {MAX_CONCURRENT}), skipping")
            return []

        # Build set of busy (department, cwd) pairs
        running_tasks = self.db.get_running_tasks()
        busy_slots = set()  # (department, cwd) tuples
        for t in running_tasks:
            try:
                spec = json.loads(t.get("spec", "{}"))
                dept = spec.get("department", "")
                cwd = spec.get("cwd", "") or spec.get("project", "")
                busy_slots.add((dept, cwd))
            except (json.JSONDecodeError, TypeError):
                pass

        insights = self.db.get_latest_insights()
        recs = insights.get("recommendations", [])
        high = [r for r in recs if r.get("priority") == "high"]
        if not high:
            log.info("Governor: no high-priority recommendations, skipping")
            return []

        dispatched = []
        dispatched_slots = set()

        for rec in high:
            if len(dispatched) >= slots:
                break

            dept = rec.get("department", "engineering")
            cwd = rec.get("cwd", "") or rec.get("project", "")
            slot_key = (dept, cwd)

            # Skip if same department + same project is already running
            if slot_key in busy_slots or slot_key in dispatched_slots:
                log.info(f"Governor: skipping rec for {dept}@{cwd} (slot busy)")
                continue

            spec = {
                "department":     dept,
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
            log.info(f"Governor: created task #{task_id}: {rec.get('summary', '')} [{dept}]")

            # Cognitive mode
            task_dict = self.db.get_task(task_id)
            spec["cognitive_mode"] = classify_cognitive_mode(task_dict)
            self.db.update_task(task_id, spec=json.dumps(spec, ensure_ascii=False, default=str))

            # Scrutiny
            self.db.update_task(task_id, status="scrutinizing")
            self.db.write_log(f"门下省审查任务 #{task_id}：{rec.get('summary', '')[:50]}", "INFO", "governor")
            approved, reason = self.scrutinize(task_id, self.db.get_task(task_id))

            if not approved:
                self.db.update_task(task_id, status="scrutiny_failed", scrutiny_note=reason,
                                    finished_at=datetime.now(timezone.utc).isoformat())
                self.db.write_log(f"任务 #{task_id} 被门下省驳回：{reason}", "WARNING", "governor")
                log.info(f"Governor: task #{task_id} rejected by scrutiny")
                continue

            self.db.update_task(task_id, scrutiny_note=f"准奏：{reason}")

            # Dispatch async — don't block, let departments run in parallel
            self.execute_task_async(task_id)
            dispatched_slots.add(slot_key)
            dispatched.append(self.db.get_task(task_id))

        if dispatched:
            slot_list = ", ".join(f"{d}@{c}" for d, c in dispatched_slots)
            self.db.write_log(
                f"Governor batch: dispatched {len(dispatched)} tasks to [{slot_list}]",
                "INFO", "governor"
            )
        return dispatched

    def run_parallel_scenario(self, scenario_name: str, project: str = "orchestrator",
                              cwd: str = "", action_prefix: str = "") -> list[dict]:
        """Dispatch a predefined parallel scenario — multiple departments at once.

        Args:
            scenario_name: Key from PARALLEL_SCENARIOS (e.g. "full_audit")
            project: Target project name
            cwd: Working directory (auto-resolved if empty)
            action_prefix: Optional prefix for task actions

        Returns:
            List of dispatched task dicts
        """
        scenario = PARALLEL_SCENARIOS.get(scenario_name)
        if not scenario:
            available = ", ".join(PARALLEL_SCENARIOS.keys())
            log.error(f"Governor: unknown scenario '{scenario_name}'. Available: {available}")
            return []

        self._reap_zombie_tasks()

        running_count = self.db.count_running_tasks()
        slots = MAX_CONCURRENT - running_count
        if slots <= 0:
            log.info(f"Governor: no slots available for scenario '{scenario_name}'")
            return []

        # Resolve cwd
        if not cwd:
            from src.core.project_registry import resolve_project
            cwd = resolve_project(project) or os.environ.get("ORCHESTRATOR_ROOT", ".")

        departments = scenario["departments"][:slots]  # Don't exceed available slots
        dispatched = []

        for dept in departments:
            action = f"{action_prefix}{scenario['description']}" if action_prefix else scenario["description"]
            spec = {
                "department": dept,
                "project": project,
                "cwd": cwd,
                "problem": f"Parallel scenario: {scenario_name}",
                "summary": f"{dept} — {scenario['description']}",
            }
            task_id = self.db.create_task(
                action=action,
                reason=f"Parallel scenario dispatch: {scenario_name}",
                priority="medium",
                spec=spec,
                source="auto",
            )

            # Cognitive mode
            task_dict = self.db.get_task(task_id)
            spec["cognitive_mode"] = classify_cognitive_mode(task_dict)
            self.db.update_task(task_id, spec=json.dumps(spec, ensure_ascii=False, default=str))

            # Scrutiny
            self.db.update_task(task_id, status="scrutinizing")
            approved, reason = self.scrutinize(task_id, self.db.get_task(task_id))

            if not approved:
                self.db.update_task(task_id, status="scrutiny_failed", scrutiny_note=reason,
                                    finished_at=datetime.now(timezone.utc).isoformat())
                log.info(f"Governor: scenario task #{task_id} ({dept}) rejected: {reason}")
                continue

            self.db.update_task(task_id, scrutiny_note=f"准奏：{reason}")
            self.execute_task_async(task_id)
            dispatched.append(self.db.get_task(task_id))

        if dispatched:
            dept_list = ", ".join(d["spec"].get("department", "?") if isinstance(d.get("spec"), dict)
                                 else json.loads(d.get("spec", "{}")).get("department", "?")
                                 for d in dispatched)
            self.db.write_log(
                f"Governor scenario '{scenario_name}': dispatched {len(dispatched)} tasks [{dept_list}]",
                "INFO", "governor"
            )
            log.info(f"Governor: scenario '{scenario_name}' dispatched {len(dispatched)} tasks")
        return dispatched

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
            from src.core.project_registry import resolve_project
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
        # 优先从 SKILL.md 加载部门 prompt，fallback 到内置 dict
        skill_content = load_department(dept_key)
        dept_prompt = skill_content if skill_content else dept["prompt_prefix"]

        # 认知模式注入
        cognitive_mode = classify_cognitive_mode(task)
        mode_prompt = COGNITIVE_MODE_PROMPTS.get(cognitive_mode, "")

        # 注入最近执行记录
        recent_runs = load_recent_runs(dept_key, n=5)
        runs_context = format_runs_for_context(recent_runs)

        # 组装最终 prompt: 部门身份 + 认知模式 + 任务 + 执行记录
        prompt = dept_prompt
        if mode_prompt:
            prompt += "\n\n" + mode_prompt
        prompt += "\n\n" + base_prompt
        if runs_context:
            prompt += "\n\n" + runs_context

        # 动态上下文组装（Parlant 模式：只注入任务相关的规则和知识）
        try:
            dynamic_ctx = assemble_context(dept_key, task)
            if dynamic_ctx:
                prompt += "\n\n" + dynamic_ctx
        except Exception as e:
            log.warning(f"Governor: context assembly failed ({e}), continuing without dynamic context")

        log.info(f"Governor: routing task #{task_id} to {dept['name']}({dept_key}), mode={cognitive_mode}, project={project_name}, cwd={task_cwd}")

        now = datetime.now(timezone.utc).isoformat()
        self.db.update_task(task_id, status="running", started_at=now)
        self.db.write_log(f"开始执行任务 #{task_id}（{project_name}）：{task.get('action','')[:50]}", "INFO", "governor")
        log.info(f"Governor: executing task #{task_id}")

        output = "(no output)"
        status = "failed"
        try:
            tools_str = dept.get("tools", "")
            allowed_tools = [t.strip() for t in tools_str.split(",") if t.strip()]

            # Agent SDK 环境准备
            agent_env = {}
            # 清除嵌套会话检测（本地调试 / CI 需要）
            if os.environ.get("CLAUDECODE"):
                agent_env["CLAUDECODE"] = ""
            # Windows 兼容：确保 Agent SDK 能找到 git-bash
            if os.name == "nt" and not os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"):
                git_bash = Path("D:/Program Files/Git/bin/bash.exe")
                if not git_bash.exists():
                    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
                if git_bash.exists():
                    agent_env["CLAUDE_CODE_GIT_BASH_PATH"] = str(git_bash)

            async def _run_agent():
                result_text = ""
                async for message in query(
                    prompt=prompt,
                    options=ClaudeAgentOptions(
                        cwd=task_cwd,
                        allowed_tools=allowed_tools,
                        permission_mode="bypassPermissions",
                        system_prompt=dept_prompt,
                        max_turns=MAX_AGENT_TURNS,
                        **({"env": agent_env} if agent_env else {}),
                    ),
                ):
                    if isinstance(message, ResultMessage):
                        result_text = message.result or ""
                return result_text

            output = anyio.from_thread.run(_run_agent) if _in_async_context() else anyio.run(_run_agent)
            output = output[:2000] if output else "(no output)"
            status = "done" if output and output != "(no output)" else "failed"
        except TimeoutError:
            output = f"timeout after {CLAUDE_TIMEOUT}s"
        except Exception as e:
            output = str(e)[:2000]
            log.error(f"Governor: Agent SDK error for task #{task_id}: {e}")
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

            # 部门执行记忆
            try:
                duration_s = 0
                started_at = task.get("started_at") or now
                try:
                    started_dt = datetime.fromisoformat(started_at)
                    finished_dt = datetime.fromisoformat(finished)
                    duration_s = int((finished_dt - started_dt).total_seconds())
                except (ValueError, TypeError):
                    pass
                # 尝试从 output 中提取 commit hash
                commit_hash = ""
                commit_match = re.search(r'\b([0-9a-f]{7,40})\b', output) if "commit" in output.lower() else None
                if commit_match:
                    commit_hash = commit_match.group(1)
                append_run_log(
                    department=dept_key,
                    task_id=task_id,
                    mode=task.get("source", "auto"),
                    summary=task.get("action", "")[:200],
                    commit=commit_hash,
                    status=status,
                    duration_s=duration_s,
                    notes=output[:200] if status == "failed" else "",
                )
            except Exception as e:
                log.warning(f"Governor: failed to write run-log for task #{task_id}: {e}")

            # 部门协作
            if status == "done":
                if dept_key == "engineering":
                    # 工部完成 → 自动派刑部验收（传入最新 output）
                    task["output"] = output
                    self._dispatch_quality_review(task_id, task, task_cwd, project_name)
                elif dept_key == "quality" and "VERDICT: FAIL" in output:
                    # 刑部验收失败 → 打回工部重做
                    self._dispatch_rework(task_id, task, task_cwd, project_name, output)

        return self.db.get_task(task_id)

    @staticmethod
    def _extract_artifact(task: dict) -> dict:
        """从完成的任务中提取结构化 artifact。"""
        try:
            output = task.get("output") or ""

            # 提取 commit hash（从 output 中找 7-40 位 hex 前面带 commit 关键词的）
            commit_match = re.search(r'(?:commit|committed|提交)[:\s]*([0-9a-f]{7,40})', output, re.IGNORECASE)
            commit = commit_match.group(1) if commit_match else ""

            # 提取改动文件（从 output 中找文件路径模式）
            file_patterns = re.findall(r'(?:src|departments|SOUL|dashboard|scripts|tests)/[\w/.-]+\.\w+', output)
            files_changed = list(set(file_patterns))[:10]  # 去重，最多10个

            # 提取 DONE 行作为 summary
            done_match = re.search(r'DONE:\s*(.+)', output)
            summary = done_match.group(1).strip() if done_match else task.get("action", "")[:100]

            return {
                "task_id": task.get("id", 0),
                "summary": summary,
                "files_changed": files_changed,
                "commit": commit,
                "status": task.get("status", ""),
            }
        except Exception:
            # fallback: 返回最小可用 artifact
            return {
                "task_id": task.get("id", 0),
                "summary": task.get("action", "")[:100],
                "files_changed": [],
                "commit": "",
                "status": task.get("status", ""),
            }

    def _dispatch_quality_review(self, parent_id: int, parent_task: dict, task_cwd: str, project_name: str):
        """工部完成任务后，自动创建刑部验收任务。跳过门下省审查（验收本身就是审查）。"""
        parent_spec = parent_task.get("spec", {})
        parent_action = parent_task.get("action", "")
        # 防止验收链无限循环：如果父任务本身已经是验收任务，不再派生
        if parent_spec.get("department") == "quality":
            return

        # 从工部 output 中提取结构化信息
        artifact = self._extract_artifact(parent_task)
        files_str = ", ".join(artifact["files_changed"]) if artifact["files_changed"] else "未检测到"
        commit_str = artifact["commit"] or "未检测到"

        if artifact["commit"]:
            observation = (
                f"工部执行摘要：{artifact['summary']}\n"
                f"改动文件：{files_str}\n"
                f"Commit: {commit_str}\n\n"
                f"请自行运行 git diff {artifact['commit']}~1..{artifact['commit']} 查看实际代码改动，不要依赖上述摘要做判断。"
            )
        else:
            observation = (
                f"工部执行摘要：{artifact['summary']}\n"
                f"改动文件：{files_str}\n"
                f"Commit: {commit_str}\n\n"
                f"未检测到 commit hash，请运行 git log --oneline -3 查看最近提交，然后用 git diff 查看实际改动。"
            )

        review_spec = {
            "department": "quality",
            "project": project_name,
            "cwd": task_cwd,
            "problem": f"验收工部任务 #{parent_id} 的执行结果",
            "observation": observation,
            "expected": parent_spec.get("expected", "任务正确完成，无引入新问题"),
            "summary": f"刑部验收：{parent_action[:40]}",
        }
        review_id = self.db.create_task(
            action=f"Review 工部任务 #{parent_id} 的代码改动：检查 git diff、跑测试（如有）、确认无逻辑错误",
            reason=f"工部任务 #{parent_id} 已完成，需刑部验收",
            priority="medium",
            spec=review_spec,
            source="auto",
            parent_task_id=parent_id,
        )
        self.db.write_log(f"工部任务 #{parent_id} 完成 → 派刑部验收任务 #{review_id}", "INFO", "governor")
        log.info(f"Governor: dispatched quality review #{review_id} for engineering task #{parent_id}")

    MAX_REWORK = 1  # 最多打回重做 1 次，防止工部↔刑部死循环

    def _dispatch_rework(self, review_task_id: int, review_task: dict,
                         task_cwd: str, project_name: str, review_output: str):
        """刑部验收失败，打回工部重做。追溯原始工部任务，携带刑部反馈。"""
        review_spec = review_task.get("spec", {})
        parent_id = review_task.get("parent_task_id")
        if not parent_id:
            log.warning(f"Governor: review #{review_task_id} has no parent_task_id, skip rework")
            return

        # 查原始工部任务，检查重做次数
        original = self.db.get_task(parent_id)
        if not original:
            return
        original_spec = original.get("spec", {})
        rework_count = original_spec.get("rework_count", 0)
        if rework_count >= self.MAX_REWORK:
            self.db.write_log(
                f"刑部验收任务 #{review_task_id} FAIL，但原任务 #{parent_id} 已重做 {rework_count} 次，不再打回",
                "WARNING", "governor")
            log.warning(f"Governor: task #{parent_id} hit max rework ({rework_count}), not dispatching")
            return

        # 提取刑部的具体问题（优先提取标记行，fallback 到 VERDICT 前的最后 10 行）
        issue_lines = [
            l for l in review_output.splitlines()
            if l.strip().startswith(('\U0001f534', '\U0001f7e1', '[CRITICAL]', '[BUG]', '[WARN]'))
        ]
        if issue_lines:
            feedback = "\n".join(issue_lines[:10])
        else:
            # fallback: VERDICT 行之前的最后 10 行
            feedback_lines = []
            for line in review_output.splitlines():
                if line.startswith("VERDICT:"):
                    break
                feedback_lines.append(line)
            feedback = "\n".join(feedback_lines[-10:])

        rework_spec = {
            "department": "engineering",
            "project": project_name,
            "cwd": task_cwd,
            "problem": f"刑部验收任务 #{review_task_id} 驳回了工部任务 #{parent_id}，需要返工修复",
            "observation": f"刑部反馈：\n{feedback}",
            "expected": original_spec.get("expected", "修复刑部指出的问题"),
            "summary": f"返工：{original.get('action', '')[:30]}（刑部驳回）",
            "rework_count": rework_count + 1,
        }
        rework_id = self.db.create_task(
            action=f"根据刑部反馈修复任务 #{parent_id} 的问题：{feedback[:100]}",
            reason=f"刑部验收 #{review_task_id} FAIL，需返工",
            priority="high",
            spec=rework_spec,
            source="auto",
            parent_task_id=review_task_id,
        )
        self.db.write_log(
            f"刑部验收 #{review_task_id} FAIL → 打回工部，创建返工任务 #{rework_id}（第 {rework_count + 1} 次）",
            "WARNING", "governor")
        log.info(f"Governor: dispatched rework #{rework_id} for failed review #{review_task_id}")

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
