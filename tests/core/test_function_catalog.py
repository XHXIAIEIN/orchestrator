"""Tests for FunctionCatalog — stolen from ChatDev 2.0."""
import pytest
from typing import Optional, Annotated
from src.core.function_catalog import introspect_function, ParamMeta


def sample_simple(name: str, count: int = 5) -> str:
    """Greet someone N times."""
    return f"hello {name}" * count


def sample_complex(query: str, max_results: int = 10, include_meta: bool = False,
                   tags: list[str] | None = None) -> dict:
    """Search with filters.

    Searches the knowledge base with optional filtering.
    """
    return {}


def sample_annotated(
    url: Annotated[str, ParamMeta(description="Target URL to fetch")],
    timeout: Annotated[float, ParamMeta(description="Timeout in seconds")] = 30.0,
) -> str:
    """Fetch a URL."""
    return ""


def test_simple_introspection():
    info = introspect_function(sample_simple)
    assert info["name"] == "sample_simple"
    assert "Greet someone" in info["description"]
    assert len(info["parameters"]) == 2
    assert info["parameters"]["name"]["type"] == "string"
    assert info["parameters"]["name"]["required"] is True
    assert info["parameters"]["count"]["type"] == "integer"
    assert info["parameters"]["count"]["required"] is False
    assert info["parameters"]["count"]["default"] == 5


def test_complex_introspection():
    info = introspect_function(sample_complex)
    assert info["parameters"]["max_results"]["type"] == "integer"
    assert info["parameters"]["include_meta"]["type"] == "boolean"
    assert info["parameters"]["tags"]["type"] == "array"
    assert info["parameters"]["tags"]["required"] is False


def test_annotated_introspection():
    info = introspect_function(sample_annotated)
    assert info["parameters"]["url"]["description"] == "Target URL to fetch"
    assert info["parameters"]["timeout"]["description"] == "Timeout in seconds"
    assert info["parameters"]["timeout"]["default"] == 30.0


def test_json_schema_output():
    info = introspect_function(sample_simple)
    schema = info["json_schema"]
    assert schema["type"] == "object"
    assert "name" in schema["properties"]
    assert schema["properties"]["name"]["type"] == "string"
    assert "name" in schema["required"]
    assert "count" not in schema["required"]


def test_no_docstring():
    def bare(x: int) -> int:
        return x
    info = introspect_function(bare)
    assert info["description"] == ""
    assert info["parameters"]["x"]["type"] == "integer"
