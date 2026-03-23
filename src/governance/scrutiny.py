"""Scrutinizer — cognitive mode classification + blast radius estimation + scrutiny审查."""
import logging

from src.storage.events_db import EventsDB
from src.core.llm_router import get_router
from src.governance.context.prompts import SCRUTINY_PROMPT, SECOND_OPINION_MODEL

log = logging.getLogger(__name__)


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


def _parse_scrutiny_verdict(text: str) -> tuple[bool, str]:
    """Parse VERDICT and REASON from scrutiny model output."""
    approved = "VERDICT: APPROVE" in text
    reason_line = next((l for l in text.splitlines() if l.startswith("REASON:")), "")
    reason = reason_line.replace("REASON:", "").strip() or text[:80]
    return approved, reason


def _resolve_project_cwd(project_name: str, fallback_cwd: str = "") -> str:
    """Resolve a project name to a working directory path."""
    import os
    from pathlib import Path
    if fallback_cwd:
        return fallback_cwd
    from src.core.project_registry import resolve_project
    resolved = resolve_project(project_name)
    if resolved:
        return resolved
    return os.environ.get("ORCHESTRATOR_ROOT", str(Path(__file__).parent.parent))


class Scrutinizer:
    """门下省审查：认知模式分类 + 爆炸半径估算 + LLM 交叉验证。"""

    def __init__(self, db: EventsDB):
        self.db = db

    def scrutinize(self, task_id: int, task: dict) -> tuple[bool, str]:
        """门下省审查。LOW/MEDIUM 单模型审查，HIGH 双模型交叉验证。"""
        spec = task.get("spec", {})
        project_name = spec.get("project", "orchestrator")
        task_cwd = _resolve_project_cwd(project_name, spec.get("cwd", ""))

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

        is_high_risk = blast_radius.startswith("HIGH")

        try:
            # First opinion (primary model via router)
            text1 = get_router().generate(prompt, task_type="scrutiny")
            approved1, reason1 = _parse_scrutiny_verdict(text1)

            if not is_high_risk:
                log.info(f"Scrutinizer: scrutiny #{task_id} → {'APPROVE' if approved1 else 'REJECT'}: {reason1}")
                return approved1, reason1

            # HIGH risk: get second opinion from a different model
            log.info(f"Scrutinizer: HIGH risk task #{task_id}, requesting second opinion")
            try:
                from src.core.config import get_anthropic_client
                client = get_anthropic_client()
                resp = client.messages.create(
                    model=SECOND_OPINION_MODEL,
                    max_tokens=256,
                    messages=[{"role": "user", "content": prompt}],
                )
                text2 = resp.content[0].text if resp.content else ""
                approved2, reason2 = _parse_scrutiny_verdict(text2)
            except Exception as e2:
                log.warning(f"Scrutinizer: second opinion failed ({e2}), using first opinion only")
                return approved1, reason1

            # Cross-validate
            if approved1 and approved2:
                log.info(f"Scrutinizer: scrutiny #{task_id} HIGH → APPROVE (both models agree)")
                return True, f"双审通过：{reason1}"
            elif not approved1 and not approved2:
                log.info(f"Scrutinizer: scrutiny #{task_id} HIGH → REJECT (both models agree)")
                return False, f"双审驳回：{reason1} / {reason2}"
            else:
                dissent = f"模型分歧 [M1:{'通过' if approved1 else '驳回'}={reason1}] [M2:{'通过' if approved2 else '驳回'}={reason2}]"
                log.warning(f"Scrutinizer: scrutiny #{task_id} HIGH → DISAGREEMENT, blocking: {dissent}")
                self.db.write_log(f"门下省分歧：#{task_id} {dissent}", "WARNING", "governor")
                return False, f"需人工决定：{dissent}"

        except Exception as e:
            log.warning(f"Scrutinizer: scrutiny failed ({e}), defaulting to APPROVE")
            return True, f"审查异常，默认放行：{e}"
