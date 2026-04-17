"""Tests for src.governance.pipeline.dangling_tool_fix — dangling tool call patching."""
import pytest
from src.governance.pipeline.dangling_tool_fix import patch_dangling_tool_calls


class TestDanglingToolFix:
    def test_no_dangling_passes_through(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result, report = patch_dangling_tool_calls(messages)
        assert result == messages
        assert not report.had_dangles

    def test_dangling_tool_call_gets_synthetic_response(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_123", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            # Missing tool response → dangling
        ]
        result, report = patch_dangling_tool_calls(messages)
        assert len(result) == 3  # original 2 + synthetic tool response
        assert result[-1]["role"] == "tool"
        assert result[-1]["tool_call_id"] == "call_123"
        assert report.dangling_found == 1

    def test_complete_tool_call_unchanged(self):
        messages = [
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_456", "function": {"name": "bash", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "call_456", "content": "done"},
        ]
        result, report = patch_dangling_tool_calls(messages)
        assert len(result) == 2  # unchanged
        assert not report.had_dangles
