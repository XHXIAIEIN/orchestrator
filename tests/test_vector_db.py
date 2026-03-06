import pytest
from src.storage.vector_db import VectorDB


def test_add_and_query(tmp_path):
    db = VectorDB(persist_dir=str(tmp_path / "vectors"))
    db.add_document(
        doc_id="test_1",
        text="今天写了很多 Python 代码，实现了一个 agent 系统",
        metadata={"source": "claude", "date": "2026-03-07"}
    )
    results = db.query("agent 系统开发", n_results=1)
    assert len(results) >= 1
    assert results[0]["id"] == "test_1"


def test_deduplicates_by_id(tmp_path):
    db = VectorDB(persist_dir=str(tmp_path / "vectors"))
    db.add_document("dup_1", "第一次添加", {})
    db.add_document("dup_1", "第二次添加", {})
    assert db.count() == 1
