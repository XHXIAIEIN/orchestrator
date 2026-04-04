"""Tests for src.proactive.messages.MessageGenerator."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.proactive.messages import MessageGenerator, TEMPLATES
from src.proactive.signals import Signal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signal(
    sig_id: str,
    tier: str,
    data: dict | None = None,
    title: str = "Test signal",
    severity: str = "medium",
) -> Signal:
    return Signal(
        id=sig_id,
        tier=tier,
        title=title,
        severity=severity,
        data=data or {},
    )


def _mock_router(return_value: str = "LLM response") -> MagicMock:
    router = MagicMock()
    router.generate.return_value = return_value
    return router


# ---------------------------------------------------------------------------
# Tier A — template rendering
# ---------------------------------------------------------------------------

class TestTierATemplate:
    def test_s1_uses_template(self):
        sig = _signal(
            "S1", "A",
            data={"collector": "github", "count": 3, "error": "timeout"},
            title="Collector failure",
        )
        gen = MessageGenerator(llm_router=None)
        result = gen.generate(sig)

        assert "github" in result
        assert "3" in result
        assert "timeout" in result
        # Must NOT call LLM (no router)
        assert "LLM response" not in result

    def test_s2_uses_template(self):
        sig = _signal("S2", "A", data={"name": "worker", "status": "exited(1)"})
        result = MessageGenerator(None).generate(sig)

        assert "worker" in result
        assert "exited(1)" in result

    def test_s3_uses_template(self):
        sig = _signal("S3", "A", data={"size_mb": 512, "delta_mb": 40})
        result = MessageGenerator(None).generate(sig)

        assert "512" in result
        assert "40" in result

    def test_s4_uses_template(self):
        sig = _signal("S4", "A", data={"count": 5, "last_summary": "failed to write"})
        result = MessageGenerator(None).generate(sig)

        assert "5" in result
        assert "failed to write" in result


# ---------------------------------------------------------------------------
# Tier D — template rendering
# ---------------------------------------------------------------------------

class TestTierDTemplate:
    def test_s11_uses_template(self):
        sig = _signal(
            "S11", "D",
            data={"repo": "XHXIAIEIN/cvui", "event_type": "star", "title": "New star"},
        )
        result = MessageGenerator(None).generate(sig)

        assert "XHXIAIEIN/cvui" in result
        assert "star" in result
        assert "New star" in result

    def test_s12_uses_template(self):
        sig = _signal(
            "S12", "D",
            data={"package": "requests", "severity": "high", "cve_id": "CVE-2024-0001"},
        )
        result = MessageGenerator(None).generate(sig)

        assert "requests" in result
        assert "high" in result
        assert "CVE-2024-0001" in result


# ---------------------------------------------------------------------------
# All Tier-A templates render without KeyError
# ---------------------------------------------------------------------------

_TIER_A_SAMPLE_DATA: dict[str, dict] = {
    "S1":  {"collector": "steam", "count": 2, "error": "connection refused"},
    "S2":  {"name": "bot", "status": "restarting"},
    "S3":  {"size_mb": 1024, "delta_mb": 128},
    "S4":  {"count": 7, "last_summary": "no output"},
    "S11": {"repo": "owner/repo", "event_type": "push", "title": "fix bug"},
    "S12": {"package": "flask", "severity": "critical", "cve_id": "CVE-2023-9999"},
}


@pytest.mark.parametrize("sig_id", list(TEMPLATES.keys()))
def test_all_templates_render(sig_id: str):
    """Every registered template must render without raising KeyError."""
    # Use tier "A" for S1-S4, "D" for S11-S12 — both are template tiers
    tier = "D" if sig_id.startswith("S1") and int(sig_id[1:]) >= 11 else "A"
    data = _TIER_A_SAMPLE_DATA[sig_id]
    sig = _signal(sig_id, tier, data=data)
    gen = MessageGenerator(llm_router=None)
    result = gen.generate(sig)
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Tier B — LLM routing
# ---------------------------------------------------------------------------

class TestTierBLLM:
    def test_tier_b_calls_router_generate(self):
        router = _mock_router("生成的消息内容")
        sig = _signal("S99", "B", title="Something important", severity="high",
                      data={"key": "value"})
        result = MessageGenerator(router).generate(sig)

        router.generate.assert_called_once()
        call_kwargs = router.generate.call_args
        assert call_kwargs.kwargs.get("task_type") == "chat"
        assert call_kwargs.kwargs.get("max_tokens") == 256
        assert call_kwargs.kwargs.get("temperature") == 0.6
        assert result == "生成的消息内容"

    def test_tier_b_prompt_contains_signal_data(self):
        router = _mock_router()
        sig = _signal("S99", "B", title="Alert title", severity="critical",
                      data={"metric": 99, "host": "prod-01"})
        MessageGenerator(router).generate(sig)

        prompt = router.generate.call_args.kwargs["prompt"]
        assert "Alert title" in prompt
        assert "critical" in prompt

    def test_tier_b_fallback_on_llm_exception(self):
        router = MagicMock()
        router.generate.side_effect = RuntimeError("LLM unavailable")
        sig = _signal("S99", "B", title="Fallback test", severity="low",
                      data={"foo": "bar"})
        result = MessageGenerator(router).generate(sig)

        # Must not raise — should return plain-text fallback
        assert "Fallback test" in result
        assert isinstance(result, str)

    def test_tier_b_fallback_when_router_is_none(self):
        sig = _signal("S99", "B", title="No router", severity="medium",
                      data={"x": 1})
        result = MessageGenerator(None).generate(sig)

        assert "No router" in result

    def test_tier_c_calls_router_generate(self):
        router = _mock_router("tier C 消息")
        sig = _signal("S88", "C", title="Info", severity="low", data={})
        result = MessageGenerator(router).generate(sig)

        router.generate.assert_called_once()
        assert result == "tier C 消息"


# ---------------------------------------------------------------------------
# Fallback — unknown template key
# ---------------------------------------------------------------------------

class TestFallback:
    def test_unknown_signal_id_falls_back(self):
        sig = _signal("S_UNKNOWN", "A", title="Unknown signal", data={"a": 1})
        result = MessageGenerator(None).generate(sig)

        # Should not raise; should contain the title
        assert "Unknown signal" in result

    def test_missing_data_key_falls_back(self):
        # S1 requires collector/count/error; provide none
        sig = _signal("S1", "A", title="Incomplete", data={})
        result = MessageGenerator(None).generate(sig)

        assert "Incomplete" in result

    def test_fallback_includes_data_fields(self):
        sig = _signal("S_NONE", "A", title="Fallback check", data={"k1": "v1", "k2": 2})
        gen = MessageGenerator(None)
        result = gen._fallback(sig)

        assert "Fallback check" in result
        assert "k1" in result
        assert "v1" in result
