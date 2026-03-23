import json
import pytest
from unittest.mock import MagicMock, patch
from src.analysis.analyst import DailyAnalyst
from src.storage.events_db import EventsDB


def make_analyst_result():
    return {
        "summary": "今天主要在做 Python 开发",
        "time_breakdown": {"coding": 120, "reading": 30},
        "top_topics": ["python", "agent", "orchestrator"],
        "behavioral_insights": "下午最活跃，偏向深度工作",
        "profile_update": {"interests": ["AI", "编程"], "work_style": "夜猫子"}
    }


def test_analyst_runs(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    db.insert_event("claude", "coding", "写代码", 60, 0.8, ["python"], {})
    db.insert_event("browser_chrome", "dev", "看文档", 30, 0.6, ["docs"], {})

    result_json = json.dumps(make_analyst_result(), ensure_ascii=False)
    mock_proc = MagicMock()
    mock_proc.stdout = result_json
    mock_proc.stderr = ""

    with patch("src.analysis.analyst.subprocess.run", return_value=mock_proc):
        analyst = DailyAnalyst(db=db)
        result = analyst.run()

        assert "summary" in result
        assert "top_topics" in result
        assert result["summary"] == "今天主要在做 Python 开发"
