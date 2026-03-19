import json
from unittest.mock import patch, MagicMock
from src.governance.debt_scanner import DebtScanner

def test_analyze_batch_uses_router():
    """_analyze_one_batch() 应通过 LLMRouter 而不是直接调 subprocess。"""
    mock_db = MagicMock()
    scanner = DebtScanner(db=mock_db)

    batch = [{
        "session_id": "abc123",
        "project": "test-project",
        "slug": "test-slug",
        "total_messages": 10,
        "key_messages": ["found a bug in the parser", "will fix later"],
        "last_assistant": "I'll look into it next time",
    }]

    fake_response = json.dumps([{
        "session_id": "test-slug",
        "project": "test-project",
        "summary": "parser bug未修复",
        "severity": "medium",
        "context": "found a bug in the parser",
    }])

    with patch("src.governance.debt_scanner.get_router") as mock_get_router:
        mock_router = MagicMock()
        mock_router.generate.return_value = fake_response
        mock_get_router.return_value = mock_router

        result = scanner._analyze_one_batch(batch)

    assert len(result) == 1
    assert result[0]["summary"] == "parser bug未修复"
    mock_router.generate.assert_called_once()

def test_analyze_batch_handles_markdown_fences():
    """响应被 markdown fence 包裹时应正常解析。"""
    mock_db = MagicMock()
    scanner = DebtScanner(db=mock_db)

    batch = [{"session_id": "x", "project": "p", "slug": "s", "total_messages": 5,
              "key_messages": ["error happened"], "last_assistant": "noted"}]

    fenced = '```json\n[{"session_id":"s","project":"p","summary":"bug","severity":"low","context":"err"}]\n```'

    with patch("src.governance.debt_scanner.get_router") as mock_get_router:
        mock_router = MagicMock()
        mock_router.generate.return_value = fenced
        mock_get_router.return_value = mock_router

        result = scanner._analyze_one_batch(batch)

    assert len(result) == 1
