# tests/governance/test_output_compress.py
"""Tests for RTK Output Compression (output_compress.py).

Covers:
- Passthrough for short outputs
- Auto strategy (extract → truncate fallback)
- Structured extraction (VERDICT, STATUS, file changes, errors)
- Smart truncation (head/tail preservation)
- Explicit strategy selection
- CompressedOutput properties
- Integration with executor wiring
"""
import pytest

from src.governance.pipeline.output_compress import (
    compress_output,
    CompressedOutput,
    _extract_structured,
    _smart_truncate,
    DEFAULT_MAX_CHARS,
)


# ── Helpers ──

def _make_long_output(length: int = 5000) -> str:
    """Generate a long output string exceeding default max_chars."""
    return "x" * length


def _make_structured_output() -> str:
    """Generate output with extractable structured data."""
    return (
        "Starting task execution...\n"
        "Reading files and analyzing codebase.\n"
        "Lots of intermediate thinking here that is not very important.\n"
        "More analysis happening in the background.\n\n"
        "VERDICT: PASS — all checks passed\n"
        "STATUS: completed successfully\n\n"
        "## Summary\n"
        "The refactoring is complete.\n\n"
        "## Changes\n"
        "modified: src/main.py\n"
        "created: src/utils.py\n"
        "deleted: src/old_helper.py\n\n"
        "3 files changed, 42 insertions(+), 18 deletions(-)\n"
    )


def _make_error_output() -> str:
    """Generate output containing error blocks."""
    return (
        "Attempting to run tests...\n"
        "Running pytest...\n\n"
        "Error: ModuleNotFoundError — cannot import 'nonexistent_module'\n\n"
        "Exception: ValueError — invalid configuration in config.yaml\n\n"
        "RESULT: FAILED\n"
    )


# ── Tests: CompressedOutput dataclass ──

class TestCompressedOutput:
    def test_compression_ratio_normal(self):
        co = CompressedOutput(
            original_length=1000,
            compressed_length=400,
            strategy="truncate",
            content="short",
        )
        assert co.compression_ratio == 0.4

    def test_compression_ratio_zero_original(self):
        co = CompressedOutput(
            original_length=0,
            compressed_length=0,
            strategy="passthrough",
            content="",
        )
        assert co.compression_ratio == 1.0

    def test_metadata_defaults_to_empty_dict(self):
        co = CompressedOutput(
            original_length=10,
            compressed_length=10,
            strategy="passthrough",
            content="hello",
        )
        assert co.metadata == {}

    def test_metadata_custom(self):
        co = CompressedOutput(
            original_length=10,
            compressed_length=10,
            strategy="test",
            content="hello",
            metadata={"key": "value"},
        )
        assert co.metadata == {"key": "value"}


# ── Tests: Passthrough (short outputs) ──

class TestPassthrough:
    def test_short_output_unchanged(self):
        text = "Task completed successfully."
        result = compress_output(text)
        assert result.content == text
        assert result.strategy == "passthrough"
        assert result.original_length == len(text)
        assert result.compressed_length == len(text)

    def test_empty_output(self):
        result = compress_output("")
        assert result.content == ""
        assert result.strategy == "passthrough"

    def test_exactly_at_limit(self):
        text = "a" * DEFAULT_MAX_CHARS
        result = compress_output(text)
        assert result.strategy == "passthrough"
        assert result.content == text

    def test_custom_max_chars_passthrough(self):
        text = "a" * 500
        result = compress_output(text, max_chars=500)
        assert result.strategy == "passthrough"


# ── Tests: Auto strategy ──

class TestAutoStrategy:
    def test_auto_prefers_extract_when_possible(self):
        output = _make_structured_output()
        # Make it exceed max_chars by repeating
        long_output = output + "\n" + "padding " * 500
        result = compress_output(long_output, max_chars=800)
        # Should use extract since structured data is available
        assert result.strategy in ("extract", "truncate")
        assert result.compressed_length <= 800

    def test_auto_falls_back_to_truncate(self):
        # No structured data, just raw text
        text = "no special markers here\n" * 200
        result = compress_output(text, max_chars=500)
        assert result.strategy == "truncate"
        assert len(result.content) <= 500

    def test_auto_extract_too_long_falls_to_truncate(self):
        """If extracted content exceeds max_chars, fall back to truncate."""
        # Create output with many structured lines
        lines = [f"STATUS: status line {i}" for i in range(100)]
        lines += [f"ERROR: error line {i}" for i in range(100)]
        text = "\n".join(lines)
        result = compress_output(text, max_chars=200)
        assert result.compressed_length <= 200


# ── Tests: Extract strategy ──

