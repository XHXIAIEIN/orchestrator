import pytest
from unittest.mock import patch, MagicMock
from src.gateway.dispatcher import dispatch_user_intent, dispatch_from_text
from src.gateway.intent import TaskIntent


class TestDispatcher:
    def test_dispatch_creates_task(self):
        """明确意图应创建 Governor 任务并返回 task_id。"""
        intent = TaskIntent(
            action="修复 Steam 采集器", department="engineering",
            cognitive_mode="hypothesis", priority="high",
            problem="Steam 采集器 0 数据", expected="正常采集",
            needs_clarification=False,
        )
        mock_db = MagicMock()
        mock_db.create_task.return_value = 42
        with patch('src.gateway.dispatcher.EventsDB', return_value=mock_db):
            result = dispatch_user_intent(intent, db=mock_db)
            assert result["task_id"] == 42
            assert result["status"] == "created"
            mock_db.create_task.assert_called_once()

    def test_dispatch_clarification_returns_question(self):
        """需要澄清的意图不创建任务，返回问题。"""
        intent = TaskIntent(
            action="", department="",
            cognitive_mode="react", priority="medium",
            problem="", expected="",
            needs_clarification=True,
            clarification_question="你说的「那个」是哪个？",
        )
        result = dispatch_user_intent(intent)
        assert result["status"] == "needs_clarification"
        assert "那个" in result["question"]

    def test_full_pipeline_from_text(self):
        """从自然语言到派单的完整流程。"""
        with patch('src.gateway.dispatcher.IntentGateway') as MockGW:
            MockGW.return_value.parse.return_value = TaskIntent(
                action="运行安全扫描", department="security",
                cognitive_mode="react", priority="high",
                problem="需要安全检查", expected="无高危漏洞",
                needs_clarification=False,
            )
            mock_db = MagicMock()
            mock_db.create_task.return_value = 99
            with patch('src.gateway.dispatcher.EventsDB', return_value=mock_db):
                result = dispatch_from_text("跑一次安全扫描", db=mock_db)
                assert result["task_id"] == 99
