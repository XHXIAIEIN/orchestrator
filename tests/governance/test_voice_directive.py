"""Tests for Voice Directive System."""
from src.governance.voice_directive import (
    VoiceDirective, VoiceConfig, evaluate_voice, VoiceScore,
)


def test_default_directive():
    vd = VoiceDirective()
    block = vd.to_prompt_block()
    assert "Voice Directive" in block
    assert "direct" in block


def test_department_preset():
    vd = VoiceDirective.for_department("security")
    block = vd.to_prompt_block()
    assert "formal" in block
    assert "vulnerability" in block.lower()


def test_inject_into_prompt():
    vd = VoiceDirective()
    result = vd.inject("You are an assistant.")
    assert "You are an assistant." in result
    assert "Voice Directive" in result


def test_evaluate_direct_text():
    text = "Fix the bug in `src/auth.py:42`. Change the return type from `str` to `int`."
    score = evaluate_voice(text)
    assert score.directness > 0.8
    assert score.hedge_count == 0


def test_evaluate_hedgy_text():
    text = "I think perhaps you might want to consider maybe looking at the auth module. It seems like it could possibly be the issue."
    score = evaluate_voice(text)
    assert score.hedge_count > 0
    assert score.directness < 0.9


def test_evaluate_ai_words():
    text = "Let me delve into this tapestry of code to leverage our synergy and empower the ecosystem."
    score = evaluate_voice(text)
    assert score.ai_word_count >= 4
    assert score.overall < 0.7


def test_evaluate_corporate():
    text = "Let's circle back and touch base about the low-hanging fruit. We need to move the needle on this."
    score = evaluate_voice(text)
    assert score.corporate_count >= 2


def test_evaluate_empty():
    score = evaluate_voice("")
    assert score.overall == 0


def test_evaluate_specific_text():
    text = "Edit `/d/project/src/main.py:15` and change `timeout=30` to `timeout=60`. Run `pytest tests/test_main.py -v` to verify."
    score = evaluate_voice(text)
    assert score.specificity > 0.5


def test_custom_rules():
    config = VoiceConfig(custom_rules=["Never say sorry", "Always include code"])
    vd = VoiceDirective(config)
    block = vd.to_prompt_block()
    assert "Never say sorry" in block
    assert "Always include code" in block
