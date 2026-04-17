"""Tests for src.governance.context.culture_inject — culture block injection."""
import pytest
from src.governance.context.culture_inject import inject_culture, render_culture, clear_cache


class TestCultureInject:
    def setup_method(self):
        clear_cache()

    def test_returns_string(self):
        result = inject_culture("base prompt here")
        assert isinstance(result, str)
        assert "base prompt here" in result

    def test_idempotent_injection(self):
        """inject_culture should not double-inject if marker is already present."""
        first = inject_culture("base prompt")
        second = inject_culture(first)
        assert first == second

    def test_injects_orchestrator_context(self):
        """If culture content exists, it should appear in the result."""
        result = inject_culture("base prompt")
        # Should contain the marker
        assert "orchestrator-culture" in result
        # Should not lose the original prompt
        assert "base prompt" in result


class TestRenderCulture:
    def setup_method(self):
        clear_cache()

    def test_renders_with_variables(self):
        result = render_culture(project="test-proj", department="eng")
        assert isinstance(result, str)
        assert len(result) > 0
