"""The result shape an in-process MCP tool handler hands back to the SDK."""

from __future__ import annotations

ToolResult = dict[str, object]


def text_result(text: str, *, is_error: bool = False) -> ToolResult:
    """One text block; `is_error` is snake_case because that is the key the Python SDK reads."""
    return {"content": [{"type": "text", "text": text}], "is_error": is_error}
