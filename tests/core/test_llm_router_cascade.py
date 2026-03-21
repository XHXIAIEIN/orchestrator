import pytest
from unittest.mock import patch, MagicMock
from src.core.llm_router import LLMRouter, ROUTES, MODEL_TIERS


class TestCascade:
    def setup_method(self):
        self.router = LLMRouter()
        self.router._ollama_available = True

    def test_cascade_first_model_succeeds(self):
        """第一个模型成功时不尝试后续模型。"""
        with patch.object(self.router, '_ollama_generate', return_value="good response here"):
            result = self.router.generate("test", "scrutiny")
            assert result == "good response here"

    def test_cascade_fallback_on_garbage(self):
        """第一个模型返回垃圾时尝试下一个。"""
        with patch.object(self.router, '_ollama_generate', return_value="x"):
            with patch.object(self.router, '_claude_generate', return_value="proper analysis result"):
                result = self.router.generate("test", "scrutiny")
                assert result == "proper analysis result"

    def test_cascade_skip_ollama_if_unavailable(self):
        """Ollama 不可达时直接跳到 Claude。"""
        self.router._ollama_available = False
        with patch.object(self.router, '_claude_generate', return_value="claude fallback works"):
            result = self.router.generate("test", "scrutiny")
            assert result == "claude fallback works"

    def test_non_cascade_route_unchanged(self):
        """没有 cascade 字段的路由走原有逻辑。"""
        # summary 没有 cascade，应走 claude 直调
        with patch.object(self.router, '_claude_generate', return_value="summary result"):
            result = self.router.generate("test", "summary")
            assert result == "summary result"

    def test_model_tiers_defined(self):
        """MODEL_TIERS 应包含所有 cascade 中引用的模型。"""
        for task_type, route in ROUTES.items():
            if "cascade" in route:
                for model_id in route["cascade"]:
                    assert model_id in MODEL_TIERS, f"{model_id} in {task_type} cascade but not in MODEL_TIERS"
