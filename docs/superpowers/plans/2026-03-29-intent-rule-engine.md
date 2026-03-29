# Intent Rule Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a rule-based pre-routing layer to `IntentGateway` that resolves 60-70% of common intents without an LLM call, saving tokens and latency.

**Architecture:** A declarative rule table sits between `classifier.py` (tier triage) and `intent.py` (LLM parsing). Rules are auto-generated from manifest tags + hand-tuned keyword patterns. High-confidence matches produce `TaskIntent` directly; low-confidence or ambiguous requests fall through to the existing LLM parser. Hit/miss metrics are logged for tuning.

**Tech Stack:** Python 3.11, regex, existing `TaskIntent` dataclass, manifest registry

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/gateway/intent_rules.py` | Rule engine: declarative rules, matching logic, `TaskIntent` construction |
| Modify | `src/gateway/intent.py:108-114` | `IntentGateway.parse()` — try rules first, fall through to LLM |
| Create | `tests/gateway/test_intent_rules.py` | Rule engine unit tests |
| Modify | `tests/gateway/test_intent.py` | Add integration test for rule-first flow |

---

### Task 1: Define the Rule Table and Matching Engine

**Files:**
- Create: `src/gateway/intent_rules.py`
- Test: `tests/gateway/test_intent_rules.py`

- [ ] **Step 1: Write failing tests for rule matching**

```python
# tests/gateway/test_intent_rules.py
"""Tests for intent rule engine — pattern-based intent resolution without LLM."""
import pytest
from src.gateway.intent_rules import try_rule_match


class TestRuleMatching:
    """High-confidence patterns should resolve to TaskIntent without LLM."""

    def test_fix_bug_routes_to_engineering(self):
        result = try_rule_match("修复 Steam 采集器的路径 bug")
        assert result is not None
        assert result.department == "engineering"
        assert result.intent == "code_fix"
        assert result.cognitive_mode == "react"

    def test_check_collector_routes_to_operations(self):
        result = try_rule_match("检查采集器健康状态")
        assert result is not None
        assert result.department == "operations"
        assert result.intent == "ops_health"
        assert result.cognitive_mode == "direct"

    def test_security_scan_routes_to_security(self):
        result = try_rule_match("扫描依赖漏洞")
        assert result is not None
        assert result.department == "security"
        assert result.intent == "security_scan"

    def test_run_tests_routes_to_quality(self):
        result = try_rule_match("跑一下回归测试")
        assert result is not None
        assert result.department == "quality"
        assert result.intent == "quality_review"

    def test_refactor_routes_to_engineering_designer(self):
        result = try_rule_match("重构 gateway 模块的路由逻辑")
        assert result is not None
        assert result.department == "engineering"
        assert result.intent == "code_refactor"
        assert result.cognitive_mode == "designer"

    def test_deploy_routes_to_operations(self):
        result = try_rule_match("部署新版本到 Docker")
        assert result is not None
        assert result.department == "operations"
        assert result.intent == "ops_deploy"

    def test_performance_report_routes_to_personnel(self):
        result = try_rule_match("生成本周绩效报告")
        assert result is not None
        assert result.department == "personnel"
        assert result.intent == "perf_report"

    def test_tech_debt_scan_routes_to_protocol(self):
        result = try_rule_match("扫描 TODO 和技术债")
        assert result is not None
        assert result.department == "protocol"
        assert result.intent == "audit_debt"

    def test_ambiguous_input_returns_none(self):
        """Ambiguous or vague input should fall through to LLM."""
        result = try_rule_match("帮我看看这个")
        assert result is None

    def test_empty_input_returns_none(self):
        result = try_rule_match("")
        assert result is None

    def test_mixed_signals_returns_none(self):
        """When keywords match multiple departments, fall through to LLM."""
        result = try_rule_match("修复安全漏洞并部署")
        assert result is None

    def test_priority_extraction_critical(self):
        result = try_rule_match("紧急修复生产环境 bug")
        assert result is not None
        assert result.priority == "critical"

    def test_priority_default_medium(self):
        result = try_rule_match("修复登录页面的样式问题")
        assert result is not None
        assert result.priority == "medium"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/gateway/test_intent_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.gateway.intent_rules'`

