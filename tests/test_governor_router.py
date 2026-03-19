from unittest.mock import patch, MagicMock
from src.governance.governor import Governor

def test_scrutinize_uses_router():
    """scrutinize() 应通过 LLMRouter 而不是直接调 subprocess。"""
    mock_db = MagicMock()
    gov = Governor(db=mock_db)

    task = {
        "action": "test action",
        "reason": "test reason",
        "spec": {
            "project": "orchestrator",
            "cwd": "/orchestrator",
            "summary": "test summary",
            "problem": "test problem",
            "observation": "test obs",
            "expected": "test expected",
        }
    }

    with patch("src.governance.governor.get_router") as mock_get_router:
        mock_router = MagicMock()
        mock_router.generate.return_value = "VERDICT: APPROVE\nREASON: looks good"
        mock_get_router.return_value = mock_router

        approved, reason = gov.scrutinize(1, task)

    assert approved is True
    assert "looks good" in reason
    mock_router.generate.assert_called_once()

def test_scrutinize_reject():
    """scrutinize() 应能正确解析 REJECT 响应。"""
    mock_db = MagicMock()
    gov = Governor(db=mock_db)
    task = {"action": "delete everything", "reason": "yolo", "spec": {"project": "orchestrator", "cwd": "/orchestrator", "summary": "bad", "problem": "", "observation": "", "expected": ""}}

    with patch("src.governance.governor.get_router") as mock_get_router:
        mock_router = MagicMock()
        mock_router.generate.return_value = "VERDICT: REJECT\nREASON: too dangerous"
        mock_get_router.return_value = mock_router

        approved, reason = gov.scrutinize(1, task)

    assert approved is False
    assert "dangerous" in reason
