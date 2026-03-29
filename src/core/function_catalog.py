"""FunctionCatalog — automatic function introspection + JSON Schema generation.

Stolen from ChatDev 2.0's utils/function_catalog.py.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Annotated, get_args, get_origin, get_type_hints, Union


@dataclass
class ParamMeta:
    description: str = ""
    enum: list[str] | None = None
    examples: list[Any] | None = None


_TYPE_MAP: dict[type, str] = {
    str: "string", int: "integer", float: "number", bool: "boolean",
    list: "array", dict: "object",
}


def _resolve_type(annotation: Any) -> tuple[str, ParamMeta | None]:
    if annotation is inspect.Parameter.empty or annotation is Any:
        return "string", None
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        base_type = args[0] if args else str
        meta = None
        for arg in args[1:]:
            if isinstance(arg, ParamMeta):
                meta = arg
                break
        json_type, _ = _resolve_type(base_type)
        return json_type, meta
    if origin is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if args:
            return _resolve_type(args[0])
        return "string", None
    if origin is list:
        return "array", None
    if origin is dict:
        return "object", None
    if isinstance(annotation, type):
        return _TYPE_MAP.get(annotation, "string"), None
    return "string", None


def introspect_function(fn: Callable) -> dict[str, Any]:
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:
        hints = {}
    doc = inspect.getdoc(fn) or ""
    first_para = doc.split("\n\n")[0].strip() if doc else ""
    description = first_para[:600]
    parameters: dict[str, dict[str, Any]] = {}
    json_properties: dict[str, dict[str, Any]] = {}
    required_params: list[str] = []
    for name, param in sig.parameters.items():
        if name in ("self", "cls", "_context"):
            continue
        annotation = hints.get(name, param.annotation)
        json_type, param_meta = _resolve_type(annotation)
        has_default = param.default is not inspect.Parameter.empty
        is_required = not has_default
        param_info: dict[str, Any] = {"type": json_type, "required": is_required}
        prop: dict[str, Any] = {"type": json_type}
        if has_default:
            param_info["default"] = param.default
            prop["default"] = param.default
        if param_meta and param_meta.description:
            param_info["description"] = param_meta.description
            prop["description"] = param_meta.description
        if param_meta and param_meta.enum:
            param_info["enum"] = param_meta.enum
            prop["enum"] = param_meta.enum
        parameters[name] = param_info
        json_properties[name] = prop
        if is_required:
            required_params.append(name)
    json_schema = {"type": "object", "properties": json_properties}
    if required_params:
        json_schema["required"] = required_params
    return {"name": fn.__name__, "description": description,
            "parameters": parameters, "json_schema": json_schema}
