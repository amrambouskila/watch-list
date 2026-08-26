"""The cheap path first, the browser only when the cheap path is visibly blocked."""

from __future__ import annotations

import httpx
import pytest
from mock_responder import MockResponder
from recording_reader import RecordingReader

from tv_watchlist.agent.constants import MAX_FETCH_CHARS, MIN_RENDERED_CHARS
from tv_watchlist.agent.errors import BlockedUrlError, FetchFailedError
from tv_watchlist.agent.fetcher import Fetcher

PUBLIC_URL = "https://93.184.216.34/list"
LONG_ENOUGH = "Dunkirk. " * MIN_RENDERED_CHARS


async def test_a_readable_page_comes_back_from_httpx_without_starting_the_browser() -> None:
    reader = RecordingReader(LONG_ENOUGH)
    fetcher = Fetcher(reader, transport=MockResponder(httpx.Response(200, html=f"<p>{LONG_ENOUGH}</p>")).transport)

    result = await fetcher.fetch(PUBLIC_URL)

    assert result.via == "httpx"
    assert result.truncated is False
    assert "Dunkirk" in result.text
    assert reader.urls == []


@pytest.mark.parametrize("status", [401, 403, 429, 451])
async def test_a_blocking_status_escalates_to_the_browser(status: int) -> None:
    reader = RecordingReader(LONG_ENOUGH)
    fetcher = Fetcher(reader, transport=MockResponder(httpx.Response(status, html="<p>nope</p>")).transport)

    result = await fetcher.fetch(PUBLIC_URL)

    assert result.via == "chromium"
    assert reader.urls == [PUBLIC_URL]


async def test_a_challenge_page_escalates_even_though_it_returned_200() -> None:
    reader = RecordingReader(LONG_ENOUGH)
    challenge = f"<title>Just a moment...</title><p>Checking your browser {LONG_ENOUGH}</p>"
    fetcher = Fetcher(reader, transport=MockResponder(httpx.Response(200, html=challenge)).transport)

    assert (await fetcher.fetch(PUBLIC_URL)).via == "chromium"


async def test_a_body_that_renders_almost_no_text_escalates() -> None:
    reader = RecordingReader(LONG_ENOUGH)
    fetcher = Fetcher(reader, transport=MockResponder(httpx.Response(200, html="<div id='root'></div>")).transport)

    assert (await fetcher.fetch(PUBLIC_URL)).via == "chromium"


async def test_a_transport_failure_escalates_rather_than_surfacing() -> None:
    reader = RecordingReader(LONG_ENOUGH)

    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    fetcher = Fetcher(reader, transport=httpx.MockTransport(explode))

    assert (await fetcher.fetch(PUBLIC_URL)).via == "chromium"


async def test_an_over_long_page_is_capped_and_flagged_rather_than_silently_cut() -> None:
    reader = RecordingReader(LONG_ENOUGH)
    body = "x" * (MAX_FETCH_CHARS * 2)
    fetcher = Fetcher(reader, transport=MockResponder(httpx.Response(200, html=f"<p>{body}</p>")).transport)

    result = await fetcher.fetch(PUBLIC_URL)

    assert result.truncated is True
    assert len(result.text) == MAX_FETCH_CHARS


async def test_an_over_long_rendered_page_is_capped_and_flagged_too() -> None:
    reader = RecordingReader("x" * (MAX_FETCH_CHARS * 2))
    fetcher = Fetcher(reader, transport=MockResponder(httpx.Response(403, html="<p>nope</p>")).transport)

    result = await fetcher.fetch(PUBLIC_URL)

    assert result.via == "chromium"
    assert result.truncated is True
    assert len(result.text) == MAX_FETCH_CHARS


async def test_a_redirect_is_followed_and_the_new_target_is_read() -> None:
    reader = RecordingReader(LONG_ENOUGH)
    responder = MockResponder(
        httpx.Response(302, headers={"location": "https://93.184.216.35/moved"}),
        httpx.Response(200, html=f"<p>{LONG_ENOUGH}</p>"),
    )
    fetcher = Fetcher(reader, transport=responder.transport)

    result = await fetcher.fetch(PUBLIC_URL)

    assert result.via == "httpx"
    assert responder.requested[-1] == "https://93.184.216.35/moved"


async def test_a_redirect_into_private_space_is_refused_mid_flight() -> None:
    reader = RecordingReader(LONG_ENOUGH)
    responder = MockResponder(httpx.Response(302, headers={"location": "http://169.254.169.254/latest"}))
    fetcher = Fetcher(reader, transport=responder.transport)

    with pytest.raises(BlockedUrlError):
        await fetcher.fetch(PUBLIC_URL)


async def test_a_url_that_fails_the_guard_never_reaches_the_transport() -> None:
    reader = RecordingReader(LONG_ENOUGH)
    responder = MockResponder(httpx.Response(200, html=f"<p>{LONG_ENOUGH}</p>"))
    fetcher = Fetcher(reader, transport=responder.transport)

    with pytest.raises(BlockedUrlError):
        await fetcher.fetch("file:///etc/passwd")

    assert responder.requested == []
    assert reader.urls == []


async def test_a_browser_that_renders_nothing_is_a_failure_not_an_empty_result() -> None:
    reader = RecordingReader("   ")
    fetcher = Fetcher(reader, transport=MockResponder(httpx.Response(403, html="<p>nope</p>")).transport)

    with pytest.raises(FetchFailedError):
        await fetcher.fetch(PUBLIC_URL)


async def test_closing_the_fetcher_tears_down_the_browser() -> None:
    reader = RecordingReader(LONG_ENOUGH)
    await Fetcher(reader).aclose()

    assert reader.closed is True
