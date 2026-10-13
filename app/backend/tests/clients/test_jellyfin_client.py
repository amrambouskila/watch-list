"""The Jellyfin client, driven entirely by hand-authored bodies. No test here opens a socket.

The fixtures under `tests/fixtures/jellyfin/` are shaped from Jellyfin 12.1's published OpenAPI document
rather than recorded from a running server - that directory's README says why, and which five things T49
still confirms live. What this file proves is the part that does not depend on those answers: the key
travels in one header and nowhere else, the configured host is the whole allowlist, a walk is bounded, an
unreachable server is data rather than a crash, and ticks become seconds exactly once.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Final

import httpx
import pytest
from pydantic import SecretStr

from lifespan_support import run_lifespan
from provider_fixtures import (
    A_CREDENTIAL_WITH_A_NEWLINE,
    A_JELLYFIN_BASE_URL,
    A_RECORDED_JELLYFIN_KEY,
    JELLYFIN,
    H11RejectingResponder,
    fixture_json,
    fixture_response,
    fixture_text_response,
    jellyfin_client_for,
)
from tv_watchlist.api.dependencies import get_catalog, get_jellyfin_client
from tv_watchlist.clients.errors import (
    OutboundUrlError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderNotFoundError,
    ProviderRefusedError,
    ProviderResponseTooLargeError,
    ProviderUnavailableError,
)
from tv_watchlist.clients.jellyfin_client import JellyfinClient, build_jellyfin_client, build_jellyfin_http
from tv_watchlist.clients.streamed_response import StreamedResponse
from tv_watchlist.config import Settings
from tv_watchlist.constants import (
    JELLYFIN_ITEM_FIELDS,
    JELLYFIN_MOVIE_TYPE,
    JELLYFIN_PAGE_SIZE,
    JELLYFIN_RELAYED_HEADERS,
    JELLYFIN_SERIES_TYPE,
    MAX_JELLYFIN_PAGES,
    MAX_PROVIDER_RESPONSE_BYTES,
    UNCONFIGURED_UPSTREAM_BASE_URL,
)
from tv_watchlist.main import create_app

LOGGER_NAME: Final[str] = "tv_watchlist.clients.jellyfin_client"
ONE_PIECE_SERIES_ID: Final[str] = "5c1d3f2a4b6e47d8a9f0c1b2d3e4f5a6"
AN_ITEM_ID: Final[str] = "0a1b2c3d4e5f6071829304a5b6c7d8e9"
A_RANGE: Final[str] = "bytes=1024-2047"
A_CHUNK: Final[int] = 1_000_000
A_CURSOR: Final[datetime] = datetime(2026, 9, 19, 21, 14, 7, tzinfo=UTC)


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records]


async def _oversized_body() -> AsyncIterator[bytes]:
    """One byte past the shared cap, and deliberately not JSON so a parse would fail differently."""
    sent = 0
    while sent < MAX_PROVIDER_RESPONSE_BYTES + 1:
        step = min(A_CHUNK, MAX_PROVIDER_RESPONSE_BYTES + 1 - sent)
        sent += step
        yield b"<" * step


def _a_page(*, items: int, total: int, start_index: int = 0) -> httpx.Response:
    """A page that claims `total` records while handing back only `items` of them."""
    body = fixture_json(JELLYFIN, "items_series_page1")
    one = body["Items"][0] if isinstance(body["Items"], list) else {}
    return httpx.Response(200, json={"Items": [one] * items, "TotalRecordCount": total, "StartIndex": start_index})


# Every public call, by name, so one test can sweep all of them rather than five tests drifting apart.
EVERY_CALL: Final[tuple[str, ...]] = ("items", "iter_items", "series_episodes", "stream", "refresh_library", "health")


def _canned_for(call: str) -> tuple[httpx.Response, ...]:
    """The answer each call needs to reach its success path, so one sweep can drive all of them."""
    if call == "items":
        return (fixture_response(JELLYFIN, "items_series_page1"),)
    if call == "iter_items":
        return (
            fixture_response(JELLYFIN, "items_series_page1"),
            fixture_response(JELLYFIN, "items_series_page2"),
            fixture_response(JELLYFIN, "items_empty"),
        )
    if call == "series_episodes":
        return (fixture_response(JELLYFIN, "shows_episodes_one_piece"),)
    if call == "refresh_library":
        return (httpx.Response(204),)
    if call == "health":
        return (fixture_text_response(JELLYFIN, "health"),)
    return (httpx.Response(206, content=b"0123456789"),)


async def _invoke(client: JellyfinClient, call: str) -> object:
    """Drive one public method by name, with arguments that are valid for it and nothing else."""
    if call == "items":
        return await client.items(include_item_types=[JELLYFIN_MOVIE_TYPE])
    if call == "iter_items":
        return [item async for item in client.iter_items(include_item_types=[JELLYFIN_MOVIE_TYPE])]
    if call == "series_episodes":
        return await client.series_episodes(ONE_PIECE_SERIES_ID)
    if call == "refresh_library":
        return await client.refresh_library()
    if call == "health":
        return await client.health()
    async with client.stream(AN_ITEM_ID, range_header=A_RANGE) as response:
        return [chunk async for chunk in response.body]


def _unreachable_client() -> tuple[JellyfinClient, list[httpx.Request]]:
    """A client whose transport refuses every connection, and the attempts it recorded."""
    attempts: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    client = JellyfinClient(
        A_JELLYFIN_BASE_URL,
        SecretStr(A_RECORDED_JELLYFIN_KEY),
        http=build_jellyfin_http(A_JELLYFIN_BASE_URL, transport=httpx.MockTransport(refuse)),
    )
    return client, attempts


# --- the credential ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("base_url", "api_key"),
    [(None, A_RECORDED_JELLYFIN_KEY), (A_JELLYFIN_BASE_URL, None), (None, None)],
)
async def test_an_unconfigured_client_refuses_before_building_a_request(
    base_url: str | None, api_key: str | None
) -> None:
    client, responder = jellyfin_client_for(
        fixture_response(JELLYFIN, "items_series_page1"), base_url=base_url, api_key=api_key
    )

    assert client.configured is False
    with pytest.raises(ProviderNotConfiguredError):
        await client.items(include_item_types=[JELLYFIN_SERIES_TYPE])

    assert responder.requested == []


async def test_an_unconfigured_client_refuses_every_other_call_the_same_way() -> None:
    client, responder = jellyfin_client_for(fixture_response(JELLYFIN, "items_series_page1"), api_key=None)

    with pytest.raises(ProviderNotConfiguredError):
        await client.series_episodes(ONE_PIECE_SERIES_ID)
    with pytest.raises(ProviderNotConfiguredError):
        await client.refresh_library()
    with pytest.raises(ProviderNotConfiguredError):
        async with client.stream(AN_ITEM_ID, range_header=None):
            pass
    with pytest.raises(ProviderNotConfiguredError):
        _ = [item async for item in client.iter_items(include_item_types=[JELLYFIN_SERIES_TYPE])]

    assert responder.requested == []


@pytest.mark.parametrize(
    ("base_url", "api_key"),
    [(None, A_RECORDED_JELLYFIN_KEY), (A_JELLYFIN_BASE_URL, None), (None, None)],
)
@pytest.mark.parametrize("call", ["items", "iter_items", "series_episodes", "stream", "refresh_library"])
async def test_every_unconfigured_refusal_carries_the_same_sentence(
    base_url: str | None, api_key: str | None, call: str
) -> None:
    """One message, whichever value is missing and whichever call asked - so the wording leaks nothing and
    no call site can check the two in a different order from another."""
    client, _ = jellyfin_client_for(base_url=base_url, api_key=api_key)

    with pytest.raises(ProviderNotConfiguredError) as raised:
        await _invoke(client, call)

    assert str(raised.value) == "TV_JELLYFIN_BASE_URL or TV_JELLYFIN_API_KEY is unset, so Jellyfin is disabled"


async def test_an_unconfigured_client_reports_unhealthy_rather_than_raising() -> None:
    client, responder = jellyfin_client_for(fixture_text_response(JELLYFIN, "health"), base_url=None)

    assert await client.health() is False
    assert responder.requested == []


async def test_a_configured_client_says_so() -> None:
    client, _ = jellyfin_client_for(fixture_response(JELLYFIN, "items_series_page1"))

    assert client.configured is True


async def test_the_key_travels_only_in_the_media_browser_header() -> None:
    client, responder = jellyfin_client_for(fixture_response(JELLYFIN, "items_movies_page1"))

    await client.items(include_item_types=[JELLYFIN_MOVIE_TYPE])

    request = responder.requests[0]
    assert request.headers["Authorization"] == f'MediaBrowser Token="{A_RECORDED_JELLYFIN_KEY}"'
    assert A_RECORDED_JELLYFIN_KEY not in str(request.url)
    assert "api_key" not in str(request.url).lower()


async def test_the_key_never_reaches_a_stream_url_either() -> None:
    """`/Videos/{id}/stream` would accept an `api_key` query parameter. This client never uses one."""
    client, responder = jellyfin_client_for(httpx.Response(200, content=b"\x00\x01"))

    async with client.stream(AN_ITEM_ID, range_header=None):
        pass

    request = responder.requests[0]
    assert request.headers["Authorization"] == f'MediaBrowser Token="{A_RECORDED_JELLYFIN_KEY}"'
    assert A_RECORDED_JELLYFIN_KEY not in str(request.url)


async def test_the_key_never_reaches_the_call_log(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = jellyfin_client_for(fixture_response(JELLYFIN, "items_movies_page1"))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await client.items(include_item_types=[JELLYFIN_MOVIE_TYPE])

    messages = _messages(caplog)
    assert messages, "the call should have logged a line"
    assert all(A_RECORDED_JELLYFIN_KEY not in message and "Authorization" not in message for message in messages)


async def test_the_call_log_carries_the_fields_an_operator_reads_and_nothing_else(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = jellyfin_client_for(fixture_response(JELLYFIN, "items_movies_page1"))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await client.items(include_item_types=[JELLYFIN_MOVIE_TYPE])

    line = next(message for message in _messages(caplog) if message.startswith("provider_call"))
    assert "host=jellyfin" in line
    assert "path=/Items" in line
    assert "status=200" in line
    assert "outcome=fresh" in line


A_KEY_WITH_A_NEWLINE: Final[str] = A_CREDENTIAL_WITH_A_NEWLINE


def _h11_rejecting_client(key: str) -> tuple[JellyfinClient, H11RejectingResponder]:
    """A client over the shared responder that fails the way h11 really does - one reproduction, three
    clients (`tests/provider_fixtures.py` says why `httpx.MockTransport` alone cannot show this)."""
    responder = H11RejectingResponder(httpx.Response(200, json={}))
    return jellyfin_client_for(api_key=key, responder=responder)[0], responder


@pytest.mark.parametrize("call", ["items", "iter_items", "series_episodes", "refresh_library", "stream"])
async def test_a_key_carrying_a_newline_never_reaches_the_raised_message(
    caplog: pytest.LogCaptureFixture, call: str
) -> None:
    """h11 quotes the WHOLE header value into its error, so interpolating that error would leak the key."""
    client, _ = _h11_rejecting_client(A_KEY_WITH_A_NEWLINE)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME), pytest.raises(ProviderUnavailableError) as raised:
        await _invoke(client, call)

    assert "cret-newline-credential" not in str(raised.value)
    assert A_KEY_WITH_A_NEWLINE not in str(raised.value)
    assert all("cret-newline-credential" not in message for message in _messages(caplog))
    # And the chain is kept, so a traceback still names what actually went wrong - while asserting the
    # CAUSE does carry the key is what proves this reproduces the real leak rather than a silent transport.
    assert isinstance(raised.value.__cause__, httpx.HTTPError)
    assert "cret-newline-credential" in str(raised.value.__cause__)


async def test_a_key_carrying_a_newline_never_reaches_a_health_probes_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`health()` swallows the failure, so it is the one path where only the log could leak it."""
    client, _ = _h11_rejecting_client(A_KEY_WITH_A_NEWLINE)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        assert await client.health() is False

    assert all("cret-newline-credential" not in message for message in _messages(caplog))


