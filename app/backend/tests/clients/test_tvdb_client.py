"""The TheTVDB client, driven entirely by bodies recorded from the live service. No test here opens a socket.

The reference values asserted below were verified live on 2026-09-15 and re-recorded on 2026-09-20; they are
the ones `docs/status.md` section 2.9 names. This file may spell season types out loud - it is asserting what
the live list contained on the day it was read. The client may not, and one test below reads its source to
prove it does not.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import httpx
import pytest
from pydantic import SecretStr

import tv_watchlist.clients.tvdb_client as tvdb_client_module
import tv_watchlist.data.enums as data_enums
from provider_fixtures import (
    A_BURST_NO_TEST_EXHAUSTS,
    A_CREDENTIAL_WITH_A_NEWLINE,
    A_RECORDED_KEY,
    A_RECORDED_PIN,
    RECORDED_TOKEN,
    TVDB,
    CountingBucket,
    H11RejectingResponder,
    RecordingResponseCache,
    fixture_bytes,
    fixture_json,
    fixture_response,
    tvdb_client_for,
)
from tv_watchlist.clients.errors import (
    OutboundUrlError,
    ProviderNotConfiguredError,
    ProviderNotFoundError,
    ProviderRefusedError,
    ProviderUnavailableError,
    UnknownSeasonTypeError,
)
from tv_watchlist.clients.rate_limiter import TokenBucket
from tv_watchlist.clients.response_cache import CachedResponse
from tv_watchlist.clients.transport import build_provider_http, payload_digest
from tv_watchlist.clients.tvdb_client import TvdbClient, build_tvdb_client
from tv_watchlist.config import Settings
from tv_watchlist.constants import TVDB_API_BASE_URL, TVDB_REQUESTS_PER_SECOND, TVDB_TOKEN_REFRESH_DAYS
from tv_watchlist.models.tvdb.tvdb_episode import TvdbEpisode

ONE_PIECE: Final[int] = 81797
LOGGER_NAME: Final[str] = "tv_watchlist.clients.tvdb_client"
NOW: Final[datetime] = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
LOGIN_PATH: Final[str] = "/v4/login"

# `docs/status.md` section 2.9: the list read from the live service on 2026-09-15 and again on 2026-09-20.
THE_LIVE_SEASON_TYPES: Final[frozenset[str]] = frozenset(
    {"official", "dvd", "absolute", "alternate", "regional", "altdvd", "alttwo"}
)
# Laboon. One episode, three numberings - the row that makes the case for `episode_order`.
LABOON_AIRED: Final[str] = "2001-03-21"
LABOON_NAME_PREFIX: Final[str] = "The First Line of Defense"

EVERY_RECORDED_FIXTURE: Final[tuple[str, ...]] = (
    "login",
    "seasons_types",
    "series_81797_translations_eng",
    "series_81797_episodes_absolute_eng_page0",
    "series_81797_episodes_absolute_eng_page1",
    "series_81797_episodes_official_eng_page0",
    "series_81797_episodes_dvd_eng_page0",
    "series_81797_episodes_dvd_eng_page1",
    "series_81797_episodes_unknown_type",
    "updates_episodes",
)


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def _logins(responder_requests: list[httpx.Request]) -> list[httpx.Request]:
    return [request for request in responder_requests if request.url.path == LOGIN_PATH]


def _laboon(episodes: tuple[TvdbEpisode, ...]) -> TvdbEpisode:
    """The one episode both reference values name, found by its title rather than by a number under test."""
    named = [
        episode
        for episode in episodes
        if (episode.name or "").startswith(LABOON_NAME_PREFIX) and episode.aired == LABOON_AIRED
    ]
    assert len(named) == 1, f"expected exactly one Laboon in the page, found {len(named)}"
    return named[0]


# --- the credentials -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("api_key", "pin"),
    [(A_RECORDED_KEY, None), (None, A_RECORDED_PIN), (None, None)],
    ids=["no pin", "no key", "neither"],
)
async def test_a_missing_key_or_pin_means_not_configured(api_key: str | None, pin: str | None) -> None:
    """The End-User Subscriptions model needs both; a client missing either refuses before it builds a request."""
    client, responder = tvdb_client_for(fixture_response(TVDB, "seasons_types"), api_key=api_key, pin=pin)

    assert client.configured is False
    with pytest.raises(ProviderNotConfiguredError):
        await client.season_types()

    assert responder.requested == []


async def test_both_credentials_present_means_configured() -> None:
    client, _ = tvdb_client_for(fixture_response(TVDB, "seasons_types"))

    assert client.configured is True


async def test_login_sends_the_pin_and_caches_the_token_with_its_issue_time() -> None:
    client, responder = tvdb_client_for(fixture_response(TVDB, "seasons_types"), clock=lambda: NOW)

    await client.login()
    await client.season_types()

    login = responder.requests[0]
    body = login.read().decode()
    assert (login.method, str(login.url)) == ("POST", f"{TVDB_API_BASE_URL}/login")
    assert '"pin"' in body and '"apikey"' in body
    assert A_RECORDED_PIN in body and A_RECORDED_KEY in body
    assert client.token_issued_at == NOW
    # Every later call carries the token the login handed back, and the login itself carried no bearer.
    assert "authorization" not in login.headers
    assert responder.requests[1].headers["Authorization"] == f"Bearer {RECORDED_TOKEN}"


async def test_a_login_refusal_is_reported_rather_than_retried() -> None:
    client, responder = tvdb_client_for(httpx.Response(401, json={"status": "failure"}), login=False)

    with pytest.raises(ProviderRefusedError):
        await client.login()

    assert len(responder.requested) == 1
    assert client.token_issued_at is None


async def test_the_token_is_refreshed_proactively_after_25_days() -> None:
    """The token lives a month and there is no refresh endpoint, so age - not a 401 - is what replaces it."""
    clock = {"now": NOW}
    client, responder = tvdb_client_for(
        fixture_response(TVDB, "login"),
        fixture_response(TVDB, "series_81797_translations_eng"),
        clock=lambda: clock["now"],
    )

    await client.login()
    clock["now"] = NOW + timedelta(days=TVDB_TOKEN_REFRESH_DAYS + 1)
    await client.series_translation(ONE_PIECE)

    assert len(_logins(responder.requests)) == 2
    assert client.token_issued_at == clock["now"]


async def test_a_token_inside_the_refresh_window_is_reused() -> None:
    clock = {"now": NOW}
    client, responder = tvdb_client_for(
        fixture_response(TVDB, "series_81797_translations_eng"), clock=lambda: clock["now"]
    )

    await client.login()
    clock["now"] = NOW + timedelta(days=TVDB_TOKEN_REFRESH_DAYS - 1)
    await client.series_translation(ONE_PIECE)

    assert len(_logins(responder.requests)) == 1


async def test_a_401_on_a_fresh_token_refuses_and_never_triggers_a_silent_relogin() -> None:
    """A re-login on 401 would hide a revoked key behind an infinite retry; age is the only trigger."""
    client, responder = tvdb_client_for(httpx.Response(401, json={"status": "failure"}), clock=lambda: NOW)

    with pytest.raises(ProviderRefusedError):
        await client.series_translation(ONE_PIECE)

    assert len(_logins(responder.requests)) == 1
    assert len(responder.requested) == 2


async def test_the_token_never_reaches_the_call_log(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = tvdb_client_for(fixture_response(TVDB, "seasons_types"))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await client.season_types()

    messages = _messages(caplog)
    assert messages, "the call should have logged a line"
    assert all(RECORDED_TOKEN not in message and "Authorization" not in message for message in messages)
    assert all(A_RECORDED_KEY not in message and A_RECORDED_PIN not in message for message in messages)


async def test_the_login_is_logged_as_the_post_it_is(caplog: pytest.LogCaptureFixture) -> None:
    """A record that called every call a GET would misdescribe the only POST this client makes."""
    client, _ = tvdb_client_for(fixture_response(TVDB, "seasons_types"))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await client.season_types()

    messages = _messages(caplog)
    assert any("method=POST" in message and LOGIN_PATH in message for message in messages)
    assert any("method=GET" in message and "/seasons/types" in message for message in messages)


async def test_the_recording_responder_answers_through_one_transport() -> None:
    """Regression: the recorder used to wrap a second transport around the base's, leaving the first dead."""
    client, responder = tvdb_client_for(fixture_response(TVDB, "seasons_types"))

    await client.season_types()

    assert [str(request.url) for request in responder.requests] == responder.requested
    assert len(responder.requested) == 2