- [ ] **Step 3: Implement the rule engine**

```python
# src/gateway/intent_rules.py
"""
Intent Rule Engine — pattern-based intent resolution without LLM.

Sits between classifier.py (tier triage) and intent.py (LLM parsing).
High-confidence pattern matches produce TaskIntent directly.
Ambiguous or multi-department matches fall through to LLM.
"""
import re
import logging
from typing import Optional

from src.gateway.intent import TaskIntent

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
        (re.compile(r'修复.*(?:采集|collector|服务|docker|容器)|(?:采集|collector|服务).*(?:挂了|坏了|失败|修)', re.I), "ops_repair", "react"),
        (re.compile(r'重启|restart|docker|容器', re.I), "ops_repair", "react"),
    ],
    "quality": [
        (re.compile(r'回归|regression|完整.*测试|验收', re.I), "quality_regression", "react"),
        (re.compile(r'测试|test|review|code\s*review|审查|检查.*代码', re.I), "quality_review", "react"),
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/gateway/test_intent_rules.py -v`
Expected: All 13 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/gateway/intent_rules.py tests/gateway/test_intent_rules.py
git commit -m "feat(gateway): intent rule engine — pattern-based routing without LLM"
```

---

### Task 2: Wire Rule Engine into IntentGateway

**Files:**
- Modify: `src/gateway/intent.py:105-114`
- Test: `tests/gateway/test_intent.py`

- [ ] **Step 1: Write failing integration test**

Add to `tests/gateway/test_intent.py`:

```python
class TestRuleFirstFlow:
    """IntentGateway.parse() should try rules before calling LLM."""

    @patch.object(IntentGateway, '_call_llm')
    def test_clear_intent_skips_llm(self, mock_llm):
        """When rule engine matches with high confidence, LLM is never called."""
        gw = IntentGateway()
        result = gw.parse("修复登录页面的 CSS bug")
        assert result.department == "engineering"
        assert result.intent == "code_fix"
        mock_llm.assert_not_called()

    @patch.object(IntentGateway, '_call_llm')
    def test_ambiguous_intent_falls_through_to_llm(self, mock_llm):
        """When rule engine returns None, LLM is called as usual."""
        mock_llm.return_value = {
            "action": "investigate", "intent": "code_fix",
            "department": "engineering", "cognitive_mode": "react",
            "priority": "medium", "problem": "unclear",
            "expected": "fix", "needs_clarification": False,
        }
        gw = IntentGateway()
        result = gw.parse("帮我看看这个东西")
        mock_llm.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/gateway/test_intent.py::TestRuleFirstFlow -v`
Expected: FAIL (rule engine not wired in yet)

- [ ] **Step 3: Modify IntentGateway.parse() to try rules first**

In `src/gateway/intent.py`, modify the `parse` method:

```python
# Add import at top of file
from src.gateway.intent_rules import try_rule_match

# Replace the existing parse method body
class IntentGateway:
    """Orchestrator's front desk."""

    def parse(self, user_input: str, context: dict = None) -> TaskIntent:
        """Parse user command. Tries rule engine first, falls back to LLM."""
        # Fast path: rule-based matching (no LLM cost)
        rule_result = try_rule_match(user_input)
        if rule_result is not None:
            return rule_result

        # Slow path: LLM-based parsing
        ctx_str = json.dumps(context or {}, ensure_ascii=False, indent=2)
        prompt = _get_intent_prompt().format(user_input=user_input, context=ctx_str)
        raw = self._call_llm(prompt)
        return self._validate(raw)
```

- [ ] **Step 4: Run all gateway tests**

Run: `python -m pytest tests/gateway/ -v`
Expected: All tests PASS (existing + new)

- [ ] **Step 5: Commit**

```bash
git add src/gateway/intent.py tests/gateway/test_intent.py
git commit -m "feat(gateway): wire rule engine into IntentGateway — rules first, LLM fallback"
```

---

### Task 3: Add Hit/Miss Logging for Tuning

**Files:**
- Modify: `src/gateway/intent.py:108-118`
- Modify: `src/gateway/intent_rules.py` (add stats)

- [ ] **Step 1: Write test for stats tracking**

Add to `tests/gateway/test_intent_rules.py`:

```python
from src.gateway.intent_rules import try_rule_match, get_stats, reset_stats


