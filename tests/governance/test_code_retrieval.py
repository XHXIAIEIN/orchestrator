"""Tests for Layered Code Retrieval."""
from src.governance.code_retrieval import CodeRetriever, RetrievalResult


def test_l0_surface_search(tmp_path):
    (tmp_path / "main.py").write_text("def hello():\n    print('world')\n")
    retriever = CodeRetriever(str(tmp_path))
    result = retriever.search("hello", layers=[0])
    assert len(result.matches) >= 1
    assert result.matches[0]["layer"] == 0
    assert "hello" in result.matches[0]["snippet"]


def test_l1_structural_search(tmp_path):
    (tmp_path / "auth.py").write_text(
        'def authenticate(user: str, password: str) -> bool:\n'
        '    """Check user credentials."""\n'
        '    return True\n'
    )
    retriever = CodeRetriever(str(tmp_path))
    result = retriever.search("authenticate", layers=[1])
    funcs = [m for m in result.matches if m.get("type") == "function"]
    assert len(funcs) >= 1
    assert "authenticate" in funcs[0]["signature"]


def test_l1_class_search(tmp_path):
    (tmp_path / "models.py").write_text("class UserModel(BaseModel):\n    pass\n")
    retriever = CodeRetriever(str(tmp_path))
    result = retriever.search("UserModel", layers=[1])
    classes = [m for m in result.matches if m.get("type") == "class"]
    assert len(classes) >= 1
    assert "UserModel" in classes[0]["signature"]


def test_no_matches(tmp_path):
    (tmp_path / "empty.py").write_text("x = 1\n")
    retriever = CodeRetriever(str(tmp_path))
    result = retriever.search("nonexistent", layers=[0, 1])
    assert len(result.matches) == 0


def test_to_context_respects_budget():
    result = RetrievalResult(query="test", layers_used=[0])
    for i in range(100):
        result.matches.append(
            {
                "file": f"file_{i}.py",
                "line": i,
                "snippet": "x" * 200,
                "layer": 0,
            }
        )
    ctx = result.to_context(max_tokens=500)
    assert "truncated" in ctx


def test_token_estimate(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    retriever = CodeRetriever(str(tmp_path))
    result = retriever.search("foo", layers=[0, 1])
    assert result.token_estimate > 0


def test_multi_layer(tmp_path):
    (tmp_path / "mod.py").write_text(
        "from os import path\n\n"
        "def process(data):\n"
        "    return data\n"
    )
    retriever = CodeRetriever(str(tmp_path))
    result = retriever.search("process", layers=[0, 1, 2])
    assert any(m.get("layer") == 0 for m in result.matches)
    assert any(m.get("layer") == 1 for m in result.matches)


def test_l2_enriches_with_imports(tmp_path):
    (tmp_path / "svc.py").write_text(
        "from pathlib import Path\n"
        "import logging\n\n"
        "def serve(req):\n"
        "    return req\n"
    )
    retriever = CodeRetriever(str(tmp_path))
    result = retriever.search("serve", layers=[0, 1, 2])
    enriched = [m for m in result.matches if m.get("imports")]
    assert len(enriched) >= 1
    assert "pathlib" in enriched[0]["imports"] or "logging" in enriched[0]["imports"]


def test_l2_finds_callers(tmp_path):
    (tmp_path / "lib.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "main.py").write_text("from lib import helper\nhelper()\n")
    retriever = CodeRetriever(str(tmp_path))
    result = retriever.search("helper", layers=[0, 1, 2])
    callers_found = [m for m in result.matches if m.get("callers")]
    assert len(callers_found) >= 1


def test_docstring_extraction(tmp_path):
    (tmp_path / "doc.py").write_text(
        'def documented():\n'
        '    """This function does things."""\n'
        '    pass\n'
    )
    retriever = CodeRetriever(str(tmp_path))
    result = retriever.search("documented", layers=[1])
    funcs = [m for m in result.matches if m.get("type") == "function"]
    assert len(funcs) >= 1
    assert "This function does things" in funcs[0].get("snippet", "")


def test_format_match_all_fields():
    result = RetrievalResult(query="test", layers_used=[0, 1, 2])
    result.matches.append(
        {
            "file": "a.py",
            "line": 10,
            "type": "function",
            "signature": "def foo(x)",
            "snippet": "do stuff",
            "imports": ["os", "sys"],
            "callers": ["bar.py", "baz.py"],
        }
    )
    ctx = result.to_context()
    assert "a.py:10" in ctx
    assert "function" in ctx
    assert "def foo(x)" in ctx
    assert "imports:" in ctx
    assert "called by:" in ctx
