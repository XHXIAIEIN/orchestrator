"""Tests for R75 Graphify query result writeback."""
import pytest
from pathlib import Path
from src.governance.learning.query_writeback import (
    save_query_result,
    list_query_results,
    prune_old_results,
)


def test_save_query_result_writes_markdown(tmp_path):
    out = save_query_result(
        question="How does X work?",
        answer="X works by Y.",
        source_refs=["src/x.py"],
        memory_dir=tmp_path,
        tags=["diagnostic"],
        department="engineering",
    )
    assert out is not None
    assert out.parent == tmp_path
    body = out.read_text(encoding="utf-8")
    assert "How does X work?" in body
    assert "X works by Y." in body
    assert 'department: "engineering"' in body
    assert "src/x.py" in body


def test_save_query_result_returns_none_on_empty_input(tmp_path):
    assert save_query_result("", "answer", memory_dir=tmp_path) is None
    assert save_query_result("q", "", memory_dir=tmp_path) is None


def test_prune_old_results_keeps_newest(tmp_path):
    for i in range(5):
        save_query_result(f"q{i}", f"a{i}", memory_dir=tmp_path)
    removed = prune_old_results(max_files=2, memory_dir=tmp_path)
    assert removed == 3
    assert len(list_query_results(memory_dir=tmp_path)) == 2