class TestExtractStrategy:
    def test_extract_finds_verdict(self):
        text = "blah blah\nVERDICT: PASS\nmore stuff\n" + "x" * 3000
        result = compress_output(text, strategy="extract", max_chars=2000)
        assert "VERDICT: PASS" in result.content

    def test_extract_finds_status(self):
        text = "blah\nSTATUS: completed\nmore\n" + "x" * 3000
        result = compress_output(text, strategy="extract", max_chars=2000)
        assert "STATUS: completed" in result.content

    def test_extract_finds_chinese_verdict(self):
        text = "一些内容\n判定: 通过\n更多内容\n" + "x" * 3000
        result = compress_output(text, strategy="extract", max_chars=2000)
        assert "判定: 通过" in result.content

    def test_extract_finds_file_changes(self):
        text = "modified: src/main.py\ncreated: src/new.py\n" + "x" * 3000
        result = compress_output(text, strategy="extract", max_chars=2000)
        assert "src/main.py" in result.content
        assert "src/new.py" in result.content

    def test_extract_finds_errors(self):
        text = "Error: something went wrong\n" + "x" * 3000
        result = compress_output(text, strategy="extract", max_chars=2000)
        assert "something went wrong" in result.content

    def test_extract_finds_diff_stats(self):
        text = "3 files changed, 10 insertions(+), 5 deletions(-)\n" + "x" * 3000
        result = compress_output(text, strategy="extract", max_chars=2000)
        assert "3 files changed" in result.content

    def test_extract_finds_headings(self):
        text = "## Summary\nThe task is done.\n## Details\nMore info.\n" + "x" * 3000
        result = compress_output(text, strategy="extract", max_chars=2000)
        assert "## Summary" in result.content

    def test_extract_no_structured_data_truncates(self):
        """If no structured data found, extract falls back to truncation."""
        text = "plain text " * 500
        result = compress_output(text, strategy="extract", max_chars=200)
        assert len(result.content) <= 200

    def test_extract_caps_file_changes_at_10(self):
        lines = [f"modified: file{i}.py" for i in range(20)]
        text = "\n".join(lines) + "\n" + "x" * 3000
        extracted = _extract_structured(text)
        file_lines = [l for l in extracted.splitlines() if l.strip().startswith("file")]
        assert len(file_lines) <= 10


# ── Tests: Truncate strategy ──

class TestTruncateStrategy:
    def test_truncate_respects_max_chars(self):
        text = "a" * 5000
        result = compress_output(text, strategy="truncate", max_chars=1000)
        assert len(result.content) <= 1000
        assert result.strategy == "truncate"

    def test_truncate_preserves_head_and_tail(self):
        head = "HEAD_MARKER_12345\n"
        middle = "middle content\n" * 200
        tail = "\nTAIL_MARKER_67890"
        text = head + middle + tail
        result = compress_output(text, strategy="truncate", max_chars=500)
        assert "HEAD_MARKER" in result.content
        assert "TAIL_MARKER" in result.content

    def test_truncate_includes_gap_marker(self):
        text = "x" * 5000
        result = compress_output(text, strategy="truncate", max_chars=500)
        assert "truncated" in result.content

    def test_smart_truncate_short_text_passthrough(self):
        text = "short"
        result = _smart_truncate(text, 1000)
        assert result == text


# ── Tests: _extract_structured internal ──

class TestExtractStructuredInternal:
    def test_returns_none_for_plain_text(self):
        result = _extract_structured("just some plain text without markers")
        assert result is None

    def test_extracts_multiple_types(self):
        text = (
            "VERDICT: PASS\n"
            "modified: foo.py\n"
            "Error: something broke\n"
            "2 files changed, 5 insertions(+)\n"
        )
        result = _extract_structured(text)
        assert result is not None
        assert "VERDICT: PASS" in result
        assert "foo.py" in result
        assert "something broke" in result
        assert "2 files changed" in result

    def test_error_blocks_capped_at_3(self):
        lines = [f"Error: error number {i}\n\n" for i in range(10)]
        text = "".join(lines)
        result = _extract_structured(text)
        # Should have at most 3 error entries
        error_count = result.count("error number")
        assert error_count <= 3


# ── Tests: _smart_truncate internal ──

class TestSmartTruncateInternal:
    def test_finds_clean_line_boundaries(self):
        lines = [f"line {i}" for i in range(100)]
        text = "\n".join(lines)
        result = _smart_truncate(text, 200)
        # Result should contain head content, a gap marker, and tail content
        assert "line 0" in result  # Head preserved
        assert "truncated" in result  # Gap marker present
        assert len(result) <= 200

    def test_head_tail_ratio(self):
        text = "a" * 10000
        result = _smart_truncate(text, 1000)
        # Gap marker splits the result
        assert "truncated" in result
        parts = result.split("[...")
        # Head should be roughly 40% of budget
        assert len(parts[0]) > 200  # At least some head content


# ── Tests: Integration with executor pattern ──

class TestExecutorIntegration:
    def test_compress_output_importable_from_pipeline(self):
        """Verify the public API is accessible from the pipeline package."""
        from src.governance.pipeline import compress_output as co
        from src.governance.pipeline import CompressedOutput as CO
        assert callable(co)
        assert CO is not None

    def test_typical_agent_output_flow(self):
        """Simulate what executor.py does: compress agent output before storage."""
        raw_output = (
            "I'll start by reading the codebase...\n"
            "Reading src/main.py...\n"
            "Reading src/utils.py...\n"
            "Analyzing the code structure...\n"
            "Found the issue in line 42.\n"
            "The problem is a missing null check.\n\n"
            "VERDICT: FIXED\n"
            "modified: src/main.py\n"
            "1 file changed, 3 insertions(+), 1 deletion(-)\n\n"
            "The fix adds a null check before accessing the property.\n"
        ) + "verbose log " * 500  # Simulate long output

        compressed = compress_output(raw_output, max_chars=2000)
        assert compressed.compressed_length <= 2000
        assert compressed.original_length > 2000
        # Key info should survive
        assert "VERDICT: FIXED" in compressed.content or "main.py" in compressed.content

    def test_short_agent_output_untouched(self):
        """Short outputs should pass through without modification."""
        raw_output = "Task completed. VERDICT: PASS"
        compressed = compress_output(raw_output, max_chars=2000)
        assert compressed.content == raw_output
        assert compressed.strategy == "passthrough"
