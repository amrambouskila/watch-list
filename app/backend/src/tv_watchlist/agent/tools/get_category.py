"""The read-only tool that shows Claude one category's columns and rows."""

from __future__ import annotations

import json

from claude_agent_sdk import SdkMcpTool, tool
from mcp.types import ToolAnnotations

from tv_watchlist.agent.constants import GET_CATEGORY_TOOL
from tv_watchlist.agent.handler_guard import log_handler_failures
from tv_watchlist.agent.read_log import ReadLog
from tv_watchlist.agent.tool_result import ToolResult, text_result
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.errors import WorkbookError

_DESCRIPTION = (
    "Read one category's full grid: its column vocabulary and every row, keyed by column key. "
    "Use it before proposing an edit so new rows match the sheet's own columns and style."
)
_SCHEMA = {
    "type": "object",
    "properties": {"category_id": {"type": "string", "description": "The category id from the library digest."}},
    "required": ["category_id"],
}


def build_get_category_tool(catalog: Catalog, read_log: ReadLog) -> SdkMcpTool[dict[str, object]]:
    """Bind the read-only category tool to the process-wide catalog and this session's read log."""

    async def read_category(args: dict[str, object]) -> ToolResult:
        category_id = str(args["category_id"])
        try:
            detail = await catalog.detail(category_id)
        except WorkbookError as error:
            return text_result(f"{type(error).__name__}: {error}", is_error=True)
        read_log.record(detail.id, detail.mtime)
        return text_result(json.dumps(detail.model_dump(include={"columns", "rows"})))

    return tool(
        GET_CATEGORY_TOOL,
        _DESCRIPTION,
        _SCHEMA,
        annotations=ToolAnnotations(read_only_hint=True),
    )(log_handler_failures(GET_CATEGORY_TOOL, read_category))
