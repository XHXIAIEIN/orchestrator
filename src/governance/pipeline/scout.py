"""
Scout-Synthesize — 编排 agent 不读源码/数据，派 scout 侦察，自己只做综合。

orc-spencer 启发：保护编排层 context window。
Governor 调度层不直接读文件，而是派一个轻量 scout sub-agent 先做侦察，
结果写入 scratchpad，编排层读摘要做决策。

使用场景：
  - 大型代码库中定位问题（先 scout，再决定派哪个部门）
  - 跨项目信息收集（多个 scout 并行，结果汇总）
  - 复杂任务的前置调研
"""
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class ScoutMission:
    """Scout 侦察任务定义。"""
    question: str         # 要回答的问题
    search_scope: str     # 搜索范围（目录/文件 glob）
    max_files: int = 20   # 最多读多少文件
    max_turns: int = 8    # scout 最多交互轮数
    tools: list = None    # scout 可用工具（默认只读）

    def __post_init__(self):
        if self.tools is None:
            self.tools = ["Read", "Glob", "Grep"]


@dataclass
class ScoutReport:
    """Scout 侦察报告。"""
    question: str
    findings: str         # 侦察结果
    files_examined: list   # 查看了哪些文件
    confidence: float     # 0-1 对答案的信心
    scratchpad_path: str = ""  # 完整报告的 scratchpad 路径


# ── Scout Prompt Template ──

SCOUT_PROMPT = """你是一个侦察员（Scout）。你的任务是快速回答一个问题，不需要修改任何代码。

## 问题
{question}

## 搜索范围
{search_scope}

## 规则
1. 只读取文件，不修改任何东西
2. 最多查看 {max_files} 个文件
3. 用简洁的事实回答，不要废话
4. 列出你查看了哪些文件
5. 给出你的信心等级（0-1）

## 输出格式
FINDINGS: <你的发现>
FILES: <file1>, <file2>, ...
CONFIDENCE: <0-1>
"""


def create_scout_spec(mission: ScoutMission, project: str = "orchestrator",
                      cwd: str = "") -> dict:
    """创建 scout 任务的 Governor spec。"""
    return {
        "department": "protocol",  # scout 用礼部（只读权限）
        "intent": "audit_attention",
        "project": project,
        "cwd": cwd,
        "problem": f"侦察任务：{mission.question}",
        "observation": f"搜索范围：{mission.search_scope}",
        "expected": "简洁的事实性回答",
        "summary": f"Scout: {mission.question[:50]}",
        "is_scout": True,
        "cognitive_mode": "direct",
    }


def build_scout_prompt(mission: ScoutMission) -> str:
    """构建 scout agent 的 prompt。"""
    return SCOUT_PROMPT.format(
        question=mission.question,
        search_scope=mission.search_scope,
        max_files=mission.max_files,
    )


def parse_scout_report(output: str, question: str) -> ScoutReport:
    """解析 scout agent 的输出为结构化报告。"""
    import re

    findings = ""
    files = []
    confidence = 0.5

    findings_match = re.search(r'FINDINGS:\s*(.+?)(?=FILES:|CONFIDENCE:|$)', output, re.DOTALL)
    if findings_match:
        findings = findings_match.group(1).strip()

    files_match = re.search(r'FILES:\s*(.+?)(?=CONFIDENCE:|$)', output, re.DOTALL)
    if files_match:
        files = [f.strip() for f in files_match.group(1).split(",") if f.strip()]

    conf_match = re.search(r'CONFIDENCE:\s*([\d.]+)', output)
    if conf_match:
        try:
            confidence = min(1.0, max(0.0, float(conf_match.group(1))))
        except ValueError:
            pass

    # Fallback: 没有结构化输出，用整个 output 做 findings
    if not findings:
        findings = output[:500]

    return ScoutReport(
        question=question,
        findings=findings,
        files_examined=files,
        confidence=confidence,
    )


def build_synthesize_prompt(reports: list[ScoutReport], original_task: str) -> str:
    """基于多个 scout 报告构建综合决策 prompt。"""
    lines = [
        "## 侦察汇总",
        f"原始任务：{original_task}",
        "",
    ]

    for i, report in enumerate(reports, 1):
        lines.append(f"### Scout #{i}: {report.question}")
        lines.append(f"发现：{report.findings}")
        lines.append(f"信心：{report.confidence}")
        if report.files_examined:
            lines.append(f"查看文件：{', '.join(report.files_examined[:5])}")
        lines.append("")

    lines.append("## 决策指引")
    lines.append("基于上述侦察结果，请确定：")
    lines.append("1. 问题的根因是什么")
    lines.append("2. 需要修改哪些文件")
    lines.append("3. 修改方案")

    return "\n".join(lines)