async def test_a_key_appears_in_the_one_authorization_header_and_in_no_other() -> None:
    client, responder = _h11_rejecting_client(A_KEY_WITH_A_NEWLINE)

    with pytest.raises(ProviderUnavailableError):
        await client.items(include_item_types=[JELLYFIN_MOVIE_TYPE])

    request = responder.requests[0]
    others = {name: value for name, value in request.headers.items() if name.lower() != "authorization"}
    assert all("cret-newline-credential" not in value for value in others.values())
    assert "cret-newline-credential" not in str(request.url)


@pytest.mark.parametrize("call", EVERY_CALL)
async def test_no_call_puts_the_key_in_a_log_record_or_an_exception(
    caplog: pytest.LogCaptureFixture, call: str
) -> None:
    """One sweep over every public method, so a method added later cannot quietly skip this check."""
    client, _ = jellyfin_client_for(httpx.Response(500, json={"error": "boom"}))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        try:
            await _invoke(client, call)
        except ProviderError as error:
            assert A_RECORDED_JELLYFIN_KEY not in str(error)

    assert all(A_RECORDED_JELLYFIN_KEY not in message for message in _messages(caplog))
    assert all("Authorization" not in message for message in _messages(caplog))


async def test_the_key_never_reaches_an_error_message() -> None:
    client, _ = jellyfin_client_for(httpx.Response(401, json={"error": "unauthorized"}))

    with pytest.raises(ProviderRefusedError) as raised:
        await client.items(include_item_types=[JELLYFIN_MOVIE_TYPE])

    assert A_RECORDED_JELLYFIN_KEY not in str(raised.value)


