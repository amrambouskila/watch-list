"""The shared provider transport: pinned base, no redirects, a hard size cap, and a credential-free log."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Final, get_args

import httpx
import pytest
from mock_responder import MockResponder

from tv_watchlist.clients.errors import (
    OutboundUrlError,
    ProviderNotFoundError,
    ProviderRefusedError,
    ProviderResponseTooLargeError,
    ProviderUnavailableError,
)
from tv_watchlist.clients.transport import (
    ACCEPT_JSON,
    CacheOutcome,
    Cursor,
    ProviderBody,
    build_provider_http,
    elapsed_ms_since,
    log_call,
    payload_digest,
    read_json,
    read_text,
    refusal_for,
    retry_after_seconds,
    scrubbed,
)
from tv_watchlist.constants import MAX_PROVIDER_RESPONSE_BYTES, PROVIDER_TIMEOUT_SECONDS, TMDB_API_BASE_URL

A_SMALL_CAP: Final[int] = 64
A_CHUNK: Final[int] = 1_000_000
# If the reader ever pulls this many chunks it is not capping at all, and the generator says so rather
# than streaming until the test times out.
A_RUNAWAY_CHUNK_COUNT: Final[int] = 64
LOGGER: Final[logging.Logger] = logging.getLogger("tv_watchlist.clients.test")


async def _fetch(response: httpx.Response, *, path: str = "/movie/603") -> httpx.Response:
    """The response, read through a provider client, the buffered way a small payload arrives."""
    async with build_provider_http(
        TMDB_API_BASE_URL, headers={}, transport=MockResponder(response).transport
    ) as client:
        return await client.get(path)


async def _oversized_body() -> AsyncIterator[bytes]:
    """One byte past the cap, and deliberately not JSON so a parse would fail differently."""
    sent = 0
    while sent < MAX_PROVIDER_RESPONSE_BYTES + 1:
        step = min(A_CHUNK, MAX_PROVIDER_RESPONSE_BYTES + 1 - sent)
        sent += step
        yield b"<" * step


async def _endless_body(produced: list[int]) -> AsyncIterator[bytes]:
    """Chunks on and on, recording each one the reader actually pulled."""
    for index in range(A_RUNAWAY_CHUNK_COUNT):
        produced.append(index)
        yield b"<" * A_CHUNK
    raise AssertionError("read_json kept pulling chunks long past the cap")


def test_the_accept_header_has_one_home_and_cannot_be_mutated() -> None:
    """Three modules used to carry their own copy; a mapping proxy is why a fourth cannot start one."""
    assert dict(ACCEPT_JSON) == {"Accept": "application/json"}
    # A mapping proxy, so the TypeError below is what stops a caller editing the shared header in place.
    with pytest.raises(TypeError):
        ACCEPT_JSON["Accept"] = "text/html"


async def test_read_text_returns_the_decoded_body_and_the_bytes_it_came_from() -> None:
    response = await _fetch(httpx.Response(200, content=b"Healthy"))

    text, raw = await read_text(response)

    assert (text, raw) == ("Healthy", b"Healthy")


async def test_read_text_refuses_a_body_past_the_cap_rather_than_truncating_it() -> None:
    """`/health` and `/Library/Refresh` answer text, and a buffered `.get()` would pull whatever arrives."""
    response = await _fetch(httpx.Response(200, content=_oversized_body()))

    with pytest.raises(ProviderResponseTooLargeError):
        await read_text(response)


async def test_read_text_honours_a_caller_supplied_cap() -> None:
    response = await _fetch(httpx.Response(200, content=b"x" * (A_SMALL_CAP + 1)))

    with pytest.raises(ProviderResponseTooLargeError):
        await read_text(response, limit=A_SMALL_CAP)


async def test_read_text_replaces_a_byte_that_is_not_utf8_rather_than_raising_a_second_time() -> None:
    """This reader is used on failure paths, so it must not become the failure it was called to report."""
    response = await _fetch(httpx.Response(200, content=b"He\xffalthy"))

    text, raw = await read_text(response)

    assert raw == b"He\xffalthy"
    assert "\ufffd" in text


async def test_read_text_stops_pulling_and_closes_a_stream_that_would_never_end() -> None:
    produced: list[int] = []
    responder = MockResponder(httpx.Response(200, content=_endless_body(produced)))
    async with build_provider_http(TMDB_API_BASE_URL, headers={}, transport=responder.transport) as client:
        async with client.stream("GET", "/movie/603") as response:
            with pytest.raises(ProviderResponseTooLargeError):
                await read_text(response)
            assert response.is_closed

    assert len(produced) == MAX_PROVIDER_RESPONSE_BYTES // A_CHUNK + 1


async def test_read_json_refuses_a_body_past_the_cap_without_parsing() -> None:
    """The body is `<` repeated: a parse would raise `ProviderUnavailableError`, so the cap is what fired."""
    response = await _fetch(httpx.Response(200, content=_oversized_body()))
    with pytest.raises(ProviderResponseTooLargeError):
        await read_json(response)


async def test_read_json_stops_pulling_and_closes_a_stream_that_would_never_end() -> None:
    """The buffered tests only prove a length check after the fact; this one proves the reader lets go."""
    produced: list[int] = []
    responder = MockResponder(httpx.Response(200, content=_endless_body(produced)))
    async with build_provider_http(TMDB_API_BASE_URL, headers={}, transport=responder.transport) as client:
        async with client.stream("GET", "/movie/603") as response:
            with pytest.raises(ProviderResponseTooLargeError):
                await read_json(response)
            assert response.is_closed

    # Eight chunks sit exactly on the cap, so the ninth is the one that trips it and the last one pulled.
    assert len(produced) == MAX_PROVIDER_RESPONSE_BYTES // A_CHUNK + 1


async def test_read_json_closes_a_stream_whose_body_turns_out_not_to_be_json() -> None:
    responder = MockResponder(httpx.Response(200, content=b"<html>nope</html>"))
    async with build_provider_http(TMDB_API_BASE_URL, headers={}, transport=responder.transport) as client:
        async with client.stream("GET", "/movie/603") as response:
            with pytest.raises(ProviderUnavailableError):
                await read_json(response)
            assert response.is_closed


async def test_read_json_refuses_one_byte_past_an_explicit_cap() -> None:
    body = b'{"pad":"' + b"x" * (A_SMALL_CAP - 9) + b'"}'
    assert len(body) == A_SMALL_CAP + 1
    response = await _fetch(httpx.Response(200, content=body))
    with pytest.raises(ProviderResponseTooLargeError):
        await read_json(response, limit=A_SMALL_CAP)


async def test_read_json_accepts_a_body_that_sits_exactly_on_the_cap() -> None:
    body = b'{"pad":"' + b"x" * (A_SMALL_CAP - 10) + b'"}'
    assert len(body) == A_SMALL_CAP
    response = await _fetch(httpx.Response(200, content=body))

    parsed, raw = await read_json(response, limit=A_SMALL_CAP)

    assert parsed == {"pad": "x" * (A_SMALL_CAP - 10)}
    assert raw == body


@pytest.mark.parametrize(
    "body",
    [b"<html><body>Service Unavailable</body></html>", b"", b"\xff\xfe not text at all"],
)
async def test_read_json_accepts_json_only(body: bytes) -> None:
    response = await _fetch(httpx.Response(200, content=body, headers={"content-type": "text/html"}))
    with pytest.raises(ProviderUnavailableError):
        await read_json(response)


async def test_read_json_returns_the_parsed_body_and_the_bytes_it_parsed() -> None:
    raw = b'{"id": 603, "name": "The Matrix"}'
    response = await _fetch(httpx.Response(200, content=raw))

    parsed, body = await read_json(response)

    assert parsed == {"id": 603, "name": "The Matrix"}
    assert body == raw


async def test_the_provider_http_never_follows_redirects_and_carries_the_timeout() -> None:
    responder = MockResponder(httpx.Response(302, headers={"location": "https://evil.example/"}))
    async with build_provider_http(TMDB_API_BASE_URL, headers={}, transport=responder.transport) as client:
        response = await client.get("/movie/603")

    assert response.status_code == 302
    assert client.follow_redirects is False
    assert client.timeout.read == pytest.approx(PROVIDER_TIMEOUT_SECONDS)
    assert responder.requested == ["https://api.themoviedb.org/3/movie/603"]


async def test_the_provider_http_refuses_an_absolute_url_off_its_own_base() -> None:
    responder = MockResponder(httpx.Response(200, json={}))
    async with build_provider_http(TMDB_API_BASE_URL, headers={}, transport=responder.transport) as client:
        with pytest.raises(OutboundUrlError):
            await client.get("https://api.themoviedb.org.evil/3/movie/603")

    assert responder.requested == []


@pytest.mark.parametrize(
    ("left", "right", "same"),
    [
        (b'{"a":1,"b":2}', b'{ "b": 2,\n  "a": 1 }', True),
        (b'{"a":1,"b":2}', b'{"a":2,"b":2}', False),
        (b'{"a":1}', b'{"a":2}', False),
        (b"[1, 2, 3]", b"[1,2,3]", True),
    ],
)
def test_a_digest_is_stable_across_key_order_and_whitespace(left: bytes, right: bytes, same: bool) -> None:
    assert (payload_digest(left) == payload_digest(right)) is same


def test_a_digest_is_a_hex_sha256() -> None:
    digest = payload_digest(b'{"a":1}')
    assert len(digest) == 64
    assert int(digest, 16) >= 0


@pytest.mark.parametrize("body", [b"<html>nope</html>", b"", b"\xff\xfe"])
def test_a_digest_of_bytes_that_are_not_json_stays_inside_the_provider_hierarchy(body: bytes) -> None:
    with pytest.raises(ProviderUnavailableError):
        payload_digest(body)


def test_the_cache_outcomes_are_the_five_the_call_log_reports() -> None:
    """`failed` is its own outcome: `throttled` means a wait, and a wait is not a failure."""
    assert set(get_args(CacheOutcome)) == {"fresh", "not-modified", "cached", "throttled", "failed"}


async def test_the_call_log_line_carries_the_outcome_and_no_authorization_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    authorization = "Bearer tmdb-read-access-value-that-must-never-be-logged"
    responder = MockResponder(httpx.Response(200, json={"id": 603}))
    with caplog.at_level(logging.INFO, logger=LOGGER.name):
        async with build_provider_http(
            TMDB_API_BASE_URL, headers={"Authorization": authorization}, transport=responder.transport
        ) as client:
            response = await client.get("/movie/603")
        log_call(
            LOGGER,
            method="GET",
            host=response.url.host,
            path=response.url.path,
            status=response.status_code,
            elapsed_ms=12,
            bytes_read=len(response.content),
            outcome="fresh",
        )

    messages = [record.getMessage() for record in caplog.records]
    assert any("outcome=fresh" in message for message in messages)
    assert any("status=200" in message for message in messages)
    assert all(authorization not in message for message in messages)
    assert all("Authorization" not in message for message in messages)


def test_the_call_log_reports_a_missing_status_rather_than_dropping_the_field(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER.name):
        log_call(
            LOGGER,
            method="GET",
            host="api.themoviedb.org",
            path="/3/movie/603",
            status=None,
            elapsed_ms=20_000,
            bytes_read=0,
            outcome="throttled",
        )

    assert "status=none" in caplog.records[0].getMessage()


def test_the_call_log_strips_the_newlines_a_crafted_path_would_forge_a_record_with(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER.name):
        log_call(
            LOGGER,
            method="GET",
            host="api.themoviedb.org",
            path="/3/movie\r\nprovider_call outcome=fresh status=200",
            status=404,
            elapsed_ms=1,
            bytes_read=0,
            outcome="fresh",
        )

    message = caplog.records[0].getMessage()
    assert len(caplog.records) == 1
    assert "\n" not in message and "\r" not in message
    assert "/3/movieprovider_call" in message


def test_the_digest_helper_round_trips_what_read_json_hands_back() -> None:
    raw = json.dumps({"b": 2, "a": 1}).encode()
    assert payload_digest(raw) == payload_digest(b'{"a":1,"b":2}')


# --- the pieces every provider client shares (Ruling 31) -------------------------------------------------


def _answered(status: int, *, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, headers=headers or {}, request=httpx.Request("GET", f"{TMDB_API_BASE_URL}/movie/603"))


@pytest.mark.parametrize("provider", ["TMDB", "TheTVDB"])
def test_a_refusal_names_the_provider_it_was_asked_about(provider: str) -> None:
    """One implementation, two upstreams: the provider is an argument so neither client owns a copy."""
    assert provider in str(refusal_for(_answered(503), provider))
    assert provider in str(refusal_for(_answered(404), provider))


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, ProviderNotFoundError),
        (429, ProviderRefusedError),
        (401, ProviderRefusedError),
        (400, ProviderRefusedError),
        (500, ProviderUnavailableError),
        (503, ProviderUnavailableError),
        # A non-following client reports a hop rather than chasing it, and an outage is the honest reading.
        (302, ProviderUnavailableError),
    ],
)
def test_each_status_reads_as_one_kind_of_refusal(status: int, expected: type[Exception]) -> None:
    assert isinstance(refusal_for(_answered(status), "TMDB"), expected)


def test_a_refusal_quotes_the_path_and_never_a_body() -> None:
    message = str(refusal_for(_answered(503), "TMDB"))

    assert "/3/movie/603" in message
    assert "603" in message


@pytest.mark.parametrize(
    ("header", "expected"),
    [("7", 7.0), ("0.5", 0.5), (None, None), ("Sun, 20 Sep 2026 12:00:07 GMT", None), ("soon", None)],
)
def test_retry_after_reads_only_a_number_of_seconds(header: str | None, expected: float | None) -> None:
    """`Retry-After` may be an HTTP-date, and a date is not a count of seconds to sleep for."""
    assert retry_after_seconds(header) == expected


def test_a_429_carries_its_retry_hint_through_the_refusal() -> None:
    refusal = refusal_for(_answered(429, headers={"retry-after": "7"}), "TheTVDB")

    assert isinstance(refusal, ProviderRefusedError)
    assert refusal.retry_after == pytest.approx(7.0)


def test_elapsed_is_measured_on_the_monotonic_clock_and_never_goes_backwards() -> None:
    assert elapsed_ms_since(time.monotonic()) >= 0
    assert elapsed_ms_since(time.monotonic() - 1.0) >= 1000


@pytest.mark.parametrize("value", ["a\rb", "a\nb", "a\r\nb"])
def test_scrubbed_strips_the_newlines_a_crafted_value_would_forge_a_record_with(value: str) -> None:
    assert scrubbed(value) == "ab"


def test_a_cursor_and_a_body_are_frozen_so_neither_can_be_edited_after_the_call() -> None:
    cursor = Cursor("tmdb_tv", "37854")
    body = ProviderBody(parsed={}, digest="d", etag=None, last_modified=None, elapsed_ms=1, bytes_read=2)

    # `FrozenInstanceError` subclasses `AttributeError`; both shapes are frozen AND slotted, so neither
    # an overwrite nor a new attribute survives the call that produced them.
    with pytest.raises(AttributeError):
        setattr(cursor, "resource_key", "1")
    with pytest.raises(AttributeError):
        setattr(body, "digest", "other")
