"""The TMDB client, driven entirely by bodies recorded from the live service. No test here opens a socket.

The reference values asserted below were verified live on 2026-09-15 and re-recorded on 2026-09-20; they
are the ones `docs/status.md` section 2.9 names.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Final

import httpx
import pytest
from pydantic import SecretStr

from provider_fixtures import (
    A_BURST_NO_TEST_EXHAUSTS,
    A_CREDENTIAL_WITH_A_NEWLINE,
    RECORDED_TOKEN,
    CountingBucket,
    H11RejectingResponder,
    RecordingResponseCache,
    fixture_bytes,
    fixture_etag,
    fixture_json,
    fixture_response,
    tmdb_client_for,
)
from tv_watchlist.clients.errors import (
    ProviderError,
    ProviderNotConfiguredError,
    ProviderNotFoundError,
    ProviderRefusedError,
    ProviderUnavailableError,
)
from tv_watchlist.clients.rate_limiter import TokenBucket
from tv_watchlist.clients.response_cache import CachedResponse
from tv_watchlist.clients.tmdb_client import TmdbClient, build_tmdb_client
from tv_watchlist.clients.transport import build_provider_http, payload_digest
from tv_watchlist.config import Settings
from tv_watchlist.constants import TMDB_API_BASE_URL, TMDB_CACHE_CEILING_DAYS, TMDB_REQUESTS_PER_SECOND
from tv_watchlist.models.tmdb.tmdb_search_page import TmdbSearchPage

TMDB: Final[str] = "tmdb"
ONE_PIECE: Final[int] = 37854
LOGGER_NAME: Final[str] = "tv_watchlist.clients.tmdb_client"
A_RETRY_AFTER: Final[str] = "7"
NOW: Final[datetime] = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
# Read off the recorded bytes once and written down here, rather than re-derived from the same file the
# client digested: a re-derivation agrees with a broken digest exactly as readily as with a right one.
A_RECORDED_TV_ETAG: Final[str] = 'W/"ca757da6e3326e6fd00b3cb5e52eda4b1d2c87925b2d43a60cb1fa84813d6ef7"'
A_RECORDED_TV_DIGEST: Final[str] = "4b3712ebb4cc133669c81f12b00a42aee593b55f44232f22320bcebbda3159e9"


def _cached(*, etag: str | None = None, digest: str | None = None, age_days: int = 0) -> CachedResponse:
    """A cursor a previous fetch would have left behind, aged by `age_days` against the frozen clock."""
    return CachedResponse(
        etag=etag, last_modified=None, payload_digest=digest, last_success_at=NOW - timedelta(days=age_days)
    )


def _unstamped(*, etag: str | None = None, digest: str | None = None) -> CachedResponse:
    """A cursor of unknown age: it carries what a fetch left behind but no record of when that was."""
    return CachedResponse(etag=etag, last_modified=None, payload_digest=digest, last_success_at=None)


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records]


# --- the credential ------------------------------------------------------------------------------------


async def test_a_missing_token_means_not_configured_and_no_request_is_made() -> None:
    client, responder = tmdb_client_for(fixture_response(TMDB, "search_tv_one_piece"), token=None)

    assert client.configured is False
    with pytest.raises(ProviderNotConfiguredError):
        await client.search_tv("One Piece")

    assert responder.requested == []


async def test_a_missing_token_refuses_a_cached_call_before_it_even_looks_up_the_cursor() -> None:
    cache = RecordingResponseCache()
    client, responder = tmdb_client_for(fixture_response(TMDB, "tv_37854"), token=None, cache=cache)

    with pytest.raises(ProviderNotConfiguredError):
        await client.tv_details(ONE_PIECE)

    assert (responder.requested, cache.lookups) == ([], [])


async def test_the_bearer_header_carries_the_token_and_the_url_carries_no_key() -> None:
    client, responder = tmdb_client_for(fixture_response(TMDB, "tv_37854"))

    await client.tv_details(ONE_PIECE)

    request = responder.requests[0]
    assert request.headers["Authorization"] == f"Bearer {RECORDED_TOKEN}"
    assert "api_key" not in str(request.url)
    assert RECORDED_TOKEN not in str(request.url)
    assert responder.requested == ["https://api.themoviedb.org/3/tv/37854"]


async def test_the_token_never_reaches_the_call_log(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = tmdb_client_for(fixture_response(TMDB, "tv_37854"))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await client.tv_details(ONE_PIECE)

    messages = _messages(caplog)
    assert messages, "the call should have logged a line"
    assert all(RECORDED_TOKEN not in message and "Authorization" not in message for message in messages)
    assert any("outcome=fresh" in message and "status=200" in message for message in messages)


# --- the reference values ------------------------------------------------------------------------------


async def test_search_attack_of_the_clones_ranks_the_franchise_title_first() -> None:
    client, responder = tmdb_client_for(fixture_response(TMDB, "search_movie_attack_of_the_clones"))

    page = await client.search_movie("Attack of the Clones")

    top = page.results[0]
    assert top.title == "Star Wars: Episode II - Attack of the Clones"
    assert top.release_date is not None and top.release_date.startswith("2002")
    assert responder.requested == ["https://api.themoviedb.org/3/search/movie?query=Attack%20of%20the%20Clones&page=1"]


async def test_one_piece_season_two_episode_numbers_run_62_to_77() -> None:
    """TMDB numbers anime absolute-continuously inside season buckets; the client stores that, not `SxxEyy`."""
    client, _ = tmdb_client_for(fixture_response(TMDB, "tv_37854_season_2"))

    season = await client.season_details(ONE_PIECE, 2)

    assert season is not None
    assert [episode.episode_number for episode in season.episodes] == list(range(62, 78))
    assert len(season.episodes) == 16
    assert {episode.season_number for episode in season.episodes} == {2}
    # The pair is stored verbatim: nothing renumbered episode 62 into a season-relative 1.
    assert season.episodes[0].episode_number != 1


async def test_one_piece_details_report_23_seasons_and_24_season_entries() -> None:
    client, _ = tmdb_client_for(fixture_response(TMDB, "tv_37854"))

    series = await client.tv_details(ONE_PIECE)

    assert series is not None
    assert series.number_of_seasons == 23
    assert len(series.seasons) == 24
    assert series.number_of_episodes == 1181
    assert series.seasons[0].season_number == 0


@pytest.mark.parametrize(("tv_id", "tvdb_id"), [(37854, 81797), (1405, 79349), (60572, 76703)])
async def test_external_ids_carry_the_tvdb_id(tv_id: int, tvdb_id: int) -> None:
    client, responder = tmdb_client_for(fixture_response(TMDB, f"tv_{tv_id}_external_ids"))

    ids = await client.external_ids("tv", tv_id)

    assert ids is not None
    assert ids.tvdb_id == tvdb_id
    assert responder.requested == [f"https://api.themoviedb.org/3/tv/{tv_id}/external_ids"]


async def test_configuration_exposes_secure_base_url_and_poster_sizes() -> None:
    client, _ = tmdb_client_for(fixture_response(TMDB, "configuration"))

    configuration = await client.configuration()

    assert configuration is not None
    assert configuration.images.secure_base_url == "https://image.tmdb.org/t/p/"
    assert "w500" in configuration.images.poster_sizes


async def test_alternative_titles_are_parsed() -> None:
    client, _ = tmdb_client_for(fixture_response(TMDB, "tv_37854_alternative_titles"))

    titles = await client.alternative_titles("tv", ONE_PIECE)

    assert titles is not None
    assert len(titles.results) == 29
    recorded = [(title.iso_3166_1, title.title, title.type) for title in titles.results]
    assert ("CN", "海贼王", "") in recorded
    # `type` is free text and carries a real episode span on this one, which is why it is not dropped.
    assert ("IT", "Tutti All'arrembaggio", "episodes 54-195") in recorded
    assert all(title.iso_3166_1 and title.title for title in titles.results)


async def test_a_movie_runtime_stays_in_the_minutes_tmdb_sent() -> None:
    """142 is minutes. Nothing here multiplies by 60 - the ingest does that once, at its own boundary."""
    client, _ = tmdb_client_for(fixture_response(TMDB, "movie_attack_of_the_clones"))

    movie = await client.movie_details(1894)

    assert movie is not None
    assert movie.runtime == 142
    assert movie.release_date == "2002-05-15"


async def test_a_changes_page_names_the_keys_that_moved() -> None:
    client, responder = tmdb_client_for(fixture_response(TMDB, "changes_tv_37854"))

    changes = await client.changes("tv", ONE_PIECE, start_date=date(2026, 9, 7), end_date=date(2026, 9, 20))

    assert changes is not None
    assert [entry.key for entry in changes.changes] == ["season", "images"]
    assert responder.requested == [
        "https://api.themoviedb.org/3/tv/37854/changes?start_date=2026-09-07&end_date=2026-09-20"
    ]


async def test_two_change_windows_are_two_cursors_rather_than_one() -> None:
    """The resource a changes call fetches is a window, so the window belongs in the key that remembers it."""
    cache = RecordingResponseCache()
    client, _ = tmdb_client_for(
        fixture_response(TMDB, "changes_tv_37854"), fixture_response(TMDB, "changes_tv_37854"), cache=cache
    )

    await client.changes("tv", ONE_PIECE, start_date=date(2026, 9, 7), end_date=date(2026, 9, 20))
    await client.changes("tv", ONE_PIECE, start_date=date(2026, 8, 7), end_date=date(2026, 8, 20))

    september = "tv/37854?start_date=2026-09-07&end_date=2026-09-20"
    august = "tv/37854?start_date=2026-08-07&end_date=2026-08-20"
    assert [stored.resource_key for stored in cache.stored] == [september, august]
    # Read under the same key it is written under, or a cursor would answer for a window it never saw.
    assert cache.lookups == [("tmdb", "tmdb_changes", september), ("tmdb", "tmdb_changes", august)]


async def test_a_tv_search_reads_the_series_name_rather_than_a_title() -> None:
    client, responder = tmdb_client_for(fixture_response(TMDB, "search_tv_one_piece"))

    page = await client.search_tv("One Piece", first_air_date_year=1999)

    assert page.results[0].name == "One Piece"
    assert page.results[0].original_name == "ワンピース"
    assert responder.requested == [
        "https://api.themoviedb.org/3/search/tv?query=One%20Piece&first_air_date_year=1999&page=1"
    ]


# --- conditional requests ------------------------------------------------------------------------------


async def test_a_304_returns_none_and_logs_not_modified(caplog: pytest.LogCaptureFixture) -> None:
    etag = fixture_etag(TMDB, "tv_37854")
    assert etag is not None, "the recorded tv_37854 response carried an ETag"
    cache = RecordingResponseCache(primed=_cached(etag=etag))
    client, responder = tmdb_client_for(httpx.Response(304, headers={"etag": etag}), cache=cache, clock=lambda: NOW)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        assert await client.tv_details(ONE_PIECE) is None

    assert responder.requests[0].headers["If-None-Match"] == etag
    assert any("outcome=not-modified" in message and "status=304" in message for message in _messages(caplog))
    assert cache.stored == []


async def test_an_equal_digest_returns_none_when_tmdb_sends_no_etag() -> None:
    """Not every TMDB endpoint sends an ETag, so an identical body is the other way to learn nothing moved."""
    recorded = fixture_bytes(TMDB, "tv_37854")
    cache = RecordingResponseCache()
    client, responder = tmdb_client_for(
        httpx.Response(200, content=recorded),
        httpx.Response(200, content=recorded),
        cache=cache,
        clock=lambda: NOW,
    )

    first = await client.tv_details(ONE_PIECE)
    assert first is not None
    assert len(cache.stored) == 1
    cache.primed = _cached(digest=cache.stored[0].payload_digest)

    assert await client.tv_details(ONE_PIECE) is None
    # Two requests really went out; only the first one had anything worth writing.
    assert len(responder.requested) == 2
    assert len(cache.stored) == 1


async def test_a_stored_cursor_carries_the_etag_and_the_digest_of_what_arrived() -> None:
    cache = RecordingResponseCache()
    client, _ = tmdb_client_for(fixture_response(TMDB, "tv_37854"), cache=cache)

    await client.tv_details(ONE_PIECE)

    stored = cache.stored[0]
    assert (stored.source, stored.resource_type, stored.resource_key) == ("tmdb", "tmdb_tv", "37854")
    assert stored.etag == A_RECORDED_TV_ETAG
    assert stored.payload_digest == A_RECORDED_TV_DIGEST


async def test_a_cursor_past_the_six_month_ceiling_refetches_unconditionally() -> None:
    """TMDB's terms cap caching at six months, so an old cursor stops being conditional and is rewritten."""
    etag = fixture_etag(TMDB, "tv_37854")
    digest = payload_digest(fixture_bytes(TMDB, "tv_37854"))
    cache = RecordingResponseCache(primed=_cached(etag=etag, digest=digest, age_days=TMDB_CACHE_CEILING_DAYS + 1))
    client, responder = tmdb_client_for(fixture_response(TMDB, "tv_37854"), cache=cache, clock=lambda: NOW)

    series = await client.tv_details(ONE_PIECE)

    assert series is not None, "an equal digest must not short-circuit a cursor past the ceiling"
    assert "If-None-Match" not in responder.requests[0].headers
    assert len(cache.stored) == 1


