import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from src.collectors.claude_memory.collector import ClaudeMemoryCollector


@pytest.fixture
def mock_memory_dir(tmp_path):
    """Create a fake Claude memory structure."""
    project_dir = tmp_path / "projects" / "test-project" / "memory"
    project_dir.mkdir(parents=True)

    # Create a memory file with frontmatter
    (project_dir / "feedback_test.md").write_text(
        "---\nname: feedback_test\ndescription: test feedback\ntype: feedback\n---\n\nDon't do X, always do Y.",
        encoding="utf-8",
    )

    # Create another memory file
    (project_dir / "user_role.md").write_text(
        "---\nname: user_role\ndescription: user is a developer\ntype: user\n---\n\nSenior Python developer.",
        encoding="utf-8",
    )

    # Create MEMORY.md index (should be skipped)
    (project_dir / "MEMORY.md").write_text(
        "# Memory Index\n- feedback_test.md\n- user_role.md",
        encoding="utf-8",
    )

    return tmp_path


def _make_collector(return_value=True):
    """Return a collector with a mocked DB whose insert_event returns return_value."""
    db = MagicMock()
    db.insert_event.return_value = return_value
    db.write_log.return_value = None
    return ClaudeMemoryCollector(db)


def test_metadata():
    meta = ClaudeMemoryCollector.metadata()
    assert meta.name == "claude_memory"
    assert meta.category == "optional"
    assert "claude_memory" in meta.event_sources
    assert meta.default_enabled is True


def test_preflight_no_claude_home():
    collector = _make_collector()
    with patch("src.collectors.claude_memory.collector._CLAUDE_HOME", Path("/nonexistent")):
        ok, msg = collector.preflight()
    assert not ok
    assert "not found" in msg


def test_preflight_no_memory_dirs(tmp_path):
    # claude home exists but has no projects/*/memory dirs
    collector = _make_collector()
    with patch("src.collectors.claude_memory.collector._CLAUDE_HOME", tmp_path):
        ok, msg = collector.preflight()
    assert not ok
    assert "No Claude Code memory" in msg


def test_preflight_success(mock_memory_dir):
    collector = _make_collector()
    with patch("src.collectors.claude_memory.collector._CLAUDE_HOME", mock_memory_dir):
        ok, msg = collector.preflight()
    assert ok
    assert "1 project" in msg


def test_collect_reads_memory_files(mock_memory_dir):
    collector = _make_collector(return_value=True)
    with patch("src.collectors.claude_memory.collector._CLAUDE_HOME", mock_memory_dir):
        count = collector.collect()
    assert count == 2  # 2 memory files (MEMORY.md skipped)
    assert collector.db.insert_event.call_count == 2


def test_collect_skips_index_file(mock_memory_dir):
    collector = _make_collector(return_value=True)
    with patch("src.collectors.claude_memory.collector._CLAUDE_HOME", mock_memory_dir):
        collector.collect()
    for call in collector.db.insert_event.call_args_list:
        _, kwargs = call
        metadata = kwargs.get("metadata", {})
        assert metadata.get("file") != "MEMORY.md"


def test_collect_source_is_claude_memory(mock_memory_dir):
    collector = _make_collector(return_value=True)
    with patch("src.collectors.claude_memory.collector._CLAUDE_HOME", mock_memory_dir):
        collector.collect()
    for call in collector.db.insert_event.call_args_list:
        _, kwargs = call
        assert kwargs.get("source") == "claude_memory"


def test_collect_tags_is_list(mock_memory_dir):
    collector = _make_collector(return_value=True)
    with patch("src.collectors.claude_memory.collector._CLAUDE_HOME", mock_memory_dir):
        collector.collect()
    for call in collector.db.insert_event.call_args_list:
        _, kwargs = call
        assert isinstance(kwargs.get("tags"), list)


def test_collect_dedup_not_counted(mock_memory_dir):
    """When insert_event returns False (already exists), count should not increase."""
    collector = _make_collector(return_value=False)
    with patch("src.collectors.claude_memory.collector._CLAUDE_HOME", mock_memory_dir):
        count = collector.collect()
    assert count == 0
    assert collector.db.insert_event.call_count == 2  # still called, just not counted


def test_collect_skips_file_without_frontmatter(tmp_path):
    project_dir = tmp_path / "projects" / "proj" / "memory"
    project_dir.mkdir(parents=True)
    (project_dir / "no_frontmatter.md").write_text("Just plain text", encoding="utf-8")

    collector = _make_collector()
    with patch("src.collectors.claude_memory.collector._CLAUDE_HOME", tmp_path):
        count = collector.collect()
    assert count == 0
    collector.db.insert_event.assert_not_called()


def test_collect_handles_chinese_content(tmp_path):
    project_dir = tmp_path / "projects" / "proj" / "memory"
    project_dir.mkdir(parents=True)
    (project_dir / "chinese_mem.md").write_text(
        "---\nname: chinese_mem\ntype: feedback\n---\n\n用中文写的记忆内容，测试编码处理。",
        encoding="utf-8",
    )

    collector = _make_collector(return_value=True)
    with patch("src.collectors.claude_memory.collector._CLAUDE_HOME", tmp_path):
        count = collector.collect()
    assert count == 1


def test_parse_frontmatter():
    content = "---\nname: test\ntype: feedback\ndescription: hello\n---\nBody text"
    result = ClaudeMemoryCollector._parse_frontmatter(content)
    assert result["name"] == "test"
    assert result["type"] == "feedback"
    assert result["description"] == "hello"


def test_parse_frontmatter_invalid():
    result = ClaudeMemoryCollector._parse_frontmatter("No frontmatter here")
    assert result is None


def test_strip_frontmatter():
    content = "---\nname: test\n---\nBody here"
    body = ClaudeMemoryCollector._strip_frontmatter(content)
    assert body.strip() == "Body here"
    assert "---" not in body


def test_type_score():
    assert ClaudeMemoryCollector._type_score("feedback") == 0.9
    assert ClaudeMemoryCollector._type_score("user") == 0.8
    assert ClaudeMemoryCollector._type_score("project") == 0.7
    assert ClaudeMemoryCollector._type_score("reference") == 0.5
    assert ClaudeMemoryCollector._type_score("unknown") == 0.3
    assert ClaudeMemoryCollector._type_score("garbage") == 0.3
