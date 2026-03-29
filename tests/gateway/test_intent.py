import pytest
from unittest.mock import patch, MagicMock
from src.gateway.intent import IntentGateway, TaskIntent


class TestIntentGateway:
    def setup_method(self):
        self.gw = IntentGateway()

    def test_parse_returns_task_intent(self):
        """parse() 应返回 TaskIntent dataclass。"""
        with patch.object(self.gw, '_call_llm') as mock:
            mock.return_value = {
                "action": "修复 Steam 采集器路径问题",
                "department": "engineering",
                "cognitive_mode": "hypothesis",
                "priority": "medium",
                "problem": "Steam 采集器一直返回 0 数据",
                "expected": "采集器能正确找到 Steam 安装路径并采集数据",
                "needs_clarification": False,
                "clarification_question": None,
            }
            result = self.gw.parse("帮我看看为什么 Steam 采集器一直是 0 数据")
            assert isinstance(result, TaskIntent)
            assert result.department == "engineering"
            assert result.cognitive_mode == "hypothesis"
            assert not result.needs_clarification

    def test_parse_needs_clarification(self):
        """模糊输入应触发澄清。"""
        with patch.object(self.gw, '_call_llm') as mock:
            mock.return_value = {
                "action": "",
                "department": "",
                "cognitive_mode": "react",
                "priority": "medium",
                "problem": "",
                "expected": "",
                "needs_clarification": True,
                "clarification_question": "你说的「那个问题」是指哪个？能具体一点吗？",
            }
            result = self.gw.parse("把那个问题修一下")
            assert result.needs_clarification
            assert "具体" in result.clarification_question

    def test_parse_with_context(self):
        """带上下文的指令应利用上下文。"""
        with patch.object(self.gw, '_call_llm') as mock:
            mock.return_value = {
                "action": "运行 deep_scan 安全审计",
                "department": "security",
                "cognitive_mode": "react",
                "priority": "high",
                "problem": "需要全面安全扫描",
                "expected": "无高危漏洞",
                "needs_clarification": False,
                "clarification_question": None,
            }
            result = self.gw.parse(
                "跑一次安全扫描",
                context={"recent_events": ["dependency update"]},
            )
            assert result.department == "security"

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


class TestGovernorSpec:
    def test_to_governor_spec(self):
        """TaskIntent 应能转换为 Governor 的 spec 格式。"""
        intent = TaskIntent(
            action="修复 Steam 采集器",
            intent="fix",
            department="engineering",
            cognitive_mode="hypothesis",
            priority="high",
            problem="路径错误导致 0 数据",
            expected="正常采集",
            needs_clarification=False,
            clarification_question=None,
        )
        spec = intent.to_governor_spec()
        assert spec["department"] == "engineering"
        assert spec["problem"] == "路径错误导致 0 数据"
        assert spec["cognitive_mode"] == "hypothesis"
