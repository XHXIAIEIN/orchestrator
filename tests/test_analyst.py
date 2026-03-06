import pytest
from unittest.mock import MagicMock, patch
from src.analyst import DailyAnalyst
from src.storage.events_db import EventsDB


def make_analyst_response():
    block = MagicMock()
    block.type = "tool_use"
    block.name = "save_analysis"
    block.id = "tu_analysis"
    block.input = {
        "summary": "今天主要在做 Python 开发",
        "time_breakdown": {"coding": 120, "reading": 30},
        "top_topics": ["python", "agent", "orchestrator"],
        "behavioral_insights": "下午最活跃，偏向深度工作",
        "profile_update": {"interests": ["AI", "编程"], "work_style": "夜猫子"}
    }
    response = MagicMock()
    response.content = [block]
    return response


def test_analyst_runs(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    db.insert_event("claude", "coding", "写代码", 60, 0.8, ["python"], {})
    db.insert_event("browser_chrome", "dev", "看文档", 30, 0.6, ["docs"], {})

    with patch("src.analyst.anthropic.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        MockAnthropic.return_value = mock_client
        mock_client.messages.create.return_value = make_analyst_response()

        analyst = DailyAnalyst(api_key="test-key", db=db)
        result = analyst.run()

        assert "summary" in result
        assert "top_topics" in result
        assert result["summary"] == "今天主要在做 Python 开发"
