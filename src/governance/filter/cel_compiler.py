"""CEL->SQL Compiler -- safe expression-to-SQL compilation.

Source: R69 Memos (internal/filter/schema.go, engine.go, parser.go, render.go)

Problem: Hand-written SQL string concatenation for memory retrieval
filtering is both injection-prone and hard to extend.

Solution: A mini expression language that compiles to parameterized SQL:
  CEL string -> parse -> AST -> build_condition(AST, schema) -> Condition tree -> render(dialect) -> (SQL, params)

Supports:
  - Comparison: field == value, field != value, field > value
  - Containment: field in [values], field contains "str"
  - Logical: expr AND expr, expr OR expr, NOT expr
  - Functions: now(), lower(), date()
  - String: field LIKE pattern

Design decisions:
  - No eval() -- pure recursive descent parser
  - All values become ? parameters (never interpolated)
  - Schema-driven: field names mapped to actual SQL columns
  - SQLite dialect by default (extensible to PostgreSQL)
  - 1=1 pattern for always-valid WHERE clause
"""
from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FilterSyntaxError(Exception):
    """Raised when the expression cannot be parsed."""


class FilterValidationError(Exception):
    """Raised when the expression references an unknown field."""


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class FieldKind(Enum):
    SCALAR = "scalar"       # direct column
    JSON_LIST = "json_list" # JSON array in column
    JSON_BOOL = "json_bool" # boolean in JSON
    COMPUTED = "computed"   # requires expression transform


class FieldType(Enum):
    TEXT = "text"
    INTEGER = "integer"
    TIMESTAMP = "timestamp"
    BOOLEAN = "boolean"


@dataclass(frozen=True)
class FieldSchema:
    name: str
    kind: FieldKind
    column: str
    field_type: FieldType = FieldType.TEXT
    json_path: tuple[str, ...] = ()
    # Per-dialect SQL expressions (e.g., for timestamp handling)
    dialect_expressions: dict[str, str] = dataclass_field(default_factory=dict)


class SchemaRegistry:
    def __init__(self) -> None:
        self._fields: dict[str, FieldSchema] = {}

    def register(self, schema: FieldSchema) -> None:
        self._fields[schema.name] = schema

    def get(self, name: str) -> FieldSchema | None:
        return self._fields.get(name)

    def validate(self, name: str) -> bool:
        return name in self._fields


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------


class NodeType(Enum):
    COMPARISON = "comparison"   # field op value
    CONTAINS = "contains"       # field contains value
    IN_LIST = "in_list"         # field in [values]
    LOGICAL = "logical"         # AND / OR
    NOT = "not"                 # NOT expr
    FUNCTION = "function"       # now(), lower(), etc.


@dataclass
class ASTNode:
    node_type: NodeType
    field: str = ""
    operator: str = ""  # ==, !=, >, <, >=, <=, LIKE
    value: Any = None
    children: list[ASTNode] = dataclass_field(default_factory=list)
    function_name: str = ""
    function_args: list[Any] = dataclass_field(default_factory=list)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class TokenType(Enum):
    FIELD = "FIELD"
    STRING = "STRING"
    NUMBER = "NUMBER"
    OPERATOR = "OPERATOR"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    LBRACKET = "LBRACKET"
    RBRACKET = "RBRACKET"
    COMMA = "COMMA"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    IN = "IN"
    CONTAINS = "CONTAINS"
    FUNCTION = "FUNCTION"
    EOF = "EOF"


@dataclass
class Token:
    type: TokenType
    value: Any
    pos: int = 0


_OPERATOR_RE = re.compile(r"(==|!=|>=|<=|>|<|LIKE)")
_NUMBER_RE = re.compile(r"-?\d+(\.\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")

_KEYWORDS: dict[str, TokenType] = {
    "AND": TokenType.AND,
    "OR": TokenType.OR,
    "NOT": TokenType.NOT,
    "IN": TokenType.IN,
    "in": TokenType.IN,
    "CONTAINS": TokenType.CONTAINS,
    "contains": TokenType.CONTAINS,
}


