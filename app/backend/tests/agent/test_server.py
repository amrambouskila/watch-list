"""The in-process MCP server that carries the three library tools."""

from __future__ import annotations

import httpx
import pytest
from mock_responder import MockResponder
from recording_reader import RecordingReader

from library_choice import a_category, another_category
from tv_watchlist.agent import server
from tv_watchlist.agent.constants import (
    FETCH_URL_TOOL,
    GET_CATEGORY_TOOL,
    LIBRARY_SERVER_NAME,
    LIBRARY_SERVER_VERSION,
    PROPOSE_TOOL,
)
from tv_watchlist.agent.fetcher import Fetcher
from tv_watchlist.agent.read_log import ReadLog
from tv_watchlist.agent.server import build_library_server
from tv_watchlist.agent.tools.propose import ProposalRecorder
from tv_watchlist.constants import FIRST_DATA_ROW, WATCHED
from tv_watchlist.models.proposal import Proposal
from tv_watchlist.services.catalog import Catalog

EDITED = a_category()
OTHER = another_category()
EDIT_SUMMARY = "mark the opening episode watched"


def _an_edit_of(category_id: str) -> dict[str, object]:
    """A one-cell edit the model might propose, aimed at whichever category is under test."""
    return {
        "kind": "edit",
        "category_id": category_id,
        "changes": [{"kind": "revise", "row": FIRST_DATA_ROW, "cells": {EDITED.watch_key: WATCHED}}],
    }


async def ignore(proposal: Proposal) -> None:
    """A recorder that throws the proposal away; the server does not care what it does."""


def a_fetcher() -> Fetcher:
    return Fetcher(RecordingReader(), transport=MockResponder(httpx.Response(200)).transport)


def capture_server(
    catalog: Catalog, record: ProposalRecorder, read_log: ReadLog, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    """What `build_library_server` hands the SDK: its name, its version and the tools it built."""
    captured: dict[str, object] = {}

    def capture(name: str, version: str = "", tools: list[object] | None = None) -> dict[str, object]:
        captured.update(name=name, version=version, tools=tools or [])
        return captured

    monkeypatch.setattr(server, "create_sdk_mcp_server", capture)
    build_library_server(catalog, a_fetcher(), record, read_log)
    return captured


def test_the_server_is_an_in_process_sdk_server_named_library(catalog: Catalog) -> None:
    config = build_library_server(catalog, a_fetcher(), ignore, ReadLog())

    assert config["type"] == "sdk"
    assert config["name"] == LIBRARY_SERVER_NAME


def test_it_carries_exactly_the_three_library_tools(catalog: Catalog, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = capture_server(catalog, ignore, ReadLog(), monkeypatch)

    assert captured["name"] == LIBRARY_SERVER_NAME
    assert captured["version"] == LIBRARY_SERVER_VERSION
    assert [built.name for built in captured["tools"]] == [GET_CATEGORY_TOOL, FETCH_URL_TOOL, PROPOSE_TOOL]


async def test_the_read_and_propose_tools_share_the_one_read_log_they_were_built_with(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[Proposal] = []

    async def record(proposal: Proposal) -> None:
        recorded.append(proposal)

    tools = {built.name: built for built in capture_server(catalog, record, ReadLog(), monkeypatch)["tools"]}
    detail = await catalog.detail(EDITED.category_id)

    await tools[GET_CATEGORY_TOOL].handler({"category_id": EDITED.category_id})
    result = await tools[PROPOSE_TOOL].handler({"summary": EDIT_SUMMARY, "body": _an_edit_of(EDITED.category_id)})

    assert result["is_error"] is False
    assert recorded[0].body.read_mtime == detail.mtime


async def test_reading_a_second_category_does_not_restamp_the_one_the_edit_names(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[Proposal] = []

    async def record(proposal: Proposal) -> None:
        recorded.append(proposal)

    tools = {built.name: built for built in capture_server(catalog, record, ReadLog(), monkeypatch)["tools"]}
    edited = await catalog.detail(EDITED.category_id)
    other = await catalog.detail(OTHER.category_id)

    await tools[GET_CATEGORY_TOOL].handler({"category_id": EDITED.category_id})
    await tools[GET_CATEGORY_TOOL].handler({"category_id": OTHER.category_id})
    await tools[PROPOSE_TOOL].handler({"summary": EDIT_SUMMARY, "body": _an_edit_of(EDITED.category_id)})

    assert edited.mtime != other.mtime
    assert recorded[0].body.read_mtime == edited.mtime