class TestRuleStats:
    """Rule engine should track hit/miss for tuning."""

    def setup_method(self):
        reset_stats()

    def test_hit_increments(self):
        try_rule_match("修复 bug")
        stats = get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 0

    def test_miss_increments(self):
        try_rule_match("帮我看看这个")
        stats = get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 1

    def test_ambiguous_counted_as_miss(self):
        try_rule_match("修复安全漏洞并部署")
        stats = get_stats()
        assert stats["hits"] == 0
        assert stats["ambiguous"] == 1

    def test_hit_rate_calculation(self):
        try_rule_match("修复 bug")
        try_rule_match("跑测试")
        try_rule_match("帮我看看")
        stats = get_stats()
        assert stats["hit_rate"] == pytest.approx(2 / 3, abs=0.01)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/gateway/test_intent_rules.py::TestRuleStats -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add stats tracking to intent_rules.py**

Add at the end of `src/gateway/intent_rules.py`:

```python
# ── Stats tracking ──

_stats = {"hits": 0, "misses": 0, "ambiguous": 0}


def get_stats() -> dict:
    """Return rule engine hit/miss stats."""
    total = _stats["hits"] + _stats["misses"] + _stats["ambiguous"]
    return {
        **_stats,
        "total": total,
        "hit_rate": _stats["hits"] / total if total > 0 else 0.0,
    }


def reset_stats():
    """Reset stats counters (for testing)."""
    _stats["hits"] = 0
    _stats["misses"] = 0
    _stats["ambiguous"] = 0
```

Then update `try_rule_match` to track stats — add to the three return paths:

```python
    # No match
    if len(matched_departments) == 0:
        _stats["misses"] += 1
        return None

    # Ambiguous
    if len(matched_departments) > 1:
        _stats["ambiguous"] += 1
        log.debug(...)
        return None

    # Hit
    _stats["hits"] += 1
    log.info(...)
    return TaskIntent(...)
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/gateway/ -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/gateway/intent_rules.py tests/gateway/test_intent_rules.py
git commit -m "feat(gateway): intent rule engine stats — hit/miss/ambiguous tracking"
```

---

### Task 4: Fix the system_uptime python→python3 Bug

**Files:**
- Modify: `src/collectors/system_uptime/manifest.yaml:8`

- [ ] **Step 1: Verify the fix is already applied**

The file should already have `python3` instead of `python`. Verify:

Run: `grep 'cmd:' src/collectors/system_uptime/manifest.yaml`
Expected: `cmd: "python3 -c \"import time; print(time.time())\""`

- [ ] **Step 2: Commit**

```bash
git add src/collectors/system_uptime/manifest.yaml
git commit -m "fix(collector): system_uptime manifest python → python3"
```

---

## Post-Implementation Verification

After all tasks are complete:

1. Run full test suite: `python -m pytest tests/gateway/ -v`
2. Verify rule engine coverage by running stats against common commands:

```python
from src.gateway.intent_rules import try_rule_match, get_stats, reset_stats

test_inputs = [
    "修复 Steam 采集器",           # → engineering/code_fix
    "检查采集器状态",               # → operations/ops_health
    "扫描安全漏洞",                # → security/security_scan
    "跑回归测试",                  # → quality/quality_regression
    "生成绩效报告",                # → personnel/perf_report
    "扫描 TODO",                  # → protocol/audit_attention
    "部署新版本",                  # → operations/ops_deploy
    "重构路由模块",                # → engineering/code_refactor
    "帮我看看这个",                # → None (LLM fallback)
    "优化数据库查询并扫描安全",      # → None (ambiguous)
]

reset_stats()
for inp in test_inputs:
    result = try_rule_match(inp)
    print(f"  {inp:30s} → {result.department + '/' + result.intent if result else 'LLM fallback'}")

stats = get_stats()
print(f"\nHit rate: {stats['hit_rate']:.0%} ({stats['hits']}/{stats['total']})")
# Expected: ~80% hit rate (8/10)
```
