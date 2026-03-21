"""
Request Classifier — 三路分流，SoulFlow-inspired gateway triage.

Every request is classified into one of three tiers:
  - NO_TOKEN:  Pure data query, answered from DB/filesystem. Zero LLM cost.
  - DIRECT:    Single LLM call (explain, summarize). No agent tools needed.
  - AGENT:     Multi-step task requiring full Governor → Agent SDK pipeline.

Simple requests skip the expensive agent loop entirely.
"""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RequestTier(Enum):
    NO_TOKEN = "no_token"   # DB query, no LLM
    DIRECT = "direct"       # Single LLM call
    AGENT = "agent"         # Full agent loop


@dataclass
class ClassifiedRequest:
    """Result of request classification."""
    tier: RequestTier
    handler: str          # which handler to route to
    confidence: float     # 0-1, how confident we are
    original_text: str
    extracted_params: dict  # parsed parameters for the handler


# ── Pattern-based classifier (no LLM needed) ──

# NO_TOKEN patterns: pure data retrieval
_NO_TOKEN_PATTERNS: list[tuple[re.Pattern, str, dict]] = [
    # Status queries
    (re.compile(r'(?:系统|容器|orchestrator)\s*(?:状态|status|健康|health)', re.I), "system_status", {}),
    (re.compile(r'(?:最近|recent)\s*(?:的\s*)?(?:任务|tasks?)', re.I), "recent_tasks", {}),
    (re.compile(r'(?:跑|运行|running)\s*(?:了吗|着吗|中吗|状态)', re.I), "system_status", {}),
    (re.compile(r'(?:采集器|collector)\s*(?:状态|health|reputation)', re.I), "collector_status", {}),
    (re.compile(r'(?:几个|多少|how many)\s*(?:任务|tasks?)', re.I), "task_count", {}),
    (re.compile(r'(?:部门|department)\s*(?:状态|stats?|统计)', re.I), "department_stats", {}),
    (re.compile(r'(?:今天|today|昨天|yesterday)\s*(?:日报|summary|摘要)', re.I), "daily_summary", {}),
    (re.compile(r'(?:run.?log|执行记录|运行日志)', re.I), "run_logs", {}),
    (re.compile(r'(?:哈希链|hash.?chain)\s*(?:验证|verify|check)', re.I), "verify_chain", {}),
    (re.compile(r'(?:债务|debts?)\s*(?:列表|list|有哪些)', re.I), "debt_list", {}),
]

# DIRECT patterns: single LLM call, no tools
_DIRECT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'^(?:解释|explain|what is|什么是)', re.I), "explain"),
    (re.compile(r'^(?:总结|summarize|概括)', re.I), "summarize"),
    (re.compile(r'^(?:翻译|translate)', re.I), "translate"),
    (re.compile(r'(?:为什么|why)\s*(?:这个|这条|that)', re.I), "explain"),
]

# AGENT signals: keywords that strongly suggest multi-step work
_AGENT_SIGNALS = re.compile(
    r'(?:修复|fix|实现|implement|重构|refactor|添加|add|删除|delete|remove|'
    r'创建|create|部署|deploy|升级|upgrade|迁移|migrate|'
    r'跑测试|run tests?|执行|execute|扫描|scan|审计|audit|'
    r'写|write|改|modify|优化|optimize)',
    re.I
)


def classify(text: str) -> ClassifiedRequest:
    """Classify a request into NO_TOKEN, DIRECT, or AGENT tier.

    Uses pattern matching (no LLM call). Conservative: when in doubt, escalate to AGENT.
    """
    text = text.strip()
    if not text:
        return ClassifiedRequest(
            tier=RequestTier.AGENT, handler="default",
            confidence=0.0, original_text=text, extracted_params={},
        )

    # Check NO_TOKEN patterns first (cheapest path)
    for pattern, handler, params in _NO_TOKEN_PATTERNS:
        if pattern.search(text):
            return ClassifiedRequest(
                tier=RequestTier.NO_TOKEN, handler=handler,
                confidence=0.9, original_text=text, extracted_params=params,
            )

    # Check DIRECT patterns
    for pattern, handler in _DIRECT_PATTERNS:
        if pattern.search(text):
            # But if it also has AGENT signals, escalate
            if _AGENT_SIGNALS.search(text):
                break
            return ClassifiedRequest(
                tier=RequestTier.DIRECT, handler=handler,
                confidence=0.7, original_text=text, extracted_params={},
            )

    # Default: AGENT (conservative — better to over-route than under-route)
    return ClassifiedRequest(
        tier=RequestTier.AGENT, handler="full_dispatch",
        confidence=0.5, original_text=text, extracted_params={},
    )