async def test_a_cursor_inside_the_ceiling_still_sends_the_conditional_header() -> None:
    etag = fixture_etag(TMDB, "tv_37854")
    cache = RecordingResponseCache(primed=_cached(etag=etag, age_days=TMDB_CACHE_CEILING_DAYS - 1))
    client, responder = tmdb_client_for(httpx.Response(304), cache=cache, clock=lambda: NOW)

    assert await client.tv_details(ONE_PIECE) is None
    assert responder.requests[0].headers["If-None-Match"] == etag


async def test_a_cursor_of_unknown_age_carrying_an_etag_is_renewed_rather_than_trusted() -> None:
    """A cursor with no `last_success_at` could 304 for ever, so the six-month ceiling would never fire."""
    etag = fixture_etag(TMDB, "tv_37854")
    cache = RecordingResponseCache(primed=_unstamped(etag=etag))
    client, responder = tmdb_client_for(fixture_response(TMDB, "tv_37854"), cache=cache, clock=lambda: NOW)

    series = await client.tv_details(ONE_PIECE)

    assert series is not None
    assert "If-None-Match" not in responder.requests[0].headers
    # The refetch is what puts a stamp on the cursor, which is what lets the ceiling fire next time.
    assert len(cache.stored) == 1


async def test_a_cursor_of_unknown_age_carrying_only_a_digest_is_renewed_too() -> None:
    """The digest short-circuit is the other way a stampless cursor could outlive the licence ceiling."""
    digest = payload_digest(fixture_bytes(TMDB, "tv_37854"))
    cache = RecordingResponseCache(primed=_unstamped(digest=digest))
    client, responder = tmdb_client_for(fixture_response(TMDB, "tv_37854"), cache=cache, clock=lambda: NOW)

    series = await client.tv_details(ONE_PIECE)

    assert series is not None, "an equal digest must not short-circuit a cursor whose age is unknown"
    assert "If-None-Match" not in responder.requests[0].headers
    assert len(cache.stored) == 1


