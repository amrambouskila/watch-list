"""The tool that reads a URL for Claude and labels what it read as untrusted."""

from __future__ import annotations

import json

import httpx
from claude_agent_sdk import SdkMcpTool
from mock_responder import MockResponder
from recording_reader import RecordingReader

from tv_watchlist.agent.constants import (
    FETCH_URL_TOOL,
    MAX_FETCH_CHARS,
    MAX_TOOL_RESULT_CHARS,
    MIN_RENDERED_CHARS,
    UNTRUSTED_CONTENT_CLOSE,
    UNTRUSTED_CONTENT_OPEN,
)
from tv_watchlist.agent.fetcher import Fetcher
from tv_watchlist.agent.tools.fetch_url import build_fetch_url_tool

PUBLIC_URL = "https://93.184.216.34/list"
PAGE_TEXT = "Dunkirk. " * MIN_RENDERED_CHARS
CYRILLIC_TEXT = "Дюнкерк. " * MIN_RENDERED_CHARS
ESCAPE_HEAVY_TEXT = '"\n' * (MAX_FETCH_CHARS // 2)
SERIALISATION_OVERHEAD_ALLOWANCE = 200


def fetcher_returning(*responses: httpx.Response) -> Fetcher:
    return Fetcher(RecordingReader(PAGE_TEXT), transport=MockResponder(*responses).transport)


def fetcher_rendering(text: str) -> Fetcher:
    """A fetcher whose cheap path is blocked, so the browser's text is what reaches the tool."""
    return Fetcher(RecordingReader(text), transport=MockResponder(httpx.Response(403)).transport)


async def test_the_tool_is_named_for_the_spec() -> None:
    built = build_fetch_url_tool(fetcher_returning(httpx.Response(200)))

    assert isinstance(built, SdkMcpTool)
    assert built.name == FETCH_URL_TOOL


async def test_fetched_text_is_delimited_as_untrusted_and_reports_its_transport() -> None:
    built = build_fetch_url_tool(fetcher_returning(httpx.Response(200, html=f"<p>{PAGE_TEXT}</p>")))

    result = await built.handler({"url": PUBLIC_URL})

    assert result["is_error"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["via"] == "httpx"
    assert payload["truncated"] is False
    assert payload["text"].startswith(UNTRUSTED_CONTENT_OPEN)
    assert payload["text"].endswith(UNTRUSTED_CONTENT_CLOSE)
    assert "Dunkirk" in payload["text"]


async def test_a_url_the_guard_refuses_comes_back_as_a_tool_error() -> None:
    built = build_fetch_url_tool(fetcher_returning(httpx.Response(200)))

    result = await built.handler({"url": "http://169.254.169.254/latest/meta-data"})

    assert result["is_error"] is True
    assert "169.254.169.254" in result["content"][0]["text"]


async def test_a_page_neither_path_could_read_comes_back_as_a_tool_error() -> None:
    fetcher = Fetcher(RecordingReader(""), transport=MockResponder(httpx.Response(403)).transport)

    result = await build_fetch_url_tool(fetcher).handler({"url": PUBLIC_URL})

    assert result["is_error"] is True


async def test_a_page_that_would_serialise_past_the_transport_cap_comes_back_under_it() -> None:
    built = build_fetch_url_tool(fetcher_rendering(ESCAPE_HEAVY_TEXT))

    result = await built.handler({"url": PUBLIC_URL})

    serialised = result["content"][0]["text"]
    assert len(serialised) <= MAX_TOOL_RESULT_CHARS
    assert json.loads(serialised)["via"] == "chromium"


async def test_a_heavily_trimmed_page_still_closes_its_untrusted_content_delimiter() -> None:
    built = build_fetch_url_tool(fetcher_rendering(ESCAPE_HEAVY_TEXT))

    result = await built.handler({"url": PUBLIC_URL})

    payload = json.loads(result["content"][0]["text"])
    assert payload["text"].startswith(UNTRUSTED_CONTENT_OPEN)
    assert payload["text"].endswith(UNTRUSTED_CONTENT_CLOSE)


async def test_a_page_trimmed_to_fit_the_transport_is_reported_as_truncated() -> None:
    built = build_fetch_url_tool(fetcher_rendering(ESCAPE_HEAVY_TEXT))

    result = await built.handler({"url": PUBLIC_URL})

    assert json.loads(result["content"][0]["text"])["truncated"] is True


async def test_a_page_of_cyrillic_is_not_inflated_by_escaping_it_to_ascii() -> None:
    built = build_fetch_url_tool(fetcher_returning(httpx.Response(200, html=f"<p>{CYRILLIC_TEXT}</p>")))

    result = await built.handler({"url": PUBLIC_URL})

    serialised = result["content"][0]["text"]
    payload = json.loads(serialised)
    assert "Дюнкерк" in payload["text"]
    assert len(serialised) <= len(payload["text"]) + SERIALISATION_OVERHEAD_ALLOWANCE


async def test_a_page_that_fits_the_transport_is_handed_back_with_every_word_intact() -> None:
    built = build_fetch_url_tool(fetcher_returning(httpx.Response(200, html=f"<p>{PAGE_TEXT}</p>")))

    result = await built.handler({"url": PUBLIC_URL})

    payload = json.loads(result["content"][0]["text"])
    assert payload["text"].count("Dunkirk") == PAGE_TEXT.count("Dunkirk")
    assert payload["truncated"] is False
