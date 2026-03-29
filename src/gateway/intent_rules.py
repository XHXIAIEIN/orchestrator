"""
Intent Rule Engine — pattern-based intent resolution without LLM.

Sits between classifier.py (tier triage) and intent.py (LLM parsing).
High-confidence pattern matches produce TaskIntent directly.
Ambiguous or multi-department matches fall through to LLM.
"""
import re
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── Priority keywords ──

_PRIORITY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'紧急|urgent|critical|立刻|马上|immediately|生产环境|production', re.I), "critical"),
    (re.compile(r'尽快|asap|important|重要', re.I), "high"),
    (re.compile(r'不急|低优|when\s*free|有空', re.I), "low"),
]


def _detect_priority(text: str) -> str:
    """Extract priority from text. Default: medium."""
    for pattern, priority in _PRIORITY_PATTERNS:
        if pattern.search(text):
            return priority
    return "medium"


# ── Intent rules ──
# Each rule: (pattern, department, intent, cognitive_mode)
# Order matters: first match wins within a department group.
# Rules are grouped by department for conflict detection.

_DEPARTMENT_RULES: dict[str, list[tuple[re.Pattern, str, str]]] = {
    "engineering": [
        (re.compile(r'重构|refactor|redesign', re.I), "code_refactor", "designer"),
        (re.compile(r'新功能|new\s*feature|实现|implement|添加功能', re.I), "code_feature", "react"),
        (re.compile(r'修复|fix|bug|错误|报错|崩溃|crash', re.I), "code_fix", "react"),
        (re.compile(r'改名|rename|配置|config|清理|cleanup|格式化|format', re.I), "code_config", "direct"),
    ],
    "operations": [
        (re.compile(r'部署|deploy|上线|发布|release', re.I), "ops_deploy", "react"),
        (re.compile(r'检查|health|健康|状态.*(?:采集|collector|服务|service)', re.I), "ops_health", "direct"),
        (re.compile(r'修复.*(?:采集|collector|服务|docker|容器).*(?:挂|坏|失败|停|断)|(?:采集|collector|服务).*(?:挂了|坏了|失败|修)', re.I), "ops_repair", "react"),
        (re.compile(r'重启|restart|docker|容器', re.I), "ops_repair", "react"),
    ],
    "quality": [
        (re.compile(r'(?:完整|full).*测试|验收|acceptance', re.I), "quality_regression", "react"),
        (re.compile(r'测试|test|review|code\s*review|审查|检查.*代码|回归|regression', re.I), "quality_review", "react"),
    ],
    "security": [
        (re.compile(r'安全事件|incident|入侵|breach|泄露|leak', re.I), "security_incident", "hypothesis"),
        (re.compile(r'安全|security|漏洞|vulnerability|依赖.*审计|secret|密钥.*扫描', re.I), "security_scan", "react"),
    ],
    "personnel": [
        (re.compile(r'深度.*评估|能力.*分析|deep.*eval', re.I), "perf_deep", "react"),
        (re.compile(r'绩效|performance|报告|report|趋势|trend|统计|stats', re.I), "perf_report", "direct"),
    ],
    "protocol": [
        (re.compile(r'技术债|tech.*debt|debt', re.I), "audit_debt", "direct"),
        (re.compile(r'TODO|待办|注意力.*审计|abandoned|废弃|stale', re.I), "audit_attention", "direct"),
    ],
}


def try_rule_match(text: str) -> Optional[TaskIntent]:
    """Try to resolve intent from rules. Returns None if ambiguous or no match.

    Conflict detection: if keywords match multiple departments, return None
    and let the LLM disambiguate.
    """
    text = text.strip()
    if not text:
        return None

    matched_departments: list[tuple[str, str, str]] = []  # (dept, intent, mode)

    for dept, rules in _DEPARTMENT_RULES.items():
        for pattern, intent, mode in rules:
            if pattern.search(text):
                matched_departments.append((dept, intent, mode))
                break  # first match per department

    # No match → fall through to LLM
    if len(matched_departments) == 0:
        return None

    # Multiple departments matched → ambiguous, let LLM decide
    if len(matched_departments) > 1:
        depts = [d[0] for d in matched_departments]
        log.debug("intent_rules: ambiguous match across %s, falling through to LLM", depts)
        return None

    dept, intent, mode = matched_departments[0]
    priority = _detect_priority(text)

    log.info("intent_rules: rule match → %s/%s (mode=%s, priority=%s)", dept, intent, mode, priority)

    from src.gateway.intent import TaskIntent
    return TaskIntent(
        action=text,
        intent=intent,
        department=dept,
        cognitive_mode=mode,
        priority=priority,
        problem=text,
        expected="",
        needs_clarification=False,
    )