# --- the season-type list ------------------------------------------------------------------------------


async def test_the_live_season_type_list_has_seven_members_including_altdvd_and_alttwo() -> None:
    """Reference value, `docs/status.md` section 2.9. `default` is an endpoint alias, never a type."""
    client, responder = tvdb_client_for(fixture_response(TVDB, "seasons_types"))

    types = await client.season_types()

    assert {entry.type for entry in types} == THE_LIVE_SEASON_TYPES
    assert len(types) == 7
    assert "default" not in {entry.type for entry in types}
    assert responder.requested[-1] == f"{TVDB_API_BASE_URL}/seasons/types"


@pytest.mark.parametrize("forbidden", ["altdvd", "alttwo", "regional"])
def test_no_season_type_name_is_hard_coded_in_the_client_or_the_enums(forbidden: str) -> None:
    """The list is examples upstream, not an enum, so a type this app has never seen must still be storable."""
    sources = [
        Path(str(tvdb_client_module.__file__)).read_text(),
        Path(str(data_enums.__file__)).read_text(),
    ]

    assert all(forbidden not in source for source in sources)


async def test_the_season_type_list_is_fetched_once_per_process() -> None:
    client, responder = tvdb_client_for(fixture_response(TVDB, "seasons_types"))

    first = await client.season_types()
    second = await client.season_types()

    assert first == second
    assert len(responder.requested) == 2  # the login and the one list; the second call asked for nothing.


