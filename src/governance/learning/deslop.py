"""
Deslop — 去 AI 臭味检测器。

bored 启发：专门的质量工位，检测 agent 产出中的 AI 典型毛病：
  - 过度注释
  - 不必要的防御代码
  - 机器感命名
  - 冗余 docstring
  - 过度 try/except

集成点：刑部评审时作为辅助检查，或作为独立的 post-processing 步骤。
"""
import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class SlopFinding:
    """单个 AI 臭味发现。"""
    category: str
    file: str
    line: int
    description: str
    suggestion: str


def scan_for_slop(file_path: str, content: str) -> list[SlopFinding]:
    """扫描文件内容中的 AI 臭味。"""
    findings = []
    lines = content.splitlines()

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # 1. 过度注释：注释比代码还长
        finding = _check_over_comment(stripped, file_path, i)
        if finding:
            findings.append(finding)

        # 2. 冗余 docstring 短语
        finding = _check_boilerplate_docstring(stripped, file_path, i)
        if finding:
            findings.append(finding)

        # 3. 不必要的 type 注释（Python 已有 type hint）
        finding = _check_redundant_type_comment(stripped, file_path, i)
        if finding:
            findings.append(finding)

        # 4. 机器感变量名
        finding = _check_robot_naming(stripped, file_path, i)
        if finding:
            findings.append(finding)

        # 5. 谄媚短语 (Round 26: anti-sycophancy protocol)
        finding = _check_sycophancy(stripped, file_path, i)
        if finding:
            findings.append(finding)

    return findings


def _check_over_comment(line: str, file: str, lineno: int) -> SlopFinding | None:
    """检测过度注释。"""
    if not line.startswith("#"):
        return None

    comment = line.lstrip("# ")

    # 对显而易见代码的注释
    obvious_patterns = [
        r"^(?:initialize|init|set up|setup|create|import|define|declare)\s",
        r"^(?:return|returns?)\s+(?:the|a)\s",
        r"^(?:check|verify|validate)\s+(?:if|whether|that)\s",
        r"^(?:loop|iterate)\s+(?:through|over)\s",
        r"^(?:get|set|update|delete|remove|add)\s+(?:the|a)\s",
        r"^(?:this|the)\s+(?:function|method|class|variable|module)\s",
    ]

    for pattern in obvious_patterns:
        if re.match(pattern, comment, re.IGNORECASE):
            return SlopFinding(
                category="over_comment",
                file=file,
                line=lineno,
                description=f"显而易见的注释: {comment[:50]}",
                suggestion="删除。代码本身已经够清楚了。",
            )

    return None


def _check_boilerplate_docstring(line: str, file: str, lineno: int) -> SlopFinding | None:
    """检测 AI 常见的模板化 docstring 短语。"""
    boilerplate = [
        "this function",
        "this method",
        "this class",
        "a helper function",
        "utility function",
        "helper method",
        "this module provides",
        "this module contains",
    ]

    line_lower = line.lower().strip('"\'')
    for phrase in boilerplate:
        if line_lower.startswith(phrase):
            return SlopFinding(
                category="boilerplate_docstring",
                file=file,
                line=lineno,
                description=f"模板化 docstring: {line[:50]}",
                suggestion="直接说做什么，不要用 'This function...' 开头。",
            )

    return None


def _check_redundant_type_comment(line: str, file: str, lineno: int) -> SlopFinding | None:
    """检测已有 type hint 时的多余类型注释。"""
    if not file.endswith(".py"):
        return None

    # "# type: xxx" 在有 type hint 的代码里是冗余的
    if re.search(r'#\s*type:\s*\w+', line):
        return SlopFinding(
            category="redundant_type",
            file=file,
            line=lineno,
            description="冗余的 # type: 注释",
            suggestion="用 Python type hint 替代行内类型注释。",
        )

    return None


def _check_robot_naming(line: str, file: str, lineno: int) -> SlopFinding | None:
    """检测机器感变量名。"""
    robot_patterns = [
        (r'\b(data_dict|result_dict|output_dict)\b', "xxx_dict → 用具体含义命名"),
        (r'\b(temp_var|tmp_var|temp_value)\b', "temp_var → 用具体含义命名"),
        (r'\b(my_list|my_dict|my_set)\b', "my_xxx → 用具体含义命名"),
        (r'\b(flag|is_flag|check_flag)\b', "flag → 用具体的布尔含义命名"),
    ]

    for pattern, suggestion in robot_patterns:
        if re.search(pattern, line):
            return SlopFinding(
                category="robot_naming",
                file=file,
                line=lineno,
                description=f"机器感命名: {re.search(pattern, line).group()}",
                suggestion=suggestion,
            )

    return None


def _check_sycophancy(line: str, file: str, lineno: int) -> SlopFinding | None:
    """检测谄媚短语 (Round 26: anti-sycophancy protocol)."""
    sycophancy_patterns = [
        (r"(?i)\byou'?re absolutely right\b", "performative agreement"),
        (r"(?i)\bgreat point\b", "performative praise"),
        (r"(?i)\bthanks for catching\b", "gratitude theater"),
        (r"(?i)\bthat'?s a great suggestion\b", "performative praise"),
        (r"(?i)\bi completely agree\b", "performative agreement"),
        (r"(?i)\bgreat catch\b", "performative praise"),
        (r"(?i)\bgreat job\b", "performative praise"),
        (r"(?i)\blooks good overall\b", "empty validation"),
        (r"(?i)\bexcellent observation\b", "performative praise"),
    ]

    for pattern, subtype in sycophancy_patterns:
        match = re.search(pattern, line)
        if match:
            return SlopFinding(
                category="sycophancy",
                file=file,
                line=lineno,
                description=f"谄媚短语 ({subtype}): {match.group()[:40]}",
                suggestion="用技术陈述替代。参见 anti-sycophancy-protocol.md。",
            )

    return None


def format_slop_report(findings: list[SlopFinding]) -> str:
    """格式化 slop 检测报告。"""
    if not findings:
        return ""

    by_category = {}
    for f in findings:
        by_category.setdefault(f.category, []).append(f)

    lines = ["## AI 臭味检测"]
    for category, items in by_category.items():
        lines.append(f"\n### {category} ({len(items)} 处)")
        for item in items[:5]:  # 每类最多显示 5 个
            lines.append(f"- {item.file}:{item.line} — {item.description}")
            lines.append(f"  建议: {item.suggestion}")

    return "\n".join(lines)
