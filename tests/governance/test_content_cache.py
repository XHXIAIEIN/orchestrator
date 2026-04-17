"""Tests for src.governance.content_cache — content-addressed cache key generation."""
import pytest
from src.governance.content_cache import content_cache_key


class TestContentCache:
    def test_same_input_same_key(self):
        k1 = content_cache_key("prompt A", [{"name": "tool1", "args": {}}])
        k2 = content_cache_key("prompt A", [{"name": "tool1", "args": {}}])
        assert k1 == k2

    def test_different_prompt_different_key(self):
        k1 = content_cache_key("prompt A", [{"name": "tool1", "args": {}}])
        k2 = content_cache_key("prompt B", [{"name": "tool1", "args": {}}])
        assert k1 != k2

    def test_different_tools_different_key(self):
        k1 = content_cache_key("prompt A", [{"name": "tool1", "args": {}}])
        k2 = content_cache_key("prompt A", [{"name": "tool2", "args": {}}])
        assert k1 != k2

    def test_returns_string(self):
        k = content_cache_key("test", [])
        assert isinstance(k, str)
        assert len(k) > 0