# --- the configured host is the whole allowlist ------------------------------------------------------------


@pytest.mark.parametrize("base_url", ["http://localhost:8096", "http://jellyfin:8096", "http://192.168.1.20:8096"])
async def test_a_private_or_loopback_base_is_accepted_because_that_is_where_jellyfin_lives(base_url: str) -> None:
    """`agent/url_guard.assert_public_http_url` rejects all three by design; this upstream is the carve-out."""
    client, responder = jellyfin_client_for(fixture_response(JELLYFIN, "items_movies_page1"), base_url=base_url)

    await client.items(include_item_types=[JELLYFIN_MOVIE_TYPE])

    assert responder.requested[0].startswith(f"{base_url}/Items")


@pytest.mark.parametrize("base_url", ["ftp://jellyfin:8096", "file:///media", "jellyfin:8096", "not a url at all"])
def test_a_base_url_that_is_not_http_is_refused_where_the_pool_is_pinned_to_it(base_url: str) -> None:
    """Refused at construction, not at the first call: a malformed base is a configuration error the owner
    should meet at once, where an ABSENT one is simply the disabled feature."""
    with pytest.raises(OutboundUrlError):
        build_jellyfin_http(base_url)


def test_a_base_url_carrying_credentials_is_refused_the_same_way() -> None:
    with pytest.raises(OutboundUrlError):
        build_jellyfin_http("http://user:pass@jellyfin:8096")