async def test_an_unrecognised_season_type_is_refused_before_any_request() -> None:
    client, responder = tvdb_client_for(fixture_response(TVDB, "seasons_types"))
    await client.season_types()
    already_asked = len(responder.requested)

    with pytest.raises(UnknownSeasonTypeError):
        await client.series_episodes(ONE_PIECE, "bogus")

    assert len(responder.requested) == already_asked
    assert not any("/episodes/" in url for url in responder.requested)


async def test_an_unrecognised_season_type_refuses_the_whole_walk_too() -> None:
    client, responder = tvdb_client_for(fixture_response(TVDB, "seasons_types"))

    with pytest.raises(UnknownSeasonTypeError):
        await client.all_series_episodes(ONE_PIECE, "../../secret")

    assert not any("secret" in url for url in responder.requested)


# --- the empty-array guard -----------------------------------------------------------------------------


async def test_a_zero_length_episodes_array_is_unknown_not_empty() -> None:
    """A Jellyfin plugin read this shape as authoritative and deleted 194 seasons a scan. It is `unknown`."""
    client, _ = tvdb_client_for(
        fixture_response(TVDB, "seasons_types"),
        fixture_response(TVDB, "series_81797_episodes_unknown_type"),
    )

    result = await client.all_series_episodes(ONE_PIECE, "absolute")

    assert result.known is False
    assert result.episodes == ()
    assert result.pages == 1


async def test_a_page_that_really_carries_episodes_is_known() -> None:
    client, _ = tvdb_client_for(
        fixture_response(TVDB, "seasons_types"),
        fixture_response(TVDB, "series_81797_episodes_dvd_eng_page0"),
        fixture_response(TVDB, "series_81797_episodes_dvd_eng_page1"),
    )

    result = await client.all_series_episodes(ONE_PIECE, "dvd")

    assert result.known is True
    assert len(result.episodes) == 934


