import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from src.llm_router import LLMRouter, ROUTES

def test_ollama_generate_success():
    """Ollama 正常返回时，generate() 应返回模型输出文本。"""
    router = LLMRouter()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({"response": "VERDICT: APPROVE\nREASON: looks good"}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = router.generate("test prompt", task_type="scrutiny")

    assert "VERDICT: APPROVE" in result
    mock_urlopen.assert_called_once()

def test_ollama_generate_fallback_on_timeout():
    """Ollama 超时时，应 fallback 到 Claude CLI。"""
    import urllib.error
    router = LLMRouter()

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        with patch.object(router, "_claude_generate", return_value="VERDICT: APPROVE\nREASON: fallback") as mock_claude:
            result = router.generate("test prompt", task_type="scrutiny")

    assert "VERDICT: APPROVE" in result
    mock_claude.assert_called_once()

def test_ollama_generate_fallback_on_garbage():
    """Ollama 返回少于 10 字符时，应 fallback 到 Claude。"""
    router = LLMRouter()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({"response": ""}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response):
        with patch.object(router, "_claude_generate", return_value="VERDICT: REJECT\nREASON: fallback") as mock_claude:
            result = router.generate("test prompt", task_type="scrutiny")

    assert "fallback" in result
    mock_claude.assert_called_once()

def test_force_claude_override():
    """LLM_FORCE_CLAUDE 环境变量应强制指定任务类型走 Claude。"""
    router = LLMRouter()

    with patch.dict("os.environ", {"LLM_FORCE_CLAUDE": "scrutiny,debt_scan"}):
        with patch.object(router, "_claude_generate", return_value="forced claude") as mock_claude:
            result = router.generate("test", task_type="scrutiny")

    assert result == "forced claude"
    mock_claude.assert_called_once()

def test_claude_task_types_always_use_claude():
    """deep_analysis 和 profile 类型应始终走 Claude，不走 Ollama。"""
    router = LLMRouter()

    with patch.object(router, "_claude_generate", return_value="claude result") as mock_claude:
        result = router.generate("test", task_type="deep_analysis")

    assert result == "claude result"
    mock_claude.assert_called_once()

def test_routes_have_required_keys():
    """每条路由必须有 backend, model, timeout。"""
    for task_type, route in ROUTES.items():
        assert "backend" in route, f"{task_type} missing backend"
        assert "model" in route, f"{task_type} missing model"
        assert "timeout" in route, f"{task_type} missing timeout"

def test_unknown_task_type_raises():
    """未知的 task_type 应抛出 ValueError。"""
    router = LLMRouter()
    with pytest.raises(ValueError, match="Unknown task_type"):
        router.generate("test", task_type="nonexistent")

def test_ollama_unavailable_skips_to_claude():
    """启动探测 Ollama 不可达时，应直接走 Claude 不再尝试 HTTP。"""
    router = LLMRouter()
    router._ollama_available = False  # 模拟探测失败

    with patch.object(router, "_claude_generate", return_value="VERDICT: APPROVE\nREASON: skipped") as mock_claude:
        with patch("urllib.request.urlopen") as mock_urlopen:
            result = router.generate("test", task_type="scrutiny")

    mock_urlopen.assert_not_called()  # 不应尝试 Ollama
    mock_claude.assert_called_once()
    assert "APPROVE" in result


def test_vision_route_sends_images():
    """vision 路由应将 base64 图片传给 Ollama。"""
    router = LLMRouter()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({"response": "A dashboard with charts"}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    # 创建临时图片文件
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG fake image data")
        tmp_path = f.name

    try:
        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result = router.generate("describe this image", task_type="vision", images=[tmp_path])

        assert "dashboard" in result
        # 验证请求体包含 images 字段
        call_args = mock_urlopen.call_args
        req_obj = call_args[0][0]
        body = json.loads(req_obj.data.decode())
        assert "images" in body
        assert len(body["images"]) == 1
    finally:
        os.unlink(tmp_path)


def test_ocr_route_exists():
    """ocr 路由应存在且使用 glm-ocr 模型。"""
    assert "ocr" in ROUTES
    assert "glm-ocr" in ROUTES["ocr"]["model"]


def test_vision_no_fallback_when_ollama_down():
    """vision/ocr 路由没有 Claude fallback，Ollama 不可达应返回空字符串。"""
    router = LLMRouter()
    router._ollama_available = False

    result = router.generate("describe", task_type="vision", images=["fake.png"])
    assert result == ""