async def test_the_pool_an_unconfigured_client_holds_can_still_reach_nothing() -> None:
    """Belt and braces: `configured` refuses first, and the pool it holds is pinned to a dead loopback port."""
    answered: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        answered.append(request)
        return httpx.Response(200)

    async with build_jellyfin_http(UNCONFIGURED_UPSTREAM_BASE_URL, transport=httpx.MockTransport(answer)) as http:
        with pytest.raises(OutboundUrlError):
            await http.get("http://evil/Items")

    assert answered == []


async def test_a_redirect_is_reported_rather_than_followed() -> None:
    """`follow_redirects=False`: a hop would have to be re-checked against the base, so it stays a status."""
    client, responder = jellyfin_client_for(httpx.Response(302, headers={"location": "http://evil/Items"}))

    with pytest.raises(ProviderUnavailableError):
        await client.items(include_item_types=[JELLYFIN_MOVIE_TYPE])

    assert len(responder.requested) == 1


# --- one page ---------------------------------------------------------------------------------------------


async def test_items_asks_for_the_fields_the_sync_stores_and_nothing_else() -> None:
    client, responder = jellyfin_client_for(fixture_response(JELLYFIN, "items_series_page1"))

    await client.items(include_item_types=[JELLYFIN_SERIES_TYPE])

    url = httpx.URL(responder.requested[0])
    assert url.path == "/Items"
    # The CLOSED set, not merely these six being present: a parameter nobody meant to send - a `userId`,
    # an `api_key`, a `sortBy` that quietly reorders a scan - is caught by the equality, never by a
    # presence check that would pass whatever else went along beside it.
    assert set(url.params) == {"recursive", "includeItemTypes", "hasTmdbId", "fields", "startIndex", "limit"}
    assert url.params["fields"] == JELLYFIN_ITEM_FIELDS
    assert url.params["recursive"] == "true"
    assert url.params["includeItemTypes"] == JELLYFIN_SERIES_TYPE
    assert url.params["hasTmdbId"] == "true"
    assert url.params["limit"] == str(JELLYFIN_PAGE_SIZE)
    assert url.params["startIndex"] == "0"


async def test_items_joins_several_types_into_one_comma_delimited_value() -> None:
    client, responder = jellyfin_client_for(fixture_response(JELLYFIN, "items_series_page1"))

    await client.items(include_item_types=[JELLYFIN_MOVIE_TYPE, JELLYFIN_SERIES_TYPE])

    types = httpx.URL(responder.requested[0]).params["includeItemTypes"]
    assert types == f"{JELLYFIN_MOVIE_TYPE},{JELLYFIN_SERIES_TYPE}"


async def test_items_sends_a_min_date_last_saved_cursor_when_it_is_given_one() -> None:
    client, responder = jellyfin_client_for(fixture_response(JELLYFIN, "items_series_page1"))

    await client.items(include_item_types=[JELLYFIN_SERIES_TYPE], min_date_last_saved=A_CURSOR)

    assert httpx.URL(responder.requested[0]).params["minDateLastSaved"] == "2026-09-19T21:14:07+00:00"


async def test_items_omits_the_cursor_and_the_tmdb_filter_when_they_are_not_wanted() -> None:
    client, responder = jellyfin_client_for(fixture_response(JELLYFIN, "items_series_page1"))

    await client.items(include_item_types=[JELLYFIN_SERIES_TYPE], has_tmdb_id=None)

    params = httpx.URL(responder.requested[0]).params
    assert "minDateLastSaved" not in params
    assert "hasTmdbId" not in params


