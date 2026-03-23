"""
PLAN→ACT→EVAL 质量闭环。

codingbuddy 启发：循环直到 criticalCount===0 && highCount===0，
达上限 fallback 回人类介入。

Governor 的 _dispatch_quality_review 已实现 ACT→EVAL，
这个模块提供结构化的 EVAL 解析和循环控制。
"""
import logging
import re
from dataclasses import dataclass, field
from enum import IntEnum

log = logging.getLogger(__name__)


class IssueSeverity(IntEnum):
    INFO = 0       # 建议，不阻塞
    LOW = 1        # 小问题，不阻塞
    HIGH = 2       # 重要问题，需修复
    CRITICAL = 3   # 严重问题，必须修复


@dataclass
class EvalIssue:
    """单个评审问题。"""
    severity: IssueSeverity
    description: str
    file: str = ""
    line: int = 0


@dataclass
class EvalResult:
    """结构化评审结果。"""
    passed: bool
    issues: list[EvalIssue] = field(default_factory=list)
    summary: str = ""
    raw_output: str = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.HIGH)

    @property
    def should_rework(self) -> bool:
        """是否需要返工：有 CRITICAL 或 HIGH 问题。"""
        return self.critical_count > 0 or self.high_count > 0


# ── EVAL Loop Control ──

MAX_EVAL_ITERATIONS = 3  # 最多循环 3 次（ACT→EVAL→rework→EVAL→rework→EVAL）

@dataclass
class LoopState:
    """PLAN→ACT→EVAL 循环状态。"""
    iteration: int = 0
    max_iterations: int = MAX_EVAL_ITERATIONS
    eval_history: list[EvalResult] = field(default_factory=list)

    @property
    def can_continue(self) -> bool:
        return self.iteration < self.max_iterations

    @property
    def should_escalate(self) -> bool:
        """达到上限且仍有问题，需要人类介入。"""
        if self.iteration < self.max_iterations:
            return False
        if not self.eval_history:
            return False
        return self.eval_history[-1].should_rework

    def record_eval(self, result: EvalResult):
        self.eval_history.append(result)
        self.iteration += 1

    def get_trend(self) -> str:
        """返回问题数趋势。"""
        if len(self.eval_history) < 2:
            return "insufficient_data"
        prev = self.eval_history[-2]
        curr = self.eval_history[-1]
        prev_total = prev.critical_count + prev.high_count
        curr_total = curr.critical_count + curr.high_count
        if curr_total == 0:
            return "resolved"
        if curr_total < prev_total:
            return "improving"
        if curr_total == prev_total:
            return "stalled"
        return "worsening"


def parse_eval_output(output: str) -> EvalResult:
    """从刑部输出中解析结构化评审结果。

    支持的格式：
    - VERDICT: PASS/FAIL
    - [CRITICAL] / [HIGH] / [LOW] / [INFO] 前缀的问题行
    - 🔴 / 🟡 / 🟢 emoji 前缀的问题行
    """
    issues = []

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        # Parse severity markers
        severity = None
        desc = line

        if line.startswith("[CRITICAL]") or line.startswith("\U0001f534"):
            severity = IssueSeverity.CRITICAL
            desc = re.sub(r'^\[CRITICAL\]\s*|^\U0001f534\s*', '', line)
        elif line.startswith("[HIGH]") or line.startswith("[BUG]"):
            severity = IssueSeverity.HIGH
            desc = re.sub(r'^\[HIGH\]\s*|^\[BUG\]\s*', '', line)
        elif line.startswith("[WARN]") or line.startswith("\U0001f7e1"):
            severity = IssueSeverity.HIGH
            desc = re.sub(r'^\[WARN\]\s*|^\U0001f7e1\s*', '', line)
        elif line.startswith("[LOW]") or line.startswith("\U0001f7e2"):
            severity = IssueSeverity.LOW
            desc = re.sub(r'^\[LOW\]\s*|^\U0001f7e2\s*', '', line)
        elif line.startswith("[INFO]"):
            severity = IssueSeverity.INFO
            desc = re.sub(r'^\[INFO\]\s*', '', line)

        if severity is not None:
            # Try to extract file:line reference
            file_match = re.search(r'(?:in\s+|at\s+|文件\s+)?([^\s:]+\.\w+)(?::(\d+))?', desc)
            file_path = file_match.group(1) if file_match else ""
            line_num = int(file_match.group(2)) if file_match and file_match.group(2) else 0

            issues.append(EvalIssue(
                severity=severity, description=desc,
                file=file_path, line=line_num,
            ))

    # Determine pass/fail
    verdict_pass = "VERDICT: PASS" in output
    verdict_fail = "VERDICT: FAIL" in output

    if verdict_pass:
        passed = True
    elif verdict_fail:
        passed = False
    else:
        # No explicit verdict — infer from issues
        passed = not any(i.severity >= IssueSeverity.HIGH for i in issues)

    return EvalResult(
        passed=passed,
        issues=issues,
        summary=_extract_summary(output),
        raw_output=output,
    )


def _extract_summary(output: str) -> str:
    """提取 VERDICT 行附近的摘要。"""
    for line in output.splitlines():
        if line.startswith("VERDICT:"):
            return line.strip()
    # Fallback: last non-empty line
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    return lines[-1] if lines else ""


def format_eval_for_rework(eval_result: EvalResult, iteration: int) -> str:
    """格式化 EVAL 结果作为返工 prompt 的一部分。"""
    lines = [
        f"## EVAL 结果（第 {iteration} 轮）",
        f"判定: {'PASS' if eval_result.passed else 'FAIL'}",
        f"CRITICAL: {eval_result.critical_count}, HIGH: {eval_result.high_count}",
        "",
        "### 需修复的问题：",
    ]

    for i in eval_result.issues:
        if i.severity >= IssueSeverity.HIGH:
            prefix = "🔴 CRITICAL" if i.severity == IssueSeverity.CRITICAL else "🟡 HIGH"
            loc = f" ({i.file}:{i.line})" if i.file else ""
            lines.append(f"- {prefix}{loc}: {i.description}")

    lines.append("")
    lines.append("请只修复上述问题，不要做额外改动。")

    return "\n".join(lines)
