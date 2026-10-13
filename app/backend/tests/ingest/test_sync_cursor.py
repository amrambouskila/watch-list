"""The `sync_state` cursor: conditional-request state, the backoff schedule, and the six-month term.

The pure half runs on any workstation; only the four SQL statements need the service container, and
those tests skip loudly through `db_session` when nothing is listening (CLAUDE.md section 16.4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clients.response_cache import CachedResponse, ResponseCache
from tv_watchlist.constants import (
    MAX_LAST_ERROR_CHARS,
    PROVIDER_BACKOFF_BASE_SECONDS,
    PROVIDER_BACKOFF_MAX_SECONDS,
    TMDB_CACHE_CEILING_DAYS,
)
from tv_watchlist.data.enums import ExternalSource, SyncResourceType
from tv_watchlist.data.models import SyncState
from tv_watchlist.ingest.sync_cursor import (
    _CURSOR_COLUMNS,
    PostgresResponseCache,
    _cursor_key,
    _matching,
    _redact,
    attempt_is_due,
    backoff_delay,
    success_past_ceiling,
)

NOW: datetime = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
TMDB: str = ExternalSource.TMDB.value
TVDB: str = ExternalSource.TVDB.value
A_TV_RESOURCE: str = SyncResourceType.TMDB_TV.value
AN_EPISODES_RESOURCE: str = SyncResourceType.TVDB_EPISODES.value
ONE_PIECE: str = "37854"
A_DIGEST: str = "d" * 64


def a_cache(session: AsyncSession, *, at: datetime = NOW) -> PostgresResponseCache:
    """One cache with the clock nailed down, so every stamp a test asserts on is arithmetic, not wall time."""
    return PostgresResponseCache(session, clock=lambda: at)


async def _row(session: AsyncSession, resource_key: str = ONE_PIECE) -> SyncState:
    """The cursor as the database now holds it.

    `populate_existing` because the cache writes through Core statements the identity map knows nothing
    about: without it a second read of the same row would hand back the attributes of the first.
    """
    statement = (
        select(SyncState).where(SyncState.resource_key == resource_key).execution_options(populate_existing=True)
    )
    return (await session.scalars(statement)).one()


# --- the pure half: no database, no provider, no clock ----------------------------------------


@pytest.mark.parametrize(
    ("consecutive_failures", "seconds"),
    [(1, 60.0), (2, 120.0), (3, 240.0), (4, 480.0)],
)
def test_the_backoff_doubles_from_one_minute(consecutive_failures: int, seconds: float) -> None:
    assert backoff_delay(consecutive_failures) == timedelta(seconds=seconds)


def test_the_backoff_caps_at_one_day_however_long_the_outage_runs() -> None:
    assert backoff_delay(20) == timedelta(seconds=PROVIDER_BACKOFF_MAX_SECONDS)
    # A count no schedule should ever reach must still be arithmetic rather than a 2**n integer.
    assert backoff_delay(10_000) == timedelta(seconds=PROVIDER_BACKOFF_MAX_SECONDS)


def test_the_first_backoff_is_the_base_wait() -> None:
    assert backoff_delay(0) == timedelta(seconds=PROVIDER_BACKOFF_BASE_SECONDS)


@pytest.mark.parametrize(
    ("next_attempt_at", "due"),
    [(None, True), (NOW - timedelta(seconds=1), True), (NOW, True), (NOW + timedelta(seconds=1), False)],
)
def test_a_cursor_is_due_once_its_stamp_has_arrived(next_attempt_at: datetime | None, due: bool) -> None:
    assert attempt_is_due(next_attempt_at, NOW) is due


@pytest.mark.parametrize(
    ("age_days", "past"),
    [(171, True), (170, True), (169, False), (0, False)],
)
def test_the_ceiling_is_read_against_the_last_success(age_days: int, past: bool) -> None:
    last_success_at = NOW - timedelta(days=age_days)
    assert success_past_ceiling(last_success_at, NOW, TMDB_CACHE_CEILING_DAYS) is past


def test_a_cursor_that_never_succeeded_has_cached_nothing_to_be_past_a_term() -> None:
    assert success_past_ceiling(None, NOW, TMDB_CACHE_CEILING_DAYS) is False


def test_redaction_removes_a_bearer_token_and_keeps_the_rest_of_the_message() -> None:
    redacted = _redact("ProviderRefusedError: TMDB refused Authorization: Bearer sk-live-abc123")
    assert "sk-live-abc123" not in redacted
    assert redacted == "ProviderRefusedError: TMDB refused Authorization: Bearer [redacted]"


def test_redaction_is_case_insensitive_about_the_scheme() -> None:
    assert "t0ken" not in _redact("sent bearer t0ken upstream")


def test_redaction_cannot_forge_a_second_log_record() -> None:
    assert _redact("connect timeout\r\nprovider_call outcome=fresh") == "connect timeoutprovider_call outcome=fresh"


def test_redaction_removes_every_control_character_not_only_the_newlines() -> None:
    """`last_error` is read back by a person and by a log; a C0 byte belongs in neither."""
    assert _redact("connect\x00 timeout\x07\x1b[31m") == "connect timeout[31m"


def test_a_message_too_long_for_a_cursor_to_carry_is_clipped() -> None:
    """The column is `Text`: an upstream answering a megabyte of HTML must not store a megabyte of it."""
    assert len(_redact("x" * 3000)) == MAX_LAST_ERROR_CHARS


def test_clipping_happens_after_redaction_so_length_can_never_save_a_token() -> None:
    clipped = _redact("Bearer sk-live-abc123 " + "x" * 3000)
    assert len(clipped) == MAX_LAST_ERROR_CHARS
    assert "sk-live-abc123" not in clipped
    assert clipped.startswith("Bearer [redacted] ")


def test_a_message_carrying_no_credential_is_stored_as_written() -> None:
    assert _redact("ProviderUnavailableError: TMDB could not be reached (ConnectTimeout: )") == (
        "ProviderUnavailableError: TMDB could not be reached (ConnectTimeout: )"
    )


def test_the_strings_the_clients_speak_convert_to_the_columns_vocabulary() -> None:
    assert _cursor_key(TMDB, A_TV_RESOURCE) == (ExternalSource.TMDB, SyncResourceType.TMDB_TV)


@pytest.mark.parametrize(
    ("source", "resource_type"),
    [("netflix", A_TV_RESOURCE), (TMDB, "tmdb_trailers")],
)
def test_a_vocabulary_this_schema_has_never_seen_is_refused_here(source: str, resource_type: str) -> None:
    with pytest.raises(ValueError, match="not a valid"):
        _cursor_key(source, resource_type)


def test_every_read_and_write_addresses_the_one_unique_cursor_key() -> None:
    """`uq(source, resource_type, resource_key)`: the reads select on it and the upserts infer against it."""
    assert [column.key for column in _CURSOR_COLUMNS] == ["source", "resource_type", "resource_key"]
    assert str(_matching((ExternalSource.TMDB, SyncResourceType.TMDB_TV), ONE_PIECE)) == (
        "sync_state.source = :source_1 AND sync_state.resource_type = :resource_type_1 "
        "AND sync_state.resource_key = :resource_key_1"
    )


def test_the_postgres_cache_satisfies_the_seam_the_clients_read_through() -> None:
    # `isinstance` against a runtime_checkable Protocol checks method presence only; the database tests
    # below call all three through.
    assert isinstance(PostgresResponseCache(AsyncSession()), ResponseCache)


# --- the database half: a real Postgres, rolled back after every test -------------------------


async def test_lookup_returns_none_for_an_unseen_resource(db_session: AsyncSession) -> None:
    assert await a_cache(db_session).lookup(TMDB, A_TV_RESOURCE, ONE_PIECE) is None


async def test_store_upserts_on_the_unique_cursor_key_rather_than_duplicating(db_session: AsyncSession) -> None:
    cache = a_cache(db_session)
    await cache.store(TMDB, A_TV_RESOURCE, ONE_PIECE, etag='W/"first"', last_modified=None, payload_digest=A_DIGEST)
    await cache.store(TMDB, A_TV_RESOURCE, ONE_PIECE, etag='W/"second"', last_modified=None, payload_digest="e" * 64)

    rows = await db_session.scalar(select(func.count()).select_from(SyncState))
    assert rows == 1
    cached = await cache.lookup(TMDB, A_TV_RESOURCE, ONE_PIECE)
    assert cached == CachedResponse(etag='W/"second"', last_modified=None, payload_digest="e" * 64, last_success_at=NOW)


async def test_store_records_etag_last_modified_digest_and_resets_failures(db_session: AsyncSession) -> None:
    cache = a_cache(db_session)
    await cache.record_failure(TMDB, A_TV_RESOURCE, ONE_PIECE, "connect timeout")
    await cache.record_failure(TMDB, A_TV_RESOURCE, ONE_PIECE, "connect timeout")

    await cache.store(
        TMDB,
        A_TV_RESOURCE,
        ONE_PIECE,
        etag='W/"abc"',
        last_modified="Mon, 15 Sep 2026 00:00:00 GMT",
        payload_digest=A_DIGEST,
    )

    row = await _row(db_session)
    assert (row.etag, row.last_modified, row.payload_digest) == ('W/"abc"', "Mon, 15 Sep 2026 00:00:00 GMT", A_DIGEST)
    assert row.consecutive_failures == 0
    assert row.next_attempt_at is None
    assert row.last_error is None
    assert row.last_success_at == NOW
    assert row.last_attempt_at == NOW


async def test_a_stored_cursor_always_carries_the_success_stamp_its_validators_belong_to(
    db_session: AsyncSession,
) -> None:
    """The client reads the ceiling off `last_success_at`; a validator without one would cache forever."""
    cache = a_cache(db_session)
    await cache.store(TMDB, A_TV_RESOURCE, ONE_PIECE, etag=None, last_modified=None, payload_digest=A_DIGEST)

    cached = await cache.lookup(TMDB, A_TV_RESOURCE, ONE_PIECE)
    assert cached is not None
    assert cached.last_success_at == NOW


async def test_record_failure_backs_off_exponentially_and_caps_at_a_day(db_session: AsyncSession) -> None:
    cache = a_cache(db_session)
    for attempt, seconds in ((1, 60.0), (2, 120.0), (3, 240.0), (4, 480.0)):
        await cache.record_failure(TMDB, A_TV_RESOURCE, ONE_PIECE, "connect timeout")
        row = await _row(db_session)
        assert row.consecutive_failures == attempt
        assert row.next_attempt_at is not None
        assert row.next_attempt_at - NOW == timedelta(seconds=seconds)

    for _ in range(5, 21):
        await cache.record_failure(TMDB, A_TV_RESOURCE, ONE_PIECE, "connect timeout")
    row = await _row(db_session)
    assert row.consecutive_failures == 20
    assert row.next_attempt_at is not None
    assert row.next_attempt_at - NOW == timedelta(seconds=PROVIDER_BACKOFF_MAX_SECONDS)


async def test_is_due_respects_next_attempt_at(db_session: AsyncSession) -> None:
    await a_cache(db_session).record_failure(TMDB, A_TV_RESOURCE, ONE_PIECE, "connect timeout")
    stamp = NOW + timedelta(seconds=PROVIDER_BACKOFF_BASE_SECONDS)

    assert await a_cache(db_session, at=stamp - timedelta(seconds=1)).is_due(TMDB, A_TV_RESOURCE, ONE_PIECE) is False
    assert await a_cache(db_session, at=stamp).is_due(TMDB, A_TV_RESOURCE, ONE_PIECE) is True


async def test_an_unrecorded_cursor_is_due_because_nothing_has_asked_it_to_wait(db_session: AsyncSession) -> None:
    assert await a_cache(db_session).is_due(TMDB, A_TV_RESOURCE, ONE_PIECE) is True


async def test_a_stored_cursor_is_due_again_because_a_success_clears_the_backoff(db_session: AsyncSession) -> None:
    cache = a_cache(db_session)
    await cache.record_failure(TMDB, A_TV_RESOURCE, ONE_PIECE, "connect timeout")
    await cache.store(TMDB, A_TV_RESOURCE, ONE_PIECE, etag=None, last_modified=None, payload_digest=A_DIGEST)

    assert await cache.is_due(TMDB, A_TV_RESOURCE, ONE_PIECE) is True


async def test_the_ceiling_flags_a_row_older_than_170_days_and_not_a_younger_one(db_session: AsyncSession) -> None:
    stale, fresh = "stale", "fresh"
    await a_cache(db_session, at=NOW - timedelta(days=171)).store(
        TMDB, A_TV_RESOURCE, stale, etag=None, last_modified=None, payload_digest=A_DIGEST
    )
    await a_cache(db_session, at=NOW - timedelta(days=169)).store(
        TMDB, A_TV_RESOURCE, fresh, etag=None, last_modified=None, payload_digest=A_DIGEST
    )

    cache = a_cache(db_session)
    assert await cache.past_ceiling(TMDB, A_TV_RESOURCE, stale) is True
    assert await cache.past_ceiling(TMDB, A_TV_RESOURCE, fresh) is False


async def test_a_cursor_nobody_has_fetched_is_not_past_the_caching_term(db_session: AsyncSession) -> None:
    assert await a_cache(db_session).past_ceiling(TMDB, A_TV_RESOURCE, ONE_PIECE) is False


async def test_due_for_refresh_lists_only_that_source_oldest_first(db_session: AsyncSession) -> None:
    oldest, older, young = "oldest", "older", "young"
    for key, age_days in ((oldest, 400), (older, 200), (young, 3)):
        await a_cache(db_session, at=NOW - timedelta(days=age_days)).store(
            TMDB, A_TV_RESOURCE, key, etag=None, last_modified=None, payload_digest=A_DIGEST
        )
    await a_cache(db_session, at=NOW - timedelta(days=300)).store(
        TVDB, AN_EPISODES_RESOURCE, "tvdb-one", etag=None, last_modified=None, payload_digest=A_DIGEST
    )

    due = await a_cache(db_session).due_for_refresh(TMDB)

    assert [row.resource_key for row in due] == [oldest, older]


async def test_due_for_refresh_stops_at_the_limit_it_was_given(db_session: AsyncSession) -> None:
    for key, age_days in (("oldest", 400), ("older", 200)):
        await a_cache(db_session, at=NOW - timedelta(days=age_days)).store(
            TMDB, A_TV_RESOURCE, key, etag=None, last_modified=None, payload_digest=A_DIGEST
        )

    due = await a_cache(db_session).due_for_refresh(TMDB, limit=1)

    assert [row.resource_key for row in due] == ["oldest"]


async def test_an_unknown_source_string_is_refused_at_the_boundary(db_session: AsyncSession) -> None:
    cache = a_cache(db_session)
    with pytest.raises(ValueError, match="not a valid ExternalSource"):
        await cache.store("netflix", A_TV_RESOURCE, ONE_PIECE, etag=None, last_modified=None, payload_digest=A_DIGEST)
    with pytest.raises(ValueError, match="not a valid ExternalSource"):
        await cache.due_for_refresh("netflix")

    assert await db_session.scalar(select(func.count()).select_from(SyncState)) == 0


async def test_last_error_never_carries_an_authorization_value(db_session: AsyncSession) -> None:
    await a_cache(db_session).record_failure(
        TMDB, A_TV_RESOURCE, ONE_PIECE, "ProviderRefusedError: TMDB refused Bearer sk-live-abc123 with 401"
    )

    row = await _row(db_session)
    assert row.last_error is not None
    assert "sk-live-abc123" not in row.last_error
    assert row.last_error == "ProviderRefusedError: TMDB refused Bearer [redacted] with 401"
