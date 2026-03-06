import pytest
from unittest.mock import MagicMock, patch
from src.agent import ClarificationAgent


def make_mock_response(content: str):
    msg = MagicMock()
    msg.content = [MagicMock(text=content)]
    return msg


def test_agent_initializes():
    agent = ClarificationAgent(api_key="test-key")
    assert agent is not None


def test_agent_detects_clear_problem():
    agent = ClarificationAgent(api_key="test-key")
    response = '{"is_clear": true, "question": null, "definition": "帮助用户追踪待办事项", "clarity_level": "高", "tags": ["任务管理"]}'
    result = agent._parse_response(response)
    assert result["is_clear"] is True
    assert result["definition"] == "帮助用户追踪待办事项"


def test_agent_detects_unclear_problem():
    agent = ClarificationAgent(api_key="test-key")
    response = '{"is_clear": false, "question": "你想解决什么具体问题？", "definition": null, "clarity_level": "低", "tags": []}'
    result = agent._parse_response(response)
    assert result["is_clear"] is False
    assert result["question"] is not None


def test_agent_runs_clarification_loop(tmp_path):
    db_path = str(tmp_path / "test.db")

    with patch("src.agent.anthropic.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        MockAnthropic.return_value = mock_client
        mock_client.messages.create.side_effect = [
            make_mock_response('{"is_clear": false, "question": "你的目标用户是谁？", "definition": null, "clarity_level": "低", "tags": []}'),
            make_mock_response('{"is_clear": true, "question": null, "definition": "帮助独立开发者追踪项目进度", "clarity_level": "高", "tags": ["开发者", "项目管理"]}'),
        ]

        agent = ClarificationAgent(api_key="test-key", db_path=db_path)
        result = agent.run("我想做一个工具", user_replies=["给独立开发者用"])

        assert result["definition"] == "帮助独立开发者追踪项目进度"
        assert result["session_id"] is not None