async def test_an_empty_cursor_is_a_first_fetch_not_a_renewal(caplog: pytest.LogCaptureFixture) -> None:
    """A row with no validator and no stamp has never succeeded: unconditional, and plainly `fresh`."""
    cache = RecordingResponseCache(primed=_unstamped())
    client, responder = tmdb_client_for(fixture_response(TMDB, "tv_37854"), cache=cache, clock=lambda: NOW)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        series = await client.tv_details(ONE_PIECE)

    assert series is not None
    assert "If-None-Match" not in responder.requests[0].headers
    assert any("outcome=fresh" in message and "status=200" in message for message in _messages(caplog))
    assert len(cache.stored) == 1


async def test_a_304_to_a_renewing_cursor_is_reported_rather_than_read_as_not_modified(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A cursor past the ceiling asks unconditionally, so a 304 agrees with nothing this call sent."""
    etag = fixture_etag(TMDB, "tv_37854")
    cache = RecordingResponseCache(primed=_cached(etag=etag, age_days=TMDB_CACHE_CEILING_DAYS + 1))
    client, responder = tmdb_client_for(httpx.Response(304), cache=cache, clock=lambda: NOW)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        with pytest.raises(ProviderUnavailableError):
            await client.tv_details(ONE_PIECE)

    assert "If-None-Match" not in responder.requests[0].headers
    assert cache.failures[0].resource_key == "37854"
    messages = _messages(caplog)
    assert any("status=304" in message and "outcome=failed" in message for message in messages)
    # The one line says it failed; a `not-modified` line beside it would claim the opposite.
    assert all("outcome=not-modified" not in message for message in messages)


async def test_a_304_to_a_first_fetch_is_reported_rather_than_read_as_not_modified() -> None:
    """A cursor with nothing to be conditional on is the same case: silence here would skip a write."""
    cache = RecordingResponseCache()
    client, responder = tmdb_client_for(httpx.Response(304), cache=cache, clock=lambda: NOW)

    with pytest.raises(ProviderUnavailableError):
        await client.tv_details(ONE_PIECE)

    assert "If-None-Match" not in responder.requests[0].headers
    assert cache.stored == []
    assert len(cache.failures) == 1


async def test_search_pages_are_never_cached() -> None:
    cache = RecordingResponseCache()
    client, _ = tmdb_client_for(fixture_response(TMDB, "search_movie_superman"), cache=cache)

    page = await client.search_movie("Superman")

    # The recorded page really was read, so an empty cursor list is the rule holding rather than a call
    # that quietly did nothing: 218 hits, the 2025 film first.
    top = page.results[0]
    assert (top.id, top.title, top.release_date) == (1061474, "Superman", "2025-07-09")
    assert page.total_results == 218
    assert (cache.stored, cache.lookups, cache.failures) == ([], [], [])


# --- refusals ------------------------------------------------------------------------------------------


async def test_a_429_raises_refused_with_retry_after() -> None:
    cache = RecordingResponseCache()
    client, _ = tmdb_client_for(httpx.Response(429, headers={"retry-after": A_RETRY_AFTER}), cache=cache)

    with pytest.raises(ProviderRefusedError) as refusal:
        await client.tv_details(ONE_PIECE)

    assert refusal.value.retry_after == pytest.approx(7.0)
    assert len(cache.failures) == 1


@pytest.mark.parametrize("header", [None, "Sun, 20 Sep 2026 12:00:07 GMT"])
async def test_a_429_without_a_numeric_retry_after_still_refuses(header: str | None) -> None:
    client, _ = tmdb_client_for(httpx.Response(429, headers={} if header is None else {"retry-after": header}))

    with pytest.raises(ProviderRefusedError) as refusal:
        await client.tv_details(ONE_PIECE)

    assert refusal.value.retry_after is None


async def test_a_5xx_raises_unavailable_and_records_the_failure(caplog: pytest.LogCaptureFixture) -> None:
    cache = RecordingResponseCache()
    client, _ = tmdb_client_for(httpx.Response(503), cache=cache)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        with pytest.raises(ProviderUnavailableError):
            await client.tv_details(ONE_PIECE)

    failure = cache.failures[0]
    assert (failure.source, failure.resource_type, failure.resource_key) == ("tmdb", "tmdb_tv", "37854")
    assert "ProviderUnavailableError" in failure.error and "503" in failure.error
    assert any("status=503" in message for message in _messages(caplog))


async def test_a_404_raises_not_found() -> None:
    cache = RecordingResponseCache()
    client, _ = tmdb_client_for(httpx.Response(404, json={"status_message": "not found"}), cache=cache)

    with pytest.raises(ProviderNotFoundError):
        await client.movie_details(1)

    assert cache.failures[0].resource_key == "1"


async def test_a_401_is_a_refusal_not_an_outage() -> None:
    client, _ = tmdb_client_for(httpx.Response(401, json={"status_message": "invalid token"}))

    with pytest.raises(ProviderRefusedError):
        await client.tv_details(ONE_PIECE)


async def test_a_redirect_is_reported_rather_than_followed() -> None:
    client, responder = tmdb_client_for(httpx.Response(302, headers={"location": "https://evil.example/"}))

    with pytest.raises(ProviderUnavailableError):
        await client.tv_details(ONE_PIECE)

    assert len(responder.requested) == 1


def _never_answers(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("the upstream did not answer", request=request)


async def test_a_transport_failure_is_unavailable_and_is_recorded(caplog: pytest.LogCaptureFixture) -> None:
    """Built by hand rather than through `tmdb_client_for`: this one needs a transport that raises."""
    cache = RecordingResponseCache()
    client = TmdbClient(
        SecretStr(RECORDED_TOKEN),
        http=build_provider_http(TMDB_API_BASE_URL, headers={}, transport=httpx.MockTransport(_never_answers)),
        bucket=TokenBucket(TMDB_REQUESTS_PER_SECOND, A_BURST_NO_TEST_EXHAUSTS),
        cache=cache,
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        with pytest.raises(ProviderUnavailableError):
            await client.tv_details(ONE_PIECE)

    assert "ConnectTimeout" in cache.failures[0].error
    # No response ever arrived, so the status field carries the absence rather than dropping it.
    assert any("status=none" in message and "outcome=failed" in message for message in _messages(caplog))


async def test_a_body_this_client_cannot_read_is_unavailable_and_says_nothing_about_the_body() -> None:
    cache = RecordingResponseCache()
    client, _ = tmdb_client_for(httpx.Response(200, json={"seasons": "not a list"}), cache=cache)

    with pytest.raises(ProviderUnavailableError) as failure:
        await client.tv_details(ONE_PIECE)

    assert "TmdbTv" in str(failure.value)
    assert "not a list" not in str(failure.value)
    assert "not a list" not in cache.failures[0].error


async def test_a_304_to_an_unconditional_search_is_reported_rather_than_read_as_an_empty_page() -> None:
    client, _ = tmdb_client_for(httpx.Response(304))

    with pytest.raises(ProviderUnavailableError):
        await client.search_movie("Superman")


@pytest.mark.parametrize(
    ("status", "answer", "error"),
    [
        (401, {"json": {"status_message": "invalid token"}}, ProviderRefusedError),
        (404, {"json": {"status_message": "not found"}}, ProviderNotFoundError),
        (429, {"headers": {"retry-after": A_RETRY_AFTER}}, ProviderRefusedError),
        (503, {}, ProviderUnavailableError),
        # A 200 whose shape this client cannot read produced nothing to write either, so it is a
        # failed attempt like any other - the status says which kind.
        (200, {"json": {"seasons": "not a list"}}, ProviderUnavailableError),
    ],
)
async def test_a_failed_attempt_logs_outcome_failed_and_never_throttled(
    status: int, answer: dict[str, object], error: type[ProviderError], caplog: pytest.LogCaptureFixture
) -> None:
    """`throttled` is a wait on the bucket. A refusal, an outage and an unreadable body are `failed`."""
    client, _ = tmdb_client_for(httpx.Response(status, **answer))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        with pytest.raises(error):
            await client.tv_details(ONE_PIECE)

    messages = _messages(caplog)
    assert any(f"status={status}" in message and "outcome=failed" in message for message in messages)
    assert all("outcome=throttled" not in message for message in messages)


# --- the budget ----------------------------------------------------------------------------------------


async def test_every_call_passes_through_the_bucket() -> None:
    bucket = CountingBucket()
    client, responder = tmdb_client_for(
        fixture_response(TMDB, "tv_37854"),
        fixture_response(TMDB, "tv_37854_season_2"),
        fixture_response(TMDB, "search_movie_superman"),
        bucket=bucket,
    )

    await client.tv_details(ONE_PIECE)
    await client.season_details(ONE_PIECE, 2)
    await client.search_movie("Superman")

    assert bucket.acquires == len(responder.requested) == 3


async def test_a_refused_call_still_spent_a_token() -> None:
    bucket = CountingBucket()
    client, _ = tmdb_client_for(httpx.Response(503), bucket=bucket)

    with pytest.raises(ProviderUnavailableError):
        await client.tv_details(ONE_PIECE)

    assert bucket.acquires == 1


# --- the fixtures themselves ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "configuration",
        "search_tv_one_piece",
        "search_movie_attack_of_the_clones",
        "search_movie_superman",
        "search_movie_the_consultant",
        "search_movie_marvel_one_shot_the_consultant",
        "search_tv_inuyasha_the_final_act",
        "tv_37854",
        "tv_37854_season_0",
        "tv_37854_season_1",
        "tv_37854_season_2",
        "tv_37854_external_ids",
        "tv_1405_external_ids",
        "tv_60572_external_ids",
        "tv_37854_alternative_titles",
        "tv_35610",
        "tv_35610_season_2",
        "tv_1429_season_0",
        "movie_attack_of_the_clones",
        "movie_superman_1978",
        "changes_tv_37854",
    ],
)
def test_every_recorded_fixture_is_readable_and_carries_no_credential(name: str) -> None:
    """A recorded body is data. The recorder redacts the token; this is the standing proof it stayed redacted."""
    body = fixture_response(TMDB, name).content.decode()
    assert fixture_json(TMDB, name)
    assert "Bearer " not in body
    # Every TMDB read access token is a JWT, and every JWT's compact form starts `eyJ`.
    assert "eyJ" not in body


async def test_a_search_page_round_trips_the_body_it_was_recorded_from() -> None:
    client, _ = tmdb_client_for(fixture_response(TMDB, "search_movie_the_consultant"))

    page = await client.search_movie("The Consultant")

    assert page == TmdbSearchPage.model_validate(fixture_json(TMDB, "search_movie_the_consultant"))
    assert page.total_results == 6


# --- the composition seam ------------------------------------------------------------------------------


def _built(token: str | None) -> TmdbClient:
    """A client built the way T19 will build it: the token from settings, everything else handed in."""
    return build_tmdb_client(
        Settings(_env_file=None, tmdb_read_access_token=None if token is None else SecretStr(token)),
        http=build_provider_http(TMDB_API_BASE_URL, headers={}, transport=httpx.MockTransport(_never_answers)),
        bucket=TokenBucket(TMDB_REQUESTS_PER_SECOND, A_BURST_NO_TEST_EXHAUSTS),
        cache=RecordingResponseCache(),
    )


@pytest.mark.parametrize(("token", "configured"), [(RECORDED_TOKEN, True), (None, False)])
def test_the_builder_takes_the_token_from_settings_and_nothing_else(token: str | None, configured: bool) -> None:
    assert _built(token).configured is configured


# --- the credential must not reach an exception through an upstream error's TEXT --------------------


async def test_a_token_carrying_a_newline_never_reaches_the_raised_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """h11 quotes the WHOLE header value into its `LocalProtocolError`, and that is an `httpx.HTTPError`.

    Interpolating it - which this client used to do - put the Bearer token into the raised message, into
    `sync_state.last_error` and into the call log. `transport.unreachable` is the one place that rule now
    lives (CLAUDE.md section 10.3, B10).
    """
    responder = H11RejectingResponder(fixture_response(TMDB, "tv_37854"))
    client, _ = tmdb_client_for(token=A_CREDENTIAL_WITH_A_NEWLINE, responder=responder)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME), pytest.raises(ProviderUnavailableError) as raised:
        await client.tv_details(ONE_PIECE)

    assert "cret-newline-credential" not in str(raised.value)
    assert A_CREDENTIAL_WITH_A_NEWLINE not in str(raised.value)
    assert all("cret-newline-credential" not in message for message in _messages(caplog))
    # The chain is kept, so a traceback still names what actually went wrong - and asserting that the
    # CAUSE does carry the credential is what proves this test is reproducing the real leak rather than a
    # transport that simply never mentioned it.
    assert isinstance(raised.value.__cause__, httpx.HTTPError)
    assert "cret-newline-credential" in str(raised.value.__cause__)


async def test_a_token_carrying_a_newline_reaches_no_header_but_the_bearer_and_no_cursor() -> None:
    cache = RecordingResponseCache()
    responder = H11RejectingResponder(fixture_response(TMDB, "tv_37854"))
    client, _ = tmdb_client_for(token=A_CREDENTIAL_WITH_A_NEWLINE, cache=cache, responder=responder)

    with pytest.raises(ProviderUnavailableError):
        await client.tv_details(ONE_PIECE)

    request = responder.requests[0]
    others = {name: value for name, value in request.headers.items() if name.lower() != "authorization"}
    assert all("cret-newline-credential" not in value for value in others.values())
    assert "cret-newline-credential" not in str(request.url)
    assert all("cret-newline-credential" not in failure.error for failure in cache.failures)
