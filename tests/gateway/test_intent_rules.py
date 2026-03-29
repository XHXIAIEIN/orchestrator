# tests/gateway/test_intent_rules.py
"""Tests for intent rule engine — pattern-based intent resolution without LLM."""
import pytest
from src.gateway.intent_rules import try_rule_match, get_stats, reset_stats


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
