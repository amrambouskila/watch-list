"""The composition root: one fetcher, one browser, one registry, torn down together."""

from __future__ import annotations

import httpx
from mock_responder import MockResponder
from recording_reader import RecordingReader
from stub_client import StubClient

from tv_watchlist.agent.fetcher import Fetcher
from tv_watchlist.agent.runtime import AgentRuntime
from tv_watchlist.services.catalog import Catalog


def a_runtime(catalog: Catalog, reader: RecordingReader) -> AgentRuntime:
    fetcher = Fetcher(reader, transport=MockResponder(httpx.Response(200)).transport)
    return AgentRuntime(catalog, fetcher, client_factory=StubClient)


async def test_sessions_it_opens_are_bound_to_the_catalog_it_was_given(catalog: Catalog) -> None:
    runtime = a_runtime(catalog, RecordingReader())

    session = await runtime.sessions.create()

    assert session.client.options.cwd == catalog.library_dir


async def test_closing_the_runtime_ends_its_sessions_and_the_browser(catalog: Catalog) -> None:
    reader = RecordingReader()
    runtime = a_runtime(catalog, reader)
    session = await runtime.sessions.create()

    await runtime.aclose()

    assert session.client.connected is False
    assert reader.closed is True
