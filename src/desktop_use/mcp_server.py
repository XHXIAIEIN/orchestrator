"""MCP Server for desktop_use — expose GUI automation as MCP tools.

Allows external agents (Claude Code, etc.) to use desktop_use operations
via the Model Context Protocol over SSE.
"""

import json
import logging
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """MCP tool definition."""
    name: str
    description: str
    input_schema: dict


@dataclass
class MCPResult:
    """MCP tool execution result."""
    content: list[dict]  # [{type: "text", text: "..."}, {type: "image", data: "base64..."}]
    is_error: bool = False


# Tool definitions for desktop_use operations
DESKTOP_TOOLS = [
    MCPTool(
        name="desktop_screenshot",
        description="Take a screenshot of the desktop or a specific monitor",
        input_schema={
            "type": "object",
            "properties": {
                "monitor_id": {"type": "integer", "description": "Monitor index (0=primary)", "default": 0},
            },
        },
    ),
    MCPTool(
        name="desktop_click",
        description="Click at a specific screen position",
        input_schema={
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
            },
            "required": ["x", "y"],
        },
    ),
    MCPTool(
        name="desktop_type",
        description="Type text at the current cursor position",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type"},
                "use_paste": {"type": "boolean", "description": "Use clipboard paste for long/special text", "default": False},
            },
            "required": ["text"],
        },
    ),
    MCPTool(
        name="desktop_hotkey",
        description="Press a keyboard shortcut",
        input_schema={
            "type": "object",
            "properties": {
                "keys": {"type": "array", "items": {"type": "string"}, "description": "Keys to press, e.g. ['ctrl', 'c']"},
            },
            "required": ["keys"],
        },
    ),
    MCPTool(
        name="desktop_scroll",
        description="Scroll at a position",
        input_schema={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "clicks": {"type": "integer", "description": "Positive=up, negative=down"},
            },
            "required": ["x", "y", "clicks"],
        },
    ),
    MCPTool(
        name="desktop_find_element",
        description="Find a UI element by text or description using OCR",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to find on screen"},
                "monitor_id": {"type": "integer", "default": 0},
            },
            "required": ["text"],
        },
    ),
]


class DesktopMCPServer:
    """MCP server that wraps desktop_use operations.

    Handles tool listing and execution. Transport (SSE/stdio) is handled separately.
    """

    def __init__(self, engine=None):
        """
        Args:
            engine: DesktopEngine instance (optional, lazy-initialized)
        """
        self._engine = engine
        self._tools = {t.name: t for t in DESKTOP_TOOLS}

    def list_tools(self) -> list[dict]:
        """Return MCP tool definitions."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in self._tools.values()
        ]

    async def call_tool(self, name: str, arguments: dict) -> MCPResult:
        """Execute an MCP tool call."""
        if name not in self._tools:
            return MCPResult(
                content=[{"type": "text", "text": f"Unknown tool: {name}"}],
                is_error=True,
            )

        try:
            handler = getattr(self, f"_handle_{name}", None)
            if handler:
                return await handler(arguments)
            return MCPResult(
                content=[{"type": "text", "text": f"Tool {name} not yet implemented"}],
                is_error=True,
            )
        except Exception as e:
            logger.error(f"MCP tool {name} failed: {e}")
            return MCPResult(
                content=[{"type": "text", "text": f"Error: {e}"}],
                is_error=True,
            )

    async def _handle_desktop_screenshot(self, args: dict) -> MCPResult:
        """Take screenshot and return as base64 image."""
        import base64
        if not self._engine:
            return MCPResult(content=[{"type": "text", "text": "No engine configured"}], is_error=True)

        monitor_id = args.get("monitor_id", 0)
        screenshot = self._engine._screen.capture(monitor_id)

        # Encode as base64 PNG
        from io import BytesIO
        try:
            from PIL import Image
            import numpy as np
            img = Image.fromarray(screenshot if isinstance(screenshot, np.ndarray) else screenshot)
            buf = BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
        except ImportError:
            b64 = base64.b64encode(screenshot).decode() if isinstance(screenshot, bytes) else ""

        return MCPResult(content=[
            {"type": "image", "data": b64, "mimeType": "image/png"},
        ])

    async def _handle_desktop_click(self, args: dict) -> MCPResult:
        """Click at position."""
        if not self._engine:
            return MCPResult(content=[{"type": "text", "text": "No engine configured"}], is_error=True)

        x, y = args["x"], args["y"]
        button = args.get("button", "left")
        self._engine._executor.click(x, y, button=button)
        return MCPResult(content=[{"type": "text", "text": f"Clicked {button} at ({x}, {y})"}])

    async def _handle_desktop_type(self, args: dict) -> MCPResult:
        """Type or paste text."""
        if not self._engine:
            return MCPResult(content=[{"type": "text", "text": "No engine configured"}], is_error=True)

        text = args["text"]
        if args.get("use_paste"):
            self._engine._executor.paste_text(text)
        else:
            self._engine._executor.type_text(text)
        return MCPResult(content=[{"type": "text", "text": f"Typed {len(text)} chars"}])

    async def _handle_desktop_hotkey(self, args: dict) -> MCPResult:
        """Press hotkey."""
        if not self._engine:
            return MCPResult(content=[{"type": "text", "text": "No engine configured"}], is_error=True)

        keys = args["keys"]
        self._engine._executor.hotkey(*keys)
        return MCPResult(content=[{"type": "text", "text": f"Pressed {'+'.join(keys)}"}])

    async def _handle_desktop_scroll(self, args: dict) -> MCPResult:
        """Scroll."""
        if not self._engine:
            return MCPResult(content=[{"type": "text", "text": "No engine configured"}], is_error=True)

        self._engine._executor.scroll(args["x"], args["y"], args["clicks"])
        return MCPResult(content=[{"type": "text", "text": f"Scrolled {args['clicks']} at ({args['x']}, {args['y']})"}])

    async def _handle_desktop_find_element(self, args: dict) -> MCPResult:
        """Find element by text."""
        if not self._engine:
            return MCPResult(content=[{"type": "text", "text": "No engine configured"}], is_error=True)

        text = args["text"]
        result = self._engine._matcher.locate(text)
        if result:
            return MCPResult(content=[{"type": "text", "text": json.dumps(asdict(result))}])
        return MCPResult(content=[{"type": "text", "text": f"Element '{text}' not found"}])
