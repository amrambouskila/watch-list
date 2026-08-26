"""The read-only tool that hands Claude one category's columns and rows."""

from __future__ import annotations

import json
import logging

import pytest
from claude_agent_sdk import SdkMcpTool

from library_choice import a_category
from tv_watchlist.agent.constants import GET_CATEGORY_TOOL
from tv_watchlist.agent.read_log import ReadLog
from tv_watchlist.agent.tools.get_category import build_get_category_tool
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.services.catalog import Catalog

UNKNOWN_CATEGORY = "no-such-category"


def a_category_id() -> str:
    """The category this tool is exercised against, chosen by shape rather than by name."""
    return a_category().category_id


async def test_the_tool_is_named_and_annotated_read_only(catalog: Catalog) -> None:
    built = build_get_category_tool(catalog, ReadLog())

    assert isinstance(built, SdkMcpTool)
    assert built.name == GET_CATEGORY_TOOL
    assert built.annotations is not None
    assert built.annotations.read_only_hint is True


async def test_it_returns_the_category_columns_and_rows_as_json_text(catalog: Catalog) -> None:
    category_id = a_category_id()
    detail = await catalog.detail(category_id)

    result = await build_get_category_tool(catalog, ReadLog()).handler({"category_id": category_id})

    assert result["is_error"] is False
    payload = json.loads(result["content"][0]["text"])
    assert [column["key"] for column in payload["columns"]] == [column.key for column in detail.columns]
    assert len(payload["rows"]) == len(detail.rows)


async def test_a_read_records_the_workbook_mtime_the_rows_came_from(catalog: Catalog) -> None:
    category_id = a_category_id()
    detail = await catalog.detail(category_id)
    read_log = ReadLog()

    await build_get_category_tool(catalog, read_log).handler({"category_id": category_id})

    assert read_log.mtime_of(category_id) == detail.mtime


async def test_a_read_that_failed_stamps_nothing_because_no_rows_were_resolved(catalog: Catalog) -> None:
    read_log = ReadLog()

    await build_get_category_tool(catalog, read_log).handler({"category_id": UNKNOWN_CATEGORY})

    assert read_log.mtime_of(UNKNOWN_CATEGORY) is None


async def test_an_unknown_category_comes_back_as_a_tool_error_the_model_can_read(catalog: Catalog) -> None:
    result = await build_get_category_tool(catalog, ReadLog()).handler({"category_id": UNKNOWN_CATEGORY})

    assert result["is_error"] is True
    assert UNKNOWN_CATEGORY in result["content"][0]["text"]


async def test_an_unexpected_failure_is_logged_here_because_the_sdk_would_swallow_it(
    catalog: Catalog, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def explode(wanted_id: str) -> CategoryDetail:
        raise RuntimeError("openpyxl fell over")

    built = build_get_category_tool(catalog, ReadLog())
    monkeypatch.setattr(catalog, "detail", explode)

    with caplog.at_level(logging.ERROR):
        result = await built.handler({"category_id": "anything"})

    assert result["is_error"] is True
    assert "openpyxl fell over" in caplog.text