async def test_items_returns_the_page_the_server_sent() -> None:
    client, _ = jellyfin_client_for(fixture_response(JELLYFIN, "items_series_page1"))

    page = await client.items(include_item_types=[JELLYFIN_SERIES_TYPE])

    assert (len(page.items), page.total_record_count) == (2, 3)
    assert page.items[0].name == "One Piece"


# --- the paged walk ---------------------------------------------------------------------------------------


async def test_iter_items_walks_start_index_until_the_total_is_covered() -> None:
    client, responder = jellyfin_client_for(
        fixture_response(JELLYFIN, "items_series_page1"),
        fixture_response(JELLYFIN, "items_series_page2"),
        fixture_response(JELLYFIN, "items_empty"),
    )

    names = [item.name async for item in client.iter_items(include_item_types=[JELLYFIN_SERIES_TYPE], limit=2)]

    assert names == ["One Piece", "Attack on Titan", "Naruto"]
    assert [httpx.URL(url).params["startIndex"] for url in responder.requested] == ["0", "2"]


async def test_iter_items_stops_on_an_empty_page_even_when_the_total_says_otherwise() -> None:
    client, responder = jellyfin_client_for(_a_page(items=0, total=999))

    collected = [item async for item in client.iter_items(include_item_types=[JELLYFIN_SERIES_TYPE])]

    assert (collected, len(responder.requested)) == ([], 1)


async def test_iter_items_stops_at_the_page_cap_rather_than_walking_for_ever() -> None:
    """A server that always reports more than it hands back is the shape that loops for ever. A truncated
    index is worse than a failed one - it reads as 'not in your library' - so the cap raises."""
    client, responder = jellyfin_client_for(_a_page(items=1, total=1_000_000))

    with pytest.raises(ProviderUnavailableError):
        _ = [item async for item in client.iter_items(include_item_types=[JELLYFIN_SERIES_TYPE], limit=1)]

    assert len(responder.requested) == MAX_JELLYFIN_PAGES


async def test_the_page_cap_overflow_is_logged_as_a_failure_too(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = jellyfin_client_for(_a_page(items=1, total=1_000_000))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME), pytest.raises(ProviderUnavailableError):
        _ = [item async for item in client.iter_items(include_item_types=[JELLYFIN_SERIES_TYPE], limit=1)]

    assert any("outcome=failed" in message for message in _messages(caplog))


# --- the episode join's source -----------------------------------------------------------------------------


async def test_series_episodes_asks_the_shows_endpoint_for_one_series() -> None:
    client, responder = jellyfin_client_for(fixture_response(JELLYFIN, "shows_episodes_one_piece"))

    page = await client.series_episodes(ONE_PIECE_SERIES_ID)

    assert httpx.URL(responder.requested[0]).path == f"/Shows/{ONE_PIECE_SERIES_ID}/Episodes"
    assert len(page.items) == 3
    assert page.items[2].index_number_end == 4


async def test_series_episodes_percent_encodes_an_id_that_would_otherwise_change_the_path() -> None:
    """The id comes from a stored row rather than from a person, and it is still never interpolated."""
    client, responder = jellyfin_client_for(fixture_response(JELLYFIN, "shows_episodes_one_piece"))

    await client.series_episodes("abc/def")

    # The RAW path, not `.path`: httpx decodes the latter, so only the wire form shows the separator that
    # the encoding stopped from becoming one.
    assert httpx.URL(responder.requested[0]).raw_path.startswith(b"/Shows/abc%2Fdef/Episodes")


async def test_series_episodes_refuses_an_id_that_walks_out_of_the_base_even_once_encoded() -> None:
    """Encoding alone would not be enough: the guard splits AFTER unquoting, so `..%2F` is still a `..`."""
    client, responder = jellyfin_client_for(fixture_response(JELLYFIN, "shows_episodes_one_piece"))

    with pytest.raises(OutboundUrlError):
        await client.series_episodes("abc/../../Users")

    assert responder.requested == []


async def test_series_episodes_reports_a_series_the_server_does_not_have() -> None:
    client, _ = jellyfin_client_for(httpx.Response(404))

    with pytest.raises(ProviderNotFoundError):
        await client.series_episodes(ONE_PIECE_SERIES_ID)


# --- health ------------------------------------------------------------------------------------------------


async def test_health_is_true_when_the_server_answers() -> None:
    client, responder = jellyfin_client_for(fixture_text_response(JELLYFIN, "health"))

    assert await client.health() is True
    assert httpx.URL(responder.requested[0]).path == "/health"


@pytest.mark.parametrize("status", [401, 404, 500, 503])
async def test_health_answers_false_rather_than_raising_on_any_refusal(status: int) -> None:
    client, _ = jellyfin_client_for(httpx.Response(status))

    assert await client.health() is False


