"""emotion_tag 上下文推断层的单元测试。"""
from src.channels.base import ChannelMessage
from src.voice.tts import (
    infer_emotion,
    tag,
    _has_emotion_tag,
    _EVENT_EMOTIONS,
    _PRIORITY_EMOTIONS,
)


class TestInferEmotion:
    def test_event_type_exact_match(self):
        assert infer_emotion("health.degraded") == "语气严肃，带紧迫感"
        assert infer_emotion("task.completed") == "轻快满足"
        assert infer_emotion("doom_loop.detected") == "严厉警告"

    def test_priority_fallback(self):
        assert infer_emotion("unknown.event", "CRITICAL") == "紧急严肃"
        assert infer_emotion("unknown.event", "LOW") == "轻松随意"

    def test_empty_event_uses_priority(self):
        assert infer_emotion("", "HIGH") == "认真专注"
        assert infer_emotion("") == "平稳自然"

    def test_unknown_priority_defaults_normal(self):
        assert infer_emotion("", "BANANA") == "平稳自然"

    def test_event_type_overrides_priority(self):
        """event_type 精确匹配时忽略 priority。"""
        result = infer_emotion("task.failed", "LOW")
        assert result == "遗憾，略带无奈"

    def test_all_events_have_emotions(self):
        for event, emotion in _EVENT_EMOTIONS.items():
            assert emotion, f"{event} has empty emotion"
            assert infer_emotion(event) == emotion

    def test_all_priorities_have_emotions(self):
        for prio in ("CRITICAL", "HIGH", "NORMAL", "LOW"):
            assert prio in _PRIORITY_EMOTIONS


class TestHasEmotionTag:
    def test_tagged_text(self):
        assert _has_emotion_tag("[angry] 出错了")
        assert _has_emotion_tag("[轻松随意] 一切正常")

    def test_untagged_text(self):
        assert not _has_emotion_tag("一切正常")
        assert not _has_emotion_tag("系统 [注意] 后面有标签")

    def test_empty(self):
        assert not _has_emotion_tag("")


class TestTagFunction:
    def test_basic(self):
        assert tag("excited", "好消息") == "[excited] 好消息"

    def test_chinese_emotion(self):
        assert tag("轻快满足", "任务完成") == "[轻快满足] 任务完成"