async def test_a_walk_reports_what_the_service_said_the_ordering_holds() -> None:
    """`reported` against `len(episodes)` is how a caller tells a short walk from a complete one.

    A truncated read that claims success is worse than one that fails (CLAUDE.md section 9.2), and the
    only evidence available is the count the pages carried. The recorded two-page walk agrees with it.
    """
    client, _ = tvdb_client_for(
        fixture_response(TVDB, "seasons_types"),
        fixture_response(TVDB, "series_81797_episodes_dvd_eng_page0"),
        fixture_response(TVDB, "series_81797_episodes_dvd_eng_page1"),
    )
    recorded = fixture_json(TVDB, "series_81797_episodes_dvd_eng_page0")["links"]
    assert isinstance(recorded, dict)

    result = await client.all_series_episodes(ONE_PIECE, "dvd")

    assert result.reported == recorded["total_items"]
    assert len(result.episodes) == result.reported
    assert result.pages == 2


async def test_a_walk_whose_pages_carried_no_count_reports_nothing_rather_than_zero() -> None:
    # "did not say" is not "said none": a caller comparing a collected count against 0 would otherwise
    # refuse every walk of an ordering whose pages omit `links.total_items`.
    client, _ = tvdb_client_for(
        fixture_response(TVDB, "seasons_types"),
        fixture_response(TVDB, "series_81797_episodes_unknown_type"),
    )

    result = await client.all_series_episodes(ONE_PIECE, "absolute")

    assert result.reported is None


# --- the reference values ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("season_type", "expected"),
    [("absolute", (1, 62, 62)), ("dvd", (2, 1, 62)), ("official", (5, 2, 62))],
)
async def test_laboon_is_absolute_62_dvd_s2e1_official_s5e2(season_type: str, expected: tuple[int, int, int]) -> None:
    """Reference value, `docs/status.md` section 2.9. No arithmetic maps one of these onto another."""
    client, _ = tvdb_client_for(
        fixture_response(TVDB, "seasons_types"),
        fixture_response(TVDB, f"series_81797_episodes_{season_type}_eng_page0"),
    )

    page = await client.series_episodes(ONE_PIECE, season_type)

    episode = _laboon(page.episodes)
    assert (episode.season_number, episode.number, episode.absolute_number) == expected


async def test_names_are_requested_through_the_eng_variant() -> None:
    """TheTVDB answers in the original language by default, which for anime is Japanese."""
    client, responder = tvdb_client_for(
        fixture_response(TVDB, "seasons_types"),
        fixture_response(TVDB, "series_81797_episodes_absolute_eng_page0"),
        fixture_response(TVDB, "series_81797_translations_eng"),
    )

    page = await client.series_episodes(ONE_PIECE, "absolute")
    translation = await client.series_translation(ONE_PIECE)

    named = [url for url in responder.requested if "/episodes/" in url or "/translations/" in url]
    assert named == [
        f"{TVDB_API_BASE_URL}/series/81797/episodes/absolute/eng?page=0",
        f"{TVDB_API_BASE_URL}/series/81797/translations/eng",
    ]
    assert all(httpx.URL(url).path.endswith("/eng") for url in named)
    assert translation.name == "One Piece"
    assert page.episodes[0].name is not None


async def test_a_missing_translation_is_a_typed_not_found() -> None:
    client, _ = tvdb_client_for(httpx.Response(404, json={"status": "failure"}))

    with pytest.raises(ProviderNotFoundError):
        await client.series_translation(ONE_PIECE)


# --- pagination ----------------------------------------------------------------------------------------