async def test_an_oversized_health_body_is_refused_rather_than_buffered() -> None:
    """A 200 with a megabyte of HTML is not a healthy Jellyfin, and it must not be pulled into memory."""
    client, _ = jellyfin_client_for(httpx.Response(200, content=_oversized_body()))

    assert await client.health() is False


async def test_a_capped_health_body_is_logged_with_the_bytes_it_read(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = jellyfin_client_for(fixture_text_response(JELLYFIN, "health"))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await client.health()

    line = next(message for message in _messages(caplog) if message.startswith("provider_call"))
    assert "method=GET" in line
    assert f"bytes={len(b'Healthy')}" in line


async def test_health_answers_false_rather_than_raising_when_jellyfin_is_unreachable() -> None:
    """A stopped, scanning or absent Jellyfin is 'availability unknown', surfaced as data, never a 500."""
    client, attempts = _unreachable_client()

    assert await client.health() is False
    assert len(attempts) == 1


# --- the library scan trigger --------------------------------------------------------------------------------


async def test_refresh_library_posts_to_the_constant_path_with_no_body() -> None:
    client, responder = jellyfin_client_for(httpx.Response(204))

    assert await client.refresh_library() is None

    request = responder.requests[0]
    assert (request.method, httpx.URL(responder.requested[0]).path) == ("POST", "/Library/Refresh")
    assert request.read() == b""


@pytest.mark.parametrize("status", [200, 403, 500])
async def test_refresh_library_refuses_anything_but_the_documented_204(status: int) -> None:
    client, _ = jellyfin_client_for(httpx.Response(status))

    with pytest.raises((ProviderRefusedError, ProviderUnavailableError)):
        await client.refresh_library()


async def test_the_refresh_is_logged_as_the_post_it_actually_is(caplog: pytest.LogCaptureFixture) -> None:
    """A log that calls every call a GET is a log an operator cannot use to find a write."""
    client, _ = jellyfin_client_for(httpx.Response(204))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await client.refresh_library()

    line = next(message for message in _messages(caplog) if message.startswith("provider_call"))
    assert "method=POST" in line
    assert "status=204" in line


async def test_a_refused_refresh_is_logged_as_a_post_too(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = jellyfin_client_for(httpx.Response(403))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME), pytest.raises(ProviderRefusedError):
        await client.refresh_library()

    line = next(message for message in _messages(caplog) if message.startswith("provider_call"))
    assert "method=POST" in line
    assert "status=403" in line


async def test_an_oversized_refresh_body_is_refused_rather_than_buffered() -> None:
    """204 is the documented answer; a server answering a megabyte still gets read through the cap."""
    client, _ = jellyfin_client_for(httpx.Response(204, content=_oversized_body()))

    with pytest.raises(ProviderResponseTooLargeError):
        await client.refresh_library()


@pytest.mark.parametrize(
    ("call", "status"),
    [
        ("items", 401),
        ("items", 404),
        ("series_episodes", 404),
        ("stream", 404),
        ("refresh_library", 403),
    ],
)
async def test_a_refusal_logs_the_status_jellyfin_actually_answered(
    caplog: pytest.LogCaptureFixture, call: str, status: int
) -> None:
    """`status=none` means "nothing answered". A server that DID answer must not be logged as an outage."""
    client, _ = jellyfin_client_for(httpx.Response(status))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME), pytest.raises(ProviderError):
        await _invoke(client, call)

    line = next(message for message in _messages(caplog) if "outcome=failed" in message)
    assert f"status={status}" in line


async def test_refresh_library_reports_an_unreachable_server_like_every_other_call() -> None:
    client, attempts = _unreachable_client()

    with pytest.raises(ProviderUnavailableError):
        await client.refresh_library()

    assert len(attempts) == 1


# --- the stream the proxy relays -------------------------------------------------------------------------------


async def test_stream_forwards_a_range_header_and_yields_without_buffering() -> None:
    client, responder = jellyfin_client_for(httpx.Response(206, content=b"0123456789"))

    async with client.stream(AN_ITEM_ID, range_header=A_RANGE) as response:
        chunks = [chunk async for chunk in response.body]
        status = response.status_code

    assert responder.requests[0].headers["Range"] == A_RANGE
    assert b"".join(chunks) == b"0123456789"
    assert status == 206


