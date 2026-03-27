"""Text Tool Call Recovery — parse non-standard tool calls from local models.

Local models (Ollama, etc.) sometimes output tool calls as text instead of
structured JSON. This module recovers structured tool calls from 13+ formats:
ReAct, XML, bare JSON, markdown blocks, function-call syntax, etc.

Based on OpenFang's text_tool_call_recovery module.
"""

import json
import re
from dataclasses import dataclass


@dataclass
class RecoveredToolCall:
    tool_name: str
    arguments: dict
    format_detected: str  # which format was matched
    confidence: float     # 0-1


def recover_tool_calls(text: str) -> list[RecoveredToolCall]:
    """Try to extract tool calls from free-form text.

    Attempts formats in order of specificity (most structured first).
    Returns all recovered calls.
    """
    results = []

    # 1. JSON code block: ```json\n{"tool": "name", "args": {...}}\n```
    for m in re.finditer(r'```(?:json)?\s*\n({[^`]+})\s*\n```', text, re.DOTALL):
        parsed = _try_parse_json_tool(m.group(1))
        if parsed:
            parsed.format_detected = "json_code_block"
            parsed.confidence = 0.9
            results.append(parsed)

    # 2. XML-style: <tool_call><name>X</name><args>...</args></tool_call>
    for m in re.finditer(r'<tool_call>\s*<name>(.*?)</name>\s*<args>(.*?)</args>\s*</tool_call>', text, re.DOTALL):
        try:
            args = json.loads(m.group(2))
            results.append(RecoveredToolCall(m.group(1).strip(), args, "xml_tool_call", 0.85))
        except json.JSONDecodeError:
            pass

    # 3. ReAct format: Action: tool_name\nAction Input: {...}
    for m in re.finditer(r'Action:\s*(\w+)\s*\nAction Input:\s*({[^\n]+})', text):
        try:
            args = json.loads(m.group(2))
            results.append(RecoveredToolCall(m.group(1), args, "react", 0.8))
        except json.JSONDecodeError:
            pass

    # 4. Function call: tool_name(arg1="val1", arg2="val2")
    for m in re.finditer(r'(\w+)\(([^)]+)\)', text):
        args = _parse_function_args(m.group(2))
        if args:
            results.append(RecoveredToolCall(m.group(1), args, "function_call", 0.7))

    # 5. Bare JSON object with tool/name/function key
    for m in re.finditer(r'({[^{}]{10,500}})', text):
        parsed = _try_parse_json_tool(m.group(1))
        if parsed:
            parsed.format_detected = "bare_json"
            parsed.confidence = 0.6
            results.append(parsed)

    # 6. YAML-ish: tool: name\n  arg1: val1
    for m in re.finditer(r'(?:tool|function):\s*(\w+)\n((?:\s+\w+:.*\n?)+)', text):
        args = _parse_yaml_args(m.group(2))
        if args:
            results.append(RecoveredToolCall(m.group(1), args, "yaml_ish", 0.5))

    return results


def _try_parse_json_tool(text: str) -> RecoveredToolCall | None:
    """Try to parse a JSON blob as a tool call."""
    try:
        obj = json.loads(text.strip())
    except json.JSONDecodeError:
        return None

    # Look for tool name in various keys
    name = obj.get("tool") or obj.get("name") or obj.get("function") or obj.get("tool_name")
    if not name:
        return None

    # Look for args
    args = obj.get("args") or obj.get("arguments") or obj.get("parameters") or obj.get("input") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {"input": args}

    return RecoveredToolCall(str(name), args, "", 0.0)


def _parse_function_args(text: str) -> dict | None:
    """Parse key=value function arguments."""
    args = {}
    for m in re.finditer(r'(\w+)\s*=\s*(?:"([^"]*)"|([\w.]+))', text):
        key = m.group(1)
        val = m.group(2) if m.group(2) is not None else m.group(3)
        # Try to parse as number/bool
        if val.lower() in ("true", "false"):
            val = val.lower() == "true"
        else:
            try:
                val = int(val)
            except ValueError:
                try:
                    val = float(val)
                except ValueError:
                    pass
        args[key] = val
    return args if args else None


def _parse_yaml_args(text: str) -> dict | None:
    """Parse simple YAML-ish key: value pairs."""
    args = {}
    for line in text.strip().split("\n"):
        m = re.match(r'\s+(\w+):\s*(.+)', line)
        if m:
            key = m.group(1)
            val = m.group(2).strip().strip('"').strip("'")
            args[key] = val
    return args if args else None
