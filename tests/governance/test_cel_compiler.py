"""Tests for src.governance.filter.cel_compiler — CEL->SQL compilation."""
import pytest
from src.governance.filter.cel_compiler import (
    compile_filter, get_memory_schema, FilterValidationError,
)


class TestCelCompiler:
    def test_simple_equality(self):
        schema = get_memory_schema()
        sql, params = compile_filter('content == "test"', schema)
        assert "content" in sql
        assert "test" in params

    def test_numeric_comparison(self):
        schema = get_memory_schema()
        sql, params = compile_filter('importance > 5', schema)
        assert ">" in sql
        assert 5 in params

    def test_logical_and(self):
        schema = get_memory_schema()
        sql, params = compile_filter('importance > 3 AND content == "x"', schema)
        assert "AND" in sql

    def test_in_operator(self):
        schema = get_memory_schema()
        sql, params = compile_filter('tags in ["work", "urgent"]', schema)
        assert len(params) >= 2

    def test_invalid_field_raises(self):
        schema = get_memory_schema()
        with pytest.raises(FilterValidationError):
            compile_filter('nonexistent_field == 1', schema)

    def test_injection_attempt_safe(self):
        """SQL injection via filter expression should be parameterized, never raw."""
        schema = get_memory_schema()
        sql, params = compile_filter('content == "Robert\'; DROP TABLE--"', schema)
        # The dangerous string should be in params (safe), not in sql (unsafe)
        assert "DROP" not in sql
        assert any("DROP" in str(p) for p in params)