async def test_pagination_follows_links_next_to_the_last_page_and_logs_the_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """934 episodes at 500 a page: page 1 is the real last page and carries `links.next: null`."""
    client, responder = tvdb_client_for(
        fixture_response(TVDB, "seasons_types"),
        fixture_response(TVDB, "series_81797_episodes_dvd_eng_page0"),
        fixture_response(TVDB, "series_81797_episodes_dvd_eng_page1"),
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        result = await client.all_series_episodes(ONE_PIECE, "dvd")

    assert result.pages == 2
    assert len(result.episodes) == 934
    assert responder.requested[-2:] == [
        f"{TVDB_API_BASE_URL}/series/81797/episodes/dvd/eng?page=0",
        f"{TVDB_API_BASE_URL}/series/81797/episodes/dvd/eng?page=1",
    ]
    assert any("pages=2" in message and "total=934" in message for message in _messages(caplog))


async def test_a_next_link_that_loops_back_stops_rather_than_paging_forever() -> None:
    """A page whose `next` is one already walked ends the walk: an upstream loop is a hang, not a dataset."""
    client, responder = tvdb_client_for(
        fixture_response(TVDB, "seasons_types"),
        fixture_response(TVDB, "series_81797_episodes_absolute_eng_page0"),
    )

    result = await client.all_series_episodes(ONE_PIECE, "absolute")

    assert result.pages == 2
    assert len(responder.requested) == 4  # login, the season types, and the two pages it was willing to walk.


async def test_a_next_link_off_the_provider_base_is_refused() -> None:
    client, _ = tvdb_client_for(
        fixture_response(TVDB, "seasons_types"),
        httpx.Response(
            200,
            json={"data": {"episodes": [{"id": 1}]}, "links": {"next": "https://evil.example/v4/x?page=1"}},
        ),
    )

    with pytest.raises(OutboundUrlError):
        await client.all_series_episodes(ONE_PIECE, "absolute")


# --- the cursor ---------------------------------------------------------------------------------------


def _keys(cache: RecordingResponseCache) -> list[str]:
    """Every cursor a run wrote, in the `source/resource_type/resource_key` shape `sync_state` is keyed by."""
    return [f"{stored.source}/{stored.resource_type}/{stored.resource_key}" for stored in cache.stored]


async def test_a_successful_call_records_the_cursor_its_ingest_will_read() -> None:
    """`sync_state` is how a stale projection becomes a question someone can answer, so every 200 writes one."""
    cache = RecordingResponseCache()
    client, _ = tvdb_client_for(
        fixture_response(TVDB, "seasons_types"),
        fixture_response(TVDB, "series_81797_episodes_dvd_eng_page0"),
        fixture_response(TVDB, "series_81797_episodes_dvd_eng_page1"),
        fixture_response(TVDB, "updates_episodes"),
        cache=cache,
    )

    await client.season_types()
    await client.all_series_episodes(ONE_PIECE, "dvd")
    await client.updates(NOW)

    assert _keys(cache) == [
        "tvdb/tvdb_season_types/all",
        "tvdb/tvdb_episodes/81797/dvd/0",
        "tvdb/tvdb_episodes/81797/dvd/1",
        "tvdb/tvdb_updates/episodes",
    ]
    # The digest is over the bytes that really arrived, so an unchanged body is recognisable next pass.
    assert cache.stored[0].payload_digest == payload_digest(fixture_bytes(TVDB, "seasons_types"))
    assert cache.stored[-1].payload_digest == payload_digest(fixture_bytes(TVDB, "updates_episodes"))
    # TheTVDB sends no ETag, so the cursor's conditional fields are honestly empty rather than invented.
    assert all(stored.etag is None and stored.last_modified is None for stored in cache.stored)


async def test_the_login_writes_no_cursor_because_it_is_not_a_resource() -> None:
    cache = RecordingResponseCache()
    client, _ = tvdb_client_for(fixture_response(TVDB, "seasons_types"), cache=cache)

    await client.login()

    assert (cache.stored, cache.lookups) == ([], [])


async def test_an_unchanged_body_is_still_stored_and_logs_not_modified(caplog: pytest.LogCaptureFixture) -> None:
    """Where this diverges from TMDB, deliberately: TheTVDB has no six-month ceiling, so the only question a
    cursor answers is *when did this last sync successfully* - and skipping the write on an equal digest would
    let that answer go stale while the ingest was in fact healthy."""
    cache = RecordingResponseCache(
        primed=CachedResponse(
            etag=None,
            last_modified=None,
            payload_digest=payload_digest(fixture_bytes(TVDB, "seasons_types")),
            last_success_at=None,
        )
    )
    client, _ = tvdb_client_for(fixture_response(TVDB, "seasons_types"), cache=cache)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await client.season_types()

    assert _keys(cache) == ["tvdb/tvdb_season_types/all"]
    assert any("outcome=not-modified" in message for message in _messages(caplog))


async def test_a_changed_body_is_stored_and_logs_fresh(caplog: pytest.LogCaptureFixture) -> None:
    cache = RecordingResponseCache(
        primed=CachedResponse(
            etag=None, last_modified=None, payload_digest="a-digest-from-some-older-body", last_success_at=None
        )
    )
    client, _ = tvdb_client_for(fixture_response(TVDB, "seasons_types"), cache=cache)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await client.season_types()

    assert len(cache.stored) == 1
    assert any("outcome=fresh" in message and "/seasons/types" in message for message in _messages(caplog))


# --- updates -------------------------------------------------------------------------------------------


async def test_a_truncated_updates_window_is_refused_rather_than_read_as_a_quiet_one() -> None:
    """A second page means the caller would act on part of a window, which reads exactly like a calm one."""
    truncated = fixture_json(TVDB, "updates_episodes")
    links = truncated["links"]
    assert isinstance(links, dict)
    links["next"] = f"{TVDB_API_BASE_URL}/updates?since=1&type=episodes&page=1"
    cache = RecordingResponseCache()
    client, _ = tvdb_client_for(httpx.Response(200, json=truncated), cache=cache)

    with pytest.raises(ProviderUnavailableError) as refusal:
        await client.updates(NOW)

    assert "one page" in str(refusal.value)
    # The cursor records the failure and NOT a success: a stored `last_success_at` here would claim the
    # updates window was current while the caller received nothing.
    assert cache.stored == []
    assert cache.failures[0].resource_type == "tvdb_updates"


async def test_a_complete_updates_window_logs_what_it_collected_against_what_was_claimed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = tvdb_client_for(fixture_response(TVDB, "updates_episodes"))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        updates = await client.updates(NOW)

    reported = fixture_json(TVDB, "updates_episodes")["links"]
    assert isinstance(reported, dict)
    assert any(
        f"pages=1 total={len(updates)} reported={reported['total_items']}" in message for message in _messages(caplog)
    )


async def test_updates_reads_the_window_as_unix_seconds() -> None:
    client, responder = tvdb_client_for(fixture_response(TVDB, "updates_episodes"))

    updates = await client.updates(NOW)

    since = int(NOW.timestamp())
    assert responder.requested[-1] == f"{TVDB_API_BASE_URL}/updates?since={since}&type=episodes&page=0"
    recorded = fixture_json(TVDB, "updates_episodes")["data"]
    assert isinstance(recorded, list)
    assert len(updates) == len(recorded)
    assert all(update.entity_type == "episodes" for update in updates)
    assert all(update.record_id > 0 for update in updates)


# --- refusals ------------------------------------------------------------------------------------------


async def test_a_5xx_records_the_failure_and_raises_unavailable(caplog: pytest.LogCaptureFixture) -> None:
    cache = RecordingResponseCache()
    client, _ = tvdb_client_for(httpx.Response(503), cache=cache, clock=lambda: NOW)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        with pytest.raises(ProviderUnavailableError):
            await client.season_types()

    failure = cache.failures[0]
    assert (failure.source, failure.resource_type) == ("tvdb", "tvdb_season_types")
    assert "ProviderUnavailableError" in failure.error and "503" in failure.error
    # `failed`, never `throttled`: nothing arrived that anything could write, and a wait is not a failure.
    assert any("status=503" in message and "outcome=failed" in message for message in _messages(caplog))


async def test_a_429_raises_refused_with_retry_after() -> None:
    client, _ = tvdb_client_for(httpx.Response(429, headers={"retry-after": "7"}))

    with pytest.raises(ProviderRefusedError) as refusal:
        await client.season_types()

    assert refusal.value.retry_after == pytest.approx(7.0)


@pytest.mark.parametrize("header", [None, "Sun, 20 Sep 2026 12:00:07 GMT"], ids=["absent", "http-date"])
async def test_a_429_without_a_numeric_retry_after_still_refuses(header: str | None) -> None:
    """`Retry-After` may be a date rather than a count, and a date is not a number of seconds to wait."""
    client, _ = tvdb_client_for(httpx.Response(429, headers={} if header is None else {"retry-after": header}))

    with pytest.raises(ProviderRefusedError) as refusal:
        await client.season_types()

    assert refusal.value.retry_after is None


def _login_then_outage(request: httpx.Request) -> httpx.Response:
    """A transport that authenticates and then stops answering, which is what a mid-ingest outage looks like."""
    if request.url.path == LOGIN_PATH:
        return fixture_response(TVDB, "login")
    raise httpx.ConnectError("the upstream did not answer", request=request)


async def test_a_transport_failure_is_unavailable_and_is_recorded_against_its_cursor() -> None:
    """Built by hand rather than through `tvdb_client_for`: this one needs a transport that raises."""
    cache = RecordingResponseCache()
    client = TvdbClient(
        SecretStr(A_RECORDED_KEY),
        SecretStr(A_RECORDED_PIN),
        http=build_provider_http(TVDB_API_BASE_URL, headers={}, transport=httpx.MockTransport(_login_then_outage)),
        bucket=TokenBucket(TVDB_REQUESTS_PER_SECOND, A_BURST_NO_TEST_EXHAUSTS),
        cache=cache,
    )

    with pytest.raises(ProviderUnavailableError) as failure:
        await client.season_types()

    assert "ConnectError" in str(failure.value)
    assert cache.failures[0].resource_type == "tvdb_season_types"
    assert "ConnectError" in cache.failures[0].error


async def test_a_login_that_answers_without_a_token_is_unavailable_not_a_silent_anonymous_client() -> None:
    """A 200 carrying no token would otherwise leave the client believing it had authenticated."""
    client, responder = tvdb_client_for(httpx.Response(200, json={"status": "success", "data": {}}), login=False)

    with pytest.raises(ProviderUnavailableError) as failure:
        await client.login()

    assert "TvdbLogin" in str(failure.value)
    assert client.token_issued_at is None
    assert len(responder.requested) == 1


async def test_a_body_this_client_cannot_read_is_unavailable_and_says_nothing_about_the_body() -> None:
    cache = RecordingResponseCache()
    client, _ = tvdb_client_for(httpx.Response(200, json={"data": "not a list"}), cache=cache)

    with pytest.raises(ProviderUnavailableError) as failure:
        await client.season_types()

    assert "not a list" not in str(failure.value)
    assert "not a list" not in cache.failures[0].error


async def test_a_redirect_is_reported_rather_than_followed() -> None:
    client, responder = tvdb_client_for(httpx.Response(302, headers={"location": "https://evil.example/"}))

    with pytest.raises(ProviderUnavailableError):
        await client.season_types()

    assert len(responder.requested) == 2


# --- the budget ----------------------------------------------------------------------------------------


async def test_every_call_including_the_login_passes_through_the_bucket() -> None:
    bucket = CountingBucket(TVDB_REQUESTS_PER_SECOND)
    client, responder = tvdb_client_for(
        fixture_response(TVDB, "seasons_types"),
        fixture_response(TVDB, "series_81797_translations_eng"),
        bucket=bucket,
    )

    await client.season_types()
    await client.series_translation(ONE_PIECE)

    assert bucket.acquires == len(responder.requested) == 3


# --- the shape of the class -----------------------------------------------------------------------------


def test_no_series_search_method_exists() -> None:
    """The series id arrives from TMDB `external_ids`; TheTVDB's own search ranked the anime eighth."""
    assert not hasattr(TvdbClient, "search")
    assert not any("search" in name for name in dir(TvdbClient))


@pytest.mark.parametrize("name", EVERY_RECORDED_FIXTURE)
def test_every_recorded_fixture_is_readable_and_carries_no_credential(name: str) -> None:
    """A recorded body is data. The recorder redacts the token; this is the standing proof it stayed redacted."""
    body = fixture_response(TVDB, name).content.decode()

    assert fixture_json(TVDB, name)
    assert "Bearer " not in body
    assert "/search" not in body
    # Every TheTVDB bearer token is a JWT, and every JWT's compact form starts `eyJ`.
    assert "eyJ" not in body


def test_the_login_fixture_carries_no_real_token() -> None:
    data = fixture_json(TVDB, "login")["data"]

    assert isinstance(data, dict)
    assert data["token"] == RECORDED_TOKEN


# --- the composition seam ------------------------------------------------------------------------------


def _built(api_key: str | None, pin: str | None) -> TvdbClient:
    """A client built the way T19 will build it: the credentials from settings, everything else handed in."""
    return build_tvdb_client(
        Settings(
            _env_file=None,
            tvdb_api_key=None if api_key is None else SecretStr(api_key),
            tvdb_pin=None if pin is None else SecretStr(pin),
        ),
        http=build_provider_http(
            TVDB_API_BASE_URL, headers={}, transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
        bucket=TokenBucket(TVDB_REQUESTS_PER_SECOND, A_BURST_NO_TEST_EXHAUSTS),
        cache=RecordingResponseCache(),
    )


@pytest.mark.parametrize(
    ("api_key", "pin", "configured"),
    [(A_RECORDED_KEY, A_RECORDED_PIN, True), (A_RECORDED_KEY, None, False), (None, None, False)],
)
def test_the_builder_takes_both_credentials_from_settings(
    api_key: str | None, pin: str | None, configured: bool
) -> None:
    assert _built(api_key, pin).configured is configured


# --- the credential must not reach an exception through an upstream error's TEXT --------------------


def _a_login_handing_back(token: str) -> httpx.Response:
    """The login answer, with a bearer this client will then have to put in a header."""
    return httpx.Response(200, json={"status": "success", "data": {"token": token}})


async def test_a_bearer_carrying_a_newline_never_reaches_the_raised_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The api key travels in a JSON body, which escapes a newline; the BEARER travels in a header, and
    h11 quotes the whole header value into its `LocalProtocolError` - an `httpx.HTTPError`. Interpolating
    that error, which this client used to do, carried the bearer into the message and the cursor."""
    responder = H11RejectingResponder(
        _a_login_handing_back(A_CREDENTIAL_WITH_A_NEWLINE), fixture_response(TVDB, "seasons_types")
    )
    client, _ = tvdb_client_for(login=False, responder=responder)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME), pytest.raises(ProviderUnavailableError) as raised:
        await client.season_types()

    assert "cret-newline-credential" not in str(raised.value)
    assert all("cret-newline-credential" not in message for message in _messages(caplog))
    # Asserting the CAUSE does carry it proves this reproduces the real leak, not a silent transport.
    assert isinstance(raised.value.__cause__, httpx.HTTPError)
    assert "cret-newline-credential" in str(raised.value.__cause__)


async def test_a_bearer_carrying_a_newline_reaches_no_header_but_the_authorization_one() -> None:
    responder = H11RejectingResponder(
        _a_login_handing_back(A_CREDENTIAL_WITH_A_NEWLINE), fixture_response(TVDB, "seasons_types")
    )
    client, _ = tvdb_client_for(login=False, responder=responder)

    with pytest.raises(ProviderUnavailableError):
        await client.season_types()

    # The login went through (no Authorization header on it); the call after it is the one that failed.
    failed = responder.requests[-1]
    others = {name: value for name, value in failed.headers.items() if name.lower() != "authorization"}
    assert all("cret-newline-credential" not in value for value in others.values())
    assert "cret-newline-credential" not in str(failed.url)
