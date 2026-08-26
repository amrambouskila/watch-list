"""Wrap a tool handler so its failures are logged in-process rather than lost to the SDK."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from tv_watchlist.agent.tool_result import ToolResult, text_result

ToolHandler = Callable[[dict[str, object]], Awaitable[ToolResult]]

_logger = logging.getLogger(__name__)


def log_handler_failures(tool_name: str, handler: ToolHandler) -> ToolHandler:
    """`create_sdk_mcp_server` catches every handler exception, so this is the only place it is seen."""

    async def guarded(args: dict[str, object]) -> ToolResult:
        try:
            return await handler(args)
        except Exception as error:
            _logger.exception("tool %s failed", tool_name)
            return text_result(f"{type(error).__name__}: {error}", is_error=True)

    return guarded
