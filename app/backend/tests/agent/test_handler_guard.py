"""A handler failure must be logged here, because the SDK swallows it into an is_error result."""

from __future__ import annotations

import logging

import pytest

from tv_watchlist.agent.handler_guard import log_handler_failures
from tv_watchlist.agent.tool_result import ToolResult, text_result


async def test_a_raising_handler_is_logged_with_its_traceback_and_reported_as_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def explode(args: dict[str, object]) -> ToolResult:
        raise RuntimeError("workbook exploded")

    guarded = log_handler_failures("propose", explode)
    with caplog.at_level(logging.ERROR):
        result = await guarded({})

    assert result["is_error"] is True
    assert "workbook exploded" in caplog.text
    assert any(record.exc_info is not None for record in caplog.records)


async def test_a_succeeding_handler_passes_its_result_through_untouched() -> None:
    async def succeed(args: dict[str, object]) -> ToolResult:
        return text_result("fine")

    assert await log_handler_failures("propose", succeed)({}) == text_result("fine")