async def test_stream_yields_only_the_three_headers_a_relay_may_pass_on() -> None:
    """An upstream `Set-Cookie` or `Server` must never reach the browser through the proxy (B17)."""
    upstream = httpx.Response(
        206,
        content=b"x",
        headers={
            "Content-Type": "video/x-matroska",
            "Content-Range": "bytes 0-0/10",
            "Set-Cookie": "session=abc; Path=/",
            "Server": "Kestrel",
            "WWW-Authenticate": "MediaBrowser",
            "X-Application": "Jellyfin",
        },
    )
    client, _ = jellyfin_client_for(upstream)

    async with client.stream(AN_ITEM_ID, range_header=A_RANGE) as response:
        seen = dict(response.headers)

    assert set(seen) <= set(JELLYFIN_RELAYED_HEADERS)
    assert seen["Content-Type"] == "video/x-matroska"
    assert seen["Content-Range"] == "bytes 0-0/10"


async def test_stream_hands_back_no_httpx_response_and_no_upstream_header_bag() -> None:
    """The narrow object is the boundary; a raw response would carry every header there is."""
    client, _ = jellyfin_client_for(httpx.Response(200, content=b"x"))

    async with client.stream(AN_ITEM_ID, range_header=None) as response:
        assert isinstance(response, StreamedResponse)
        assert not isinstance(response, httpx.Response)
        assert not hasattr(response, "request")
        assert not hasattr(response, "cookies")


async def test_an_error_raised_while_the_caller_relays_is_not_reclassified_or_logged_twice(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The `try` must not span the yield: a relay-time fault is the caller's, not a provider failure."""
    client, _ = jellyfin_client_for(httpx.Response(200, content=b"0123456789"))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME), pytest.raises(RuntimeError, match="the caller broke"):
        async with client.stream(AN_ITEM_ID, range_header=None) as response:
            await anext(aiter(response.body))
            raise RuntimeError("the caller broke")

    assert not [message for message in _messages(caplog) if "outcome=failed" in message]


async def test_an_httpx_error_raised_while_relaying_is_not_turned_into_a_provider_failure() -> None:
    """The narrower `try` also means a mid-body `httpx` fault reaches the caller as what it is."""
    client, _ = jellyfin_client_for(httpx.Response(200, content=b"0123456789"))

    with pytest.raises(httpx.ReadError):
        async with client.stream(AN_ITEM_ID, range_header=None) as response:
            await anext(aiter(response.body))
            raise httpx.ReadError("the socket went away")


async def test_stream_sends_no_range_header_when_there_is_none_to_send() -> None:
    client, responder = jellyfin_client_for(httpx.Response(200, content=b"x"))

    async with client.stream(AN_ITEM_ID, range_header=None):
        pass

    assert "Range" not in responder.requests[0].headers


async def test_stream_asks_for_the_original_file_rather_than_a_transcode() -> None:
    client, responder = jellyfin_client_for(httpx.Response(200, content=b"x"))

    async with client.stream(AN_ITEM_ID, range_header=None):
        pass

    url = httpx.URL(responder.requested[0])
    assert url.path == f"/Videos/{AN_ITEM_ID}/stream"
    assert url.params["static"] == "true"


async def test_the_body_is_live_inside_the_block_and_finished_once_it_closes() -> None:
    """The narrow object holds a LIVE iterator, and the exit stack is what ends it: a body still readable
    after the block would mean a connection the pool never got back."""
    client, _ = jellyfin_client_for(httpx.Response(200, content=b"0123456789"))

    async with client.stream(AN_ITEM_ID, range_header=None) as response:
        body = response.body
        assert await anext(aiter(body)) == b"0123456789"

    with pytest.raises(StopAsyncIteration):
        await anext(aiter(body))


async def test_stream_reports_a_refusal_rather_than_handing_back_an_error_body() -> None:
    client, _ = jellyfin_client_for(httpx.Response(404))

    with pytest.raises(ProviderNotFoundError):
        async with client.stream(AN_ITEM_ID, range_header=None):
            pass


async def test_stream_reports_an_unreachable_server() -> None:
    client, attempts = _unreachable_client()

    with pytest.raises(ProviderUnavailableError):
        async with client.stream(AN_ITEM_ID, range_header=None):
            pass

    assert len(attempts) == 1


# --- the shared refusals -----------------------------------------------------------------------------------------


async def test_an_oversized_body_is_refused_rather_than_truncated() -> None:
    client, _ = jellyfin_client_for(httpx.Response(200, content=_oversized_body()))

    with pytest.raises(ProviderResponseTooLargeError):
        await client.items(include_item_types=[JELLYFIN_MOVIE_TYPE])


async def test_a_body_that_is_not_json_is_an_unusable_answer() -> None:
    client, _ = jellyfin_client_for(httpx.Response(200, content=b"<html>Jellyfin is starting</html>"))

    with pytest.raises(ProviderUnavailableError):
        await client.items(include_item_types=[JELLYFIN_MOVIE_TYPE])