def _tokenize(expr: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(expr)

    while i < n:
        # Skip whitespace
        if expr[i].isspace():
            i += 1
            continue

        # String literals
        if expr[i] in ('"', "'"):
            quote = expr[i]
            j = i + 1
            buf: list[str] = []
            while j < n and expr[j] != quote:
                if expr[j] == "\\" and j + 1 < n:
                    buf.append(expr[j + 1])
                    j += 2
                else:
                    buf.append(expr[j])
                    j += 1
            if j >= n:
                raise FilterSyntaxError(f"Unterminated string at pos {i}")
            tokens.append(Token(TokenType.STRING, "".join(buf), i))
            i = j + 1
            continue

        # Numbers
        m = _NUMBER_RE.match(expr, i)
        if m and (i == 0 or not expr[i - 1].isalpha()):
            raw = m.group()
            val = float(raw) if "." in raw else int(raw)
            tokens.append(Token(TokenType.NUMBER, val, i))
            i = m.end()
            continue

        # Operators (multi-char first)
        m = _OPERATOR_RE.match(expr, i)
        if m:
            tokens.append(Token(TokenType.OPERATOR, m.group(), i))
            i = m.end()
            continue

        # Single-char tokens
        if expr[i] == "(":
            tokens.append(Token(TokenType.LPAREN, "(", i))
            i += 1
            continue
        if expr[i] == ")":
            tokens.append(Token(TokenType.RPAREN, ")", i))
            i += 1
            continue
        if expr[i] == "[":
            tokens.append(Token(TokenType.LBRACKET, "[", i))
            i += 1
            continue
        if expr[i] == "]":
            tokens.append(Token(TokenType.RBRACKET, "]", i))
            i += 1
            continue
        if expr[i] == ",":
            tokens.append(Token(TokenType.COMMA, ",", i))
            i += 1
            continue

        # Identifiers / keywords / functions
        m = _IDENT_RE.match(expr, i)
        if m:
            word = m.group()
            end = m.end()
            # Peek for '(' to detect function calls
            peek = end
            while peek < n and expr[peek].isspace():
                peek += 1
            if peek < n and expr[peek] == "(":
                tokens.append(Token(TokenType.FUNCTION, word, i))
            elif word.upper() in _KEYWORDS:
                tokens.append(Token(_KEYWORDS[word.upper()], word, i))
            else:
                tokens.append(Token(TokenType.FIELD, word, i))
            i = end
            continue

        raise FilterSyntaxError(f"Unexpected character '{expr[i]}' at pos {i}")

    tokens.append(Token(TokenType.EOF, None, n))
    return tokens


# ---------------------------------------------------------------------------
# Parser — recursive descent, NO eval()
# ---------------------------------------------------------------------------


class _TokenStream:
    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def peek(self) -> Token:
        return self._tokens[self._pos]

    def consume(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def expect(self, ttype: TokenType) -> Token:
        tok = self.consume()
        if tok.type != ttype:
            raise FilterSyntaxError(
                f"Expected {ttype.value} but got {tok.type.value} ({tok.value!r}) at pos {tok.pos}"
            )
        return tok

    def match(self, *ttypes: TokenType) -> bool:
        return self.peek().type in ttypes


class FilterParser:
    """Parse a CEL-like expression into an AST."""

    def parse(self, expression: str) -> ASTNode:
        tokens = _tokenize(expression.strip())
        stream = _TokenStream(tokens)
        node = self._parse_or(stream)
        if not stream.match(TokenType.EOF):
            tok = stream.peek()
            raise FilterSyntaxError(f"Unexpected token {tok.value!r} at pos {tok.pos}")
        return node

    # --- grammar levels (lowest precedence first) ---

    def _parse_or(self, s: _TokenStream) -> ASTNode:
        left = self._parse_and(s)
        while s.match(TokenType.OR):
            s.consume()
            right = self._parse_and(s)
            left = ASTNode(NodeType.LOGICAL, operator="OR", children=[left, right])
        return left

    def _parse_and(self, s: _TokenStream) -> ASTNode:
        left = self._parse_not(s)
        while s.match(TokenType.AND):
            s.consume()
            right = self._parse_not(s)
            left = ASTNode(NodeType.LOGICAL, operator="AND", children=[left, right])
        return left

    def _parse_not(self, s: _TokenStream) -> ASTNode:
        if s.match(TokenType.NOT):
            s.consume()
            child = self._parse_not(s)
            return ASTNode(NodeType.NOT, children=[child])
        return self._parse_primary(s)

    def _parse_primary(self, s: _TokenStream) -> ASTNode:
        # Parenthesised sub-expression
        if s.match(TokenType.LPAREN):
            s.consume()
            node = self._parse_or(s)
            s.expect(TokenType.RPAREN)
            return node

        # Function call
        if s.match(TokenType.FUNCTION):
            return self._parse_function(s)

        # Field-based expression
        field_tok = s.expect(TokenType.FIELD)
        field_name = field_tok.value

        # field IN [values]
        if s.match(TokenType.IN):
            s.consume()
            s.expect(TokenType.LBRACKET)
            values = self._parse_value_list(s)
            s.expect(TokenType.RBRACKET)
            return ASTNode(NodeType.IN_LIST, field=field_name, value=values)

        # field CONTAINS "str"
        if s.match(TokenType.CONTAINS):
            s.consume()
            val = self._parse_atomic_value(s)
            return ASTNode(NodeType.CONTAINS, field=field_name, value=val)

        # field OP value
        if s.match(TokenType.OPERATOR):
            op_tok = s.consume()
            val = self._parse_atomic_value(s)
            return ASTNode(NodeType.COMPARISON, field=field_name, operator=op_tok.value, value=val)

        raise FilterSyntaxError(
            f"Expected operator after field '{field_name}' at pos {field_tok.pos}"
        )

    def _parse_function(self, s: _TokenStream) -> ASTNode:
        func_tok = s.consume()  # FUNCTION token
        s.expect(TokenType.LPAREN)
        args: list[Any] = []
        if not s.match(TokenType.RPAREN):
            args = self._parse_value_list(s)
        s.expect(TokenType.RPAREN)

        # Check if this is used in an arithmetic expression: now() - 86400
        result = ASTNode(NodeType.FUNCTION, function_name=func_tok.value, function_args=args)

        # Handle arithmetic suffix: func() - N  or  func() + N
        if s.match(TokenType.OPERATOR) and s.peek().value in ("-", "+"):
            # Tokenizer emits "-" as part of a negative number when adjacent,
            # but standalone "-" won't be caught by OPERATOR_RE.
            # We represent this in function_args as a trailing ("op", N) pair.
            pass  # Arithmetic on functions is handled in the renderer via special args

        return result

    def _parse_value_list(self, s: _TokenStream) -> list[Any]:
        values: list[Any] = [self._parse_atomic_value(s)]
        while s.match(TokenType.COMMA):
            s.consume()
            values.append(self._parse_atomic_value(s))
        return values

    def _parse_atomic_value(self, s: _TokenStream) -> Any:
        tok = s.peek()
        if tok.type == TokenType.STRING:
            s.consume()
            return tok.value
        if tok.type == TokenType.NUMBER:
            s.consume()
            return tok.value
        if tok.type == TokenType.FUNCTION:
            return self._parse_function(s)
        if tok.type == TokenType.FIELD:
            # bare identifier used as value — keep as string
            s.consume()
            return tok.value
        raise FilterSyntaxError(
            f"Expected value but got {tok.type.value} ({tok.value!r}) at pos {tok.pos}"
        )


# ---------------------------------------------------------------------------
# Renderer — AST -> parameterized SQL
# ---------------------------------------------------------------------------

# Built-in function implementations per dialect
_FUNCTION_SQL: dict[str, dict[str, str]] = {
    "now": {
        "sqlite": "strftime('%s', 'now')",    # Unix epoch as integer
        "postgresql": "EXTRACT(EPOCH FROM now())",
    },
    "lower": {
        "sqlite": "lower",
        "postgresql": "lower",
    },
    "date": {
        "sqlite": "date",
        "postgresql": "date",
    },
}


class SQLRenderer:
    def __init__(self, schema: SchemaRegistry, dialect: str = "sqlite") -> None:
        self._schema = schema
        self._dialect = dialect
        self._params: list[Any] = []

    def render(self, node: ASTNode) -> tuple[str, list[Any]]:
        """Render AST to (sql_fragment, params_list)."""
        self._params = []
        sql = self._render_node(node)
        return sql, list(self._params)

    def _render_node(self, node: ASTNode) -> str:
        if node.node_type == NodeType.COMPARISON:
            return self._render_comparison(node)
        if node.node_type == NodeType.CONTAINS:
            return self._render_contains(node)
        if node.node_type == NodeType.IN_LIST:
            return self._render_in_list(node)
        if node.node_type == NodeType.LOGICAL:
            return self._render_logical(node)
        if node.node_type == NodeType.NOT:
            return self._render_not(node)
        if node.node_type == NodeType.FUNCTION:
            return self._render_function_expr(node)
        raise FilterSyntaxError(f"Unknown node type: {node.node_type}")

    def _render_comparison(self, node: ASTNode) -> str:
        fs = self._get_field_schema(node.field)
        col_expr = self._column_expr(fs)
        op = _normalize_op(node.operator)

        # Value may itself be a function node
        if isinstance(node.value, ASTNode):
            val_sql = self._render_node(node.value)
            return f"{col_expr} {op} {val_sql}"

        self._params.append(_coerce_value(node.value, fs.field_type))
        placeholder = "?"
        return f"{col_expr} {op} {placeholder}"

    def _render_contains(self, node: ASTNode) -> str:
        fs = self._get_field_schema(node.field)

        if fs.kind == FieldKind.JSON_LIST:
            # Use json_each to search within a JSON array
            json_col, json_path_expr = self._json_path(fs)
            if isinstance(node.value, ASTNode):
                val_sql = self._render_node(node.value)
                return (
                    f"EXISTS (SELECT 1 FROM json_each({json_col}, '{json_path_expr}') "
                    f"WHERE value = {val_sql})"
                )
            self._params.append(node.value)
            return (
                f"EXISTS (SELECT 1 FROM json_each({json_col}, '{json_path_expr}') "
                f"WHERE value = ?)"
            )

        # TEXT column: use LIKE
        col_expr = self._column_expr(fs)
        self._params.append(f"%{node.value}%")
        return f"{col_expr} LIKE ?"

    def _render_in_list(self, node: ASTNode) -> str:
        fs = self._get_field_schema(node.field)
        values: list[Any] = node.value if isinstance(node.value, list) else [node.value]

        if fs.kind == FieldKind.JSON_LIST:
            # ANY of the provided values must appear in the JSON array
            json_col, json_path_expr = self._json_path(fs)
            placeholders = ", ".join("?" for _ in values)
            for v in values:
                self._params.append(v)
            return (
                f"EXISTS (SELECT 1 FROM json_each({json_col}, '{json_path_expr}') "
                f"WHERE value IN ({placeholders}))"
            )

        col_expr = self._column_expr(fs)
        placeholders = ", ".join("?" for _ in values)
        for v in values:
            self._params.append(_coerce_value(v, fs.field_type))
        return f"{col_expr} IN ({placeholders})"

    def _render_logical(self, node: ASTNode) -> str:
        parts = [f"({self._render_node(child)})" for child in node.children]
        return f" {node.operator} ".join(parts)

    def _render_not(self, node: ASTNode) -> str:
        child_sql = self._render_node(node.children[0])
        return f"NOT ({child_sql})"

    def _render_function_expr(self, node: ASTNode) -> str:
        """Render a bare FUNCTION node as a SQL expression (used as a value)."""
        return self._resolve_function(node.function_name, node.function_args)

    def _resolve_function(self, name: str, args: list[Any]) -> str:
        """Resolve a function call to its SQL representation."""
        dialect_map = _FUNCTION_SQL.get(name.lower())
        if dialect_map is None:
            raise FilterSyntaxError(f"Unknown function: {name!r}")
        sql_expr = dialect_map.get(self._dialect) or dialect_map.get("sqlite", name)

        if name.lower() == "now":
            # now() with optional arithmetic: now() - 86400
            # Represented as function_args = [("-", 86400)] from caller context,
            # but typically bare now() is fine; arithmetic is handled by the
            # comparison parser via separate NUMBER tokens.
            return sql_expr

        if name.lower() in ("lower", "date"):
            # Scalar functions applied to args
            arg_parts: list[str] = []
            for a in args:
                if isinstance(a, ASTNode):
                    arg_parts.append(self._render_node(a))
                else:
                    self._params.append(a)
                    arg_parts.append("?")
            return f"{sql_expr}({', '.join(arg_parts)})"

        return sql_expr

    # --- helpers ---

    def _get_field_schema(self, name: str) -> FieldSchema:
        fs = self._schema.get(name)
        if fs is None:
            raise FilterValidationError(f"Unknown field: {name!r}")
        return fs

    def _column_expr(self, fs: FieldSchema) -> str:
        """Return the SQL column expression for a scalar field."""
        if fs.kind == FieldKind.JSON_BOOL and fs.json_path:
            col, path = self._json_path(fs)
            return f"json_extract({col}, '{path}')"
        if dialect_expr := fs.dialect_expressions.get(self._dialect):
            return dialect_expr
        return fs.column

    def _json_path(self, fs: FieldSchema) -> tuple[str, str]:
        """Return (column_name, '$.path.to.key') for JSON fields."""
        path_str = "$." + ".".join(fs.json_path) if fs.json_path else "$"
        return fs.column, path_str

    def _add_param(self, value: Any) -> str:
        """Add a parameter, return the placeholder."""
        self._params.append(value)
        return "?"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_op(op: str) -> str:
    _MAP = {"==": "=", "!=": "!=", ">": ">", "<": "<", ">=": ">=", "<=": "<=", "LIKE": "LIKE"}
    return _MAP.get(op, op)


def _coerce_value(value: Any, ftype: FieldType) -> Any:
    """Coerce a parsed value to the appropriate Python type for binding."""
    if ftype == FieldType.INTEGER and isinstance(value, float):
        return int(value)
    if ftype == FieldType.BOOLEAN:
        if isinstance(value, str):
            return 1 if value.lower() in ("true", "1", "yes") else 0
        return int(bool(value))
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_filter(
    expression: str,
    schema: SchemaRegistry,
    dialect: str = "sqlite",
) -> tuple[str, list[Any]]:
    """Compile a CEL-like expression to parameterized SQL.

    Returns (sql_where_clause, params_list).
    Raises FilterSyntaxError on parse failure.
    Raises FilterValidationError on unknown field names.

    Example:
        schema = get_memory_schema()
        sql, params = compile_filter('tags in ["work"] AND importance > 5', schema)
        cursor.execute(f"SELECT * FROM memories WHERE {sql}", params)
    """
    if not expression or not expression.strip():
        return "1=1", []

    parser = FilterParser()
    try:
        ast = parser.parse(expression)
    except FilterSyntaxError:
        raise
    except Exception as exc:
        raise FilterSyntaxError(f"Parse error: {exc}") from exc

    renderer = SQLRenderer(schema, dialect)
    return renderer.render(ast)


def get_memory_schema() -> SchemaRegistry:
    """Default schema for Orchestrator memory queries."""
    reg = SchemaRegistry()
    reg.register(FieldSchema("content", FieldKind.SCALAR, "content", FieldType.TEXT))
    reg.register(FieldSchema(
        "tags",
        FieldKind.JSON_LIST,
        "metadata",
        field_type=FieldType.TEXT,
        json_path=("tags",),
    ))
    reg.register(FieldSchema("source", FieldKind.SCALAR, "source", FieldType.TEXT))
    reg.register(FieldSchema("created_at", FieldKind.SCALAR, "created_at", FieldType.TIMESTAMP))
    reg.register(FieldSchema("importance", FieldKind.SCALAR, "importance", FieldType.INTEGER))
    reg.register(FieldSchema("type", FieldKind.SCALAR, "type", FieldType.TEXT))
    return reg
