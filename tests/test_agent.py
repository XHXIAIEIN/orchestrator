import pytest
from unittest.mock import MagicMock, patch
from src.agent import ClarificationAgent


def make_clarify_response(is_clear: bool, question: str = None, definition: str = None,
                           clarity_level: str = "低", tags: list = None):
    block = MagicMock()
    block.type = "tool_use"
    block.name = "clarify"
    block.id = "tu_test"
    block.input = {
        "is_clear": is_clear,
        "question": question,
        "definition": definition,
        "clarity_level": clarity_level,
        "tags": tags or [],
    }
    response = MagicMock()
    response.content = [block]
    return response


def test_agent_initializes():
    agent = ClarificationAgent(api_key="test-key")
    assert agent is not None


def test_agent_runs_clarification_loop(tmp_path):
    db_path = str(tmp_path / "test.db")

    with patch("src.agent.anthropic.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        MockAnthropic.return_value = mock_client
        mock_client.messages.create.side_effect = [
            make_clarify_response(False, question="你的目标用户是谁？", clarity_level="低"),
            make_clarify_response(True, definition="帮助独立开发者追踪项目进度",
                                  clarity_level="高", tags=["开发者", "项目管理"]),
        ]

        agent = ClarificationAgent(api_key="test-key", db_path=db_path)
        result = agent.run("我想做一个工具", user_replies=["给独立开发者用"])

        assert result["definition"] == "帮助独立开发者追踪项目进度"
        assert result["session_id"] is not None
        assert result["rounds"] == 2


def test_agent_forces_finish_at_max_rounds(tmp_path):
    db_path = str(tmp_path / "test.db")

    with patch("src.agent.anthropic.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        MockAnthropic.return_value = mock_client
        mock_client.messages.create.return_value = make_clarify_response(
            False, question="还有什么补充？", clarity_level="中"
        )

        agent = ClarificationAgent(api_key="test-key", db_path=db_path)
        agent.max_rounds = 2
        result = agent.run("我想做点什么", user_replies=["不知道", "随便"])

        assert result["rounds"] == 2