async def test_a_shape_this_client_cannot_read_never_repeats_the_values_it_refused() -> None:
    """`ValidationError.errors()` embeds the input, and this message reaches a log and an operator's screen."""
    client, _ = jellyfin_client_for(httpx.Response(200, json={"Items": [{"Name": "nameless"}]}))

    with pytest.raises(ProviderUnavailableError) as raised:
        await client.items(include_item_types=[JELLYFIN_MOVIE_TYPE])

    assert "nameless" not in str(raised.value)


async def test_an_unreachable_server_is_one_attempt_and_one_failure(caplog: pytest.LogCaptureFixture) -> None:
    """No retry storm: an outage produces exactly one request and one `failed` line, never a loop."""
    client, attempts = _unreachable_client()

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME), pytest.raises(ProviderUnavailableError):
        await client.items(include_item_types=[JELLYFIN_MOVIE_TYPE])

    assert len(attempts) == 1
    assert any("outcome=failed" in message for message in _messages(caplog))


# --- the composition seam -----------------------------------------------------------------------------------------


def test_build_jellyfin_client_reads_both_values_off_settings() -> None:
    settings = Settings(
        _env_file=None,
        jellyfin_base_url=A_JELLYFIN_BASE_URL,
        jellyfin_api_key=SecretStr(A_RECORDED_JELLYFIN_KEY),
    )

    assert build_jellyfin_client(settings).configured is True


def test_build_jellyfin_client_is_disabled_rather_than_broken_with_nothing_configured() -> None:
    assert build_jellyfin_client(Settings(_env_file=None)).configured is False


@pytest.mark.parametrize(
    "overrides",
    [{"jellyfin_base_url": ""}, {"jellyfin_api_key": SecretStr("")}],
)
def test_settings_map_a_blank_jellyfin_line_to_an_unset_value(overrides: dict[str, object]) -> None:
    """R91 covers both configured upstreams: `TV_JELLYFIN_BASE_URL=` in a .env is the disabled feature, not
    a base URL of "" that the R80 shape check would refuse at boot, and a blank key never configures the
    client with an empty credential."""
    configured: dict[str, object] = {
        "jellyfin_base_url": A_JELLYFIN_BASE_URL,
        "jellyfin_api_key": SecretStr(A_RECORDED_JELLYFIN_KEY),
    }

    settings = Settings(_env_file=None, **(configured | overrides))

    assert build_jellyfin_client(settings).configured is False


async def test_a_client_closes_the_pool_it_holds() -> None:
    client, _ = jellyfin_client_for(fixture_response(JELLYFIN, "items_series_page1"))

    await client.aclose()

    with pytest.raises(RuntimeError):
        await client.items(include_item_types=[JELLYFIN_SERIES_TYPE])


async def test_the_lifespan_closes_the_pool_the_singleton_opened() -> None:
    """One pool to the media server, and it must not outlive the backend that opened it."""
    get_jellyfin_client.cache_clear()
    get_catalog.cache_clear()
    app = create_app()
    client = get_jellyfin_client()

    await run_lifespan(app)

    assert client.closed
    get_jellyfin_client.cache_clear()
    get_catalog.cache_clear()


async def test_a_process_that_never_reached_jellyfin_builds_no_client_to_close() -> None:
    """Asking for it at shutdown would pin a pool to the media server an app never touched.

    `currsize` is the whole observable: 0 before the lifespan and still 0 after, so the shutdown path did
    not call the singleton. The test above proves the other half - that a client which WAS built is closed.
    """
    get_jellyfin_client.cache_clear()
    get_catalog.cache_clear()
    app = create_app()
    assert get_jellyfin_client.cache_info().currsize == 0

    await run_lifespan(app)

    assert get_jellyfin_client.cache_info().currsize == 0
    get_catalog.cache_clear()


@pytest.mark.parametrize("call", EVERY_CALL)
async def test_no_call_hands_a_caller_anything_carrying_the_upstream_address(call: str) -> None:
    """A URL a caller could hold is one that can be logged, pasted or embedded - so nothing returned by
    any public method carries the base, the host or a path. A name check would only prove nobody spelled a
    method `..._url`; this drives every one of them and looks at what actually comes back."""
    client, _ = jellyfin_client_for(*_canned_for(call))

    returned = repr(await _invoke(client, call))

    assert A_JELLYFIN_BASE_URL not in returned
    assert "jellyfin:8096" not in returned
    assert "/Items" not in returned
    assert A_RECORDED_JELLYFIN_KEY not in returned


def test_no_public_member_is_even_named_after_a_url() -> None:
    """The cheap half of the check above, kept because it catches a `build_stream_url` before it is used."""
    public = {name for name in dir(JellyfinClient) if not name.startswith("_")}

    assert not {name for name in public if "url" in name.lower()}
