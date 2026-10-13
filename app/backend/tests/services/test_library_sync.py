"""The library sync: what one walk of the owner's Jellyfin writes, and everything it refuses to write.

No socket is opened here. The bodies are the hand-authored ones under `tests/fixtures/jellyfin/`, shaped
from 12.1's OpenAPI document (that directory's README says why, and what T54's gate still confirms live),
replayed through `httpx.MockTransport`. The database is real: this is a reconciler, and a mocked one would
only prove that the mock agrees with itself.

The assertion this file exists for is the master plan's 10.3 line: **series are matched by provider id
only**. A fixture whose Jellyfin name differs from the title's, and one whose name matches while carrying
no TMDB id, are both here - and the second must come out with `tmdb_id` NULL rather than a plausible guess.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from jellyfin_library import (
    CURSOR_PARAM,
    EPISODES,
    EPISODES_SEGMENT,
    EVERY_SERIES_ID,
    ITEMS_PATH,
    LIBRARY_ROWS,
    MOVIES,
    ONE_PIECE_SERIES_ID,
    SCAN_TYPES,
    SERIES,
    TMDB_FILTER_PARAM,
    TYPES_PARAM,
    JellyfinLibrary,
    client_for,
    fixture_library,
    items_of,
    library_items,
    page,
)
from provider_fixtures import A_JELLYFIN_BASE_URL, A_RECORDED_JELLYFIN_KEY
from statement_support import counted_statements
from tv_watchlist.clients.jellyfin_client import JellyfinClient, build_jellyfin_http
from tv_watchlist.constants import JELLYFIN_EPISODE_TYPE, JELLYFIN_ITEM_FIELDS, MAX_JELLYFIN_ID_LENGTH
from tv_watchlist.data.enums import JellyfinItemKind, MediaType
from tv_watchlist.data.errors import JellyfinUnavailableError
from tv_watchlist.data.models import JellyfinItem, Title
from tv_watchlist.services import library_sync

IRON_MAN_ID: Final[str] = "0a1b2c3d4e5f6071829304a5b6c7d8e9"
SPIDER_MAN_ID: Final[str] = "2c3d4e5f60718293a4b5c6d7e8f90123"
A_MULTI_EPISODE_FILE_ID: Final[str] = "5f60718293a4b5c6d7e8f90123456789"

IRON_MAN_TMDB_ID: Final[int] = 1726
ONE_PIECE_TMDB_ID: Final[int] = 37854
# The TMDB id of the real Spider-Man (2002). The fixture's file carries no TMDB id at all, so a row
# claiming this number could only have come from matching on the name - which is what must never happen.
SPIDER_MAN_TMDB_ID: Final[int] = 557


A_FIRST_PASS: Final[datetime] = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
A_SECOND_PASS: Final[datetime] = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)
A_CALLER_HELD_CURSOR: Final[datetime] = datetime(2026, 9, 20, 12, 30, tzinfo=UTC)
AN_EARLIER_STAMP: Final[datetime] = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
A_LATER_STAMP: Final[datetime] = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)

A_NEW_EPISODE_FILE_ID: Final[str] = "60718293a4b5c6d7e8f9012345678901"
# `Type` on the wire, beside the enum member the sync maps it to.
EPISODE_TYPE: Final[str] = JELLYFIN_EPISODE_TYPE
LOGGER_NAME: Final[str] = "tv_watchlist.services.library_sync"


def _a_new_episode_file() -> dict[str, object]:
    """One episode file that arrived after the last pass, on a series whose own record did not change."""
    return {
        "Id": A_NEW_EPISODE_FILE_ID,
        "Name": "The Beginning of the Legend",
        "Path": "/media/anime/One Piece/Season 01/One Piece - S01E04 - The Beginning of the Legend.mkv",
        "RunTimeTicks": 14400000000,
        "IndexNumber": 4,
        "ParentIndexNumber": 1,
        "SeriesId": ONE_PIECE_SERIES_ID,
        "Type": EPISODE_TYPE,
        "DateLastSaved": "2026-09-21T10:00:00Z",
    }


def _sync_record(caplog: pytest.LogCaptureFixture) -> str:
    """The one summary record a pass emits, whichever way the pass ended."""
    messages = (record.getMessage() for record in caplog.records)
    return next(message for message in messages if message.startswith("library_sync "))


async def _rows(session: AsyncSession) -> dict[str, JellyfinItem]:
    return {row.jellyfin_id: row for row in (await session.scalars(select(JellyfinItem)))}


def _unreachable_client() -> tuple[JellyfinClient, list[httpx.Request]]:
    """A client whose every request dies in the transport, and the record of how many were attempted."""
    attempts: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectError("no route to host", request=request)

    http = build_jellyfin_http(A_JELLYFIN_BASE_URL, transport=httpx.MockTransport(refuse))
    return JellyfinClient(A_JELLYFIN_BASE_URL, SecretStr(A_RECORDED_JELLYFIN_KEY), http=http), attempts


async def test_a_first_sync_indexes_movies_series_and_episodes(db_session: AsyncSession) -> None:
    responder = fixture_library()

    result = await library_sync.sync_library(db_session, client_for(responder), clock=lambda: A_FIRST_PASS)

    assert (result.seen, result.added, result.updated, result.removed) == (LIBRARY_ROWS, LIBRARY_ROWS, 0, 0)
    assert result.incremental is False
    assert result.synced_at == A_FIRST_PASS
    rows = await _rows(db_session)
    assert len(rows) == LIBRARY_ROWS
    kinds = [row.kind for row in rows.values()]
    assert kinds.count(JellyfinItemKind.MOVIE) == MOVIES
    assert kinds.count(JellyfinItemKind.SERIES) == SERIES
    assert kinds.count(JellyfinItemKind.EPISODE) == EPISODES


async def test_the_scan_asks_the_reconciled_question(db_session: AsyncSession) -> None:
    """Movies and series from the paged `/Items` walk; episodes from `/Shows/{id}/Episodes` per series.

    Both halves of the plan were right about one of them, and this is the assertion that keeps them
    together: an episode almost never carries its own TMDB id, so `hasTmdbId=true` would index none of
    them, and there is no `?tmdbId=` filter to ask the other way round.
    """
    responder = fixture_library()

    await library_sync.sync_library(db_session, client_for(responder), clock=lambda: A_FIRST_PASS)

    scan = responder.requests[0].url
    assert scan.path == ITEMS_PATH
    assert scan.params[TYPES_PARAM] == SCAN_TYPES
    assert scan.params[TMDB_FILTER_PARAM] == "true"
    assert scan.params["recursive"] == "true"
    assert scan.params["fields"] == JELLYFIN_ITEM_FIELDS
    # A first pass has no cursor to be incremental from, so the filter is off the URL entirely.
    assert CURSOR_PARAM not in scan.params
    # One show call per series the scan returned, and no more.
    assert responder.paths()[1:] == [f"/Shows/{series}/{EPISODES_SEGMENT}" for series in EVERY_SERIES_ID]


async def test_the_tmdb_id_comes_from_provider_ids_and_the_ticks_become_whole_seconds(
    db_session: AsyncSession,
) -> None:
    await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_FIRST_PASS)

    iron_man = (await _rows(db_session))[IRON_MAN_ID]
    assert iron_man.tmdb_id == IRON_MAN_TMDB_ID
    # 75_600_000_000 ticks of 100 ns, converted once by the DTO. There is no ticks column to hold.
    assert iron_man.run_time_seconds == 7560
    assert iron_man.path is not None and iron_man.path.endswith(".mkv")


async def test_a_multi_episode_file_keeps_jellyfins_numbers_verbatim(db_session: AsyncSession) -> None:
    """`IndexNumberEnd` non-null is one file covering a range, which satisfies several watch-list rows."""
    await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_FIRST_PASS)

    spanning = (await _rows(db_session))[A_MULTI_EPISODE_FILE_ID]
    assert (spanning.parent_index_number, spanning.index_number, spanning.index_number_end) == (1, 3, 4)
    assert spanning.series_jellyfin_id == ONE_PIECE_SERIES_ID
    assert spanning.kind is JellyfinItemKind.EPISODE


async def test_no_series_is_matched_by_title(db_session: AsyncSession) -> None:
    """The 10.3 acceptance line. A name is never compared; a file with no provider id joins to nothing."""
    db_session.add_all(
        [
            # A title whose name does NOT resemble the Jellyfin one - it still matches, by id.
            Title(media_type=MediaType.TV, tmdb_id=ONE_PIECE_TMDB_ID, name="ワンピース", match_key="one piece 1999"),
            # A title whose name matches the Jellyfin one EXACTLY, and whose id must never be borrowed.
            Title(
                media_type=MediaType.MOVIE,
                tmdb_id=SPIDER_MAN_TMDB_ID,
                name="Spider-Man",
                match_key="spider man 2002",
            ),
        ]
    )
    await db_session.flush()

    await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_FIRST_PASS)

    rows = await _rows(db_session)
    assert rows[ONE_PIECE_SERIES_ID].tmdb_id == ONE_PIECE_TMDB_ID
    assert rows[SPIDER_MAN_ID].name == "Spider-Man"
    assert rows[SPIDER_MAN_ID].tmdb_id is None
    # And the sync sets nobody's pick: that is T56's write, made by a human.
    picks = (await db_session.scalars(select(Title.jellyfin_item_id))).all()
    assert set(picks) == {None}


async def test_a_second_sync_over_an_unchanged_library_writes_nothing(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_FIRST_PASS)
    stamps = {jellyfin_id: row.last_seen_at for jellyfin_id, row in (await _rows(db_session)).items()}

    with counted_statements(engine, "jellyfin_item") as statements:
        result = await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_SECOND_PASS)

    assert (result.seen, result.added, result.updated, result.removed) == (LIBRARY_ROWS, 0, 0, 0)
    # The positive control: the tap is attached and did see this pass, so the emptiness below is a fact
    # about the pass rather than about a listener that was never wired up.
    assert any(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    assert [sql for sql in statements if sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))] == []
    assert {jellyfin_id: row.last_seen_at for jellyfin_id, row in (await _rows(db_session)).items()} == stamps


async def test_a_changed_file_is_rewritten_and_counted_once(db_session: AsyncSession) -> None:
    await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_FIRST_PASS)
    renamed = library_items()
    for row in renamed:
        if row.get("Id") == IRON_MAN_ID:
            row["Name"] = "Iron Man (2008)"
    responder = JellyfinLibrary(scan=renamed, episodes={ONE_PIECE_SERIES_ID: items_of("shows_episodes_one_piece")})

    result = await library_sync.sync_library(db_session, client_for(responder), clock=lambda: A_SECOND_PASS)

    assert (result.added, result.updated, result.removed) == (0, 1, 0)
    rewritten = (await _rows(db_session))[IRON_MAN_ID]
    assert rewritten.name == "Iron Man (2008)"
    assert rewritten.last_seen_at == A_SECOND_PASS
    assert rewritten.first_seen_at == A_FIRST_PASS


async def test_a_vanished_file_is_marked_removed_not_deleted(db_session: AsyncSession) -> None:
    """`full=True`, because only a whole-library walk may conclude that a file is gone."""
    await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_FIRST_PASS)
    responder = fixture_library(without=IRON_MAN_ID)

    result = await library_sync.sync_library(db_session, client_for(responder), full=True, clock=lambda: A_SECOND_PASS)

    assert (result.seen, result.added, result.updated, result.removed) == (LIBRARY_ROWS - 1, 0, 0, 1)
    rows = await _rows(db_session)
    # Still there - `title.jellyfin_item_id` may point at it, and the owner's pick outlives a moved file.
    assert len(rows) == LIBRARY_ROWS
    assert rows[IRON_MAN_ID].removed_at == A_SECOND_PASS


async def test_an_incremental_pass_never_marks_anything_removed(db_session: AsyncSession) -> None:
    """Absence from a walk that asked only for what changed proves nothing whatsoever."""
    await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_FIRST_PASS)

    result = await library_sync.sync_library(db_session, client_for(JellyfinLibrary()), clock=lambda: A_SECOND_PASS)

    assert result.incremental is True
    assert (result.seen, result.removed) == (0, 0)
    assert all(row.removed_at is None for row in (await _rows(db_session)).values())


async def test_a_title_whose_pick_is_already_set_keeps_it_through_a_removal(db_session: AsyncSession) -> None:
    await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_FIRST_PASS)
    picked = (await _rows(db_session))[IRON_MAN_ID]
    title = Title(
        media_type=MediaType.MOVIE,
        tmdb_id=IRON_MAN_TMDB_ID,
        name="Iron Man",
        match_key="iron man 2008",
        jellyfin_item_id=picked.id,
    )
    db_session.add(title)
    await db_session.flush()

    await library_sync.sync_library(
        db_session, client_for(fixture_library(without=IRON_MAN_ID)), full=True, clock=lambda: A_SECOND_PASS
    )

    # Read back from Postgres rather than off the instance: the identity map would answer with the value
    # this test assigned however the database had answered.
    stored = (await db_session.execute(select(Title.jellyfin_item_id).where(Title.id == title.id))).scalar_one()
    assert stored == picked.id
    assert picked.removed_at == A_SECOND_PASS


async def test_a_file_that_comes_back_clears_its_mark(db_session: AsyncSession) -> None:
    await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_FIRST_PASS)
    await library_sync.sync_library(
        db_session, client_for(fixture_library(without=IRON_MAN_ID)), full=True, clock=lambda: A_SECOND_PASS
    )

    result = await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_SECOND_PASS)

    assert (result.added, result.updated, result.removed) == (0, 1, 0)
    assert (await _rows(db_session))[IRON_MAN_ID].removed_at is None


async def test_an_item_of_a_type_this_index_does_not_hold_is_skipped(db_session: AsyncSession) -> None:
    """`BoxSet`, `Folder`, `Audio` - Jellyfin's vocabulary is wider than the three playable units."""
    a_box_set: dict[str, object] = {"Id": "boxsetboxsetboxsetboxsetboxset01", "Name": "Marvel", "Type": "BoxSet"}

    result = await library_sync.sync_library(
        db_session, client_for(JellyfinLibrary(scan=[a_box_set])), clock=lambda: A_FIRST_PASS
    )

    assert (result.seen, result.added) == (0, 0)
    assert await _rows(db_session) == {}


async def test_an_unconfigured_jellyfin_refuses_before_a_request_is_built(db_session: AsyncSession) -> None:
    responder = fixture_library()

    with pytest.raises(JellyfinUnavailableError):
        await library_sync.sync_library(db_session, client_for(responder, base_url=None), clock=lambda: A_FIRST_PASS)

    assert responder.requests == []
    assert await _rows(db_session) == {}


async def test_an_unreachable_jellyfin_is_one_attempt_and_no_rows(db_session: AsyncSession) -> None:
    client, attempts = _unreachable_client()

    with pytest.raises(JellyfinUnavailableError) as raised:
        await library_sync.sync_library(db_session, client, clock=lambda: A_FIRST_PASS)

    # One attempt, never a retry storm (CLAUDE.md section 6.6), and the upstream's own text is not repeated.
    assert len(attempts) == 1
    assert "ProviderUnavailableError" in str(raised.value)
    assert A_JELLYFIN_BASE_URL not in str(raised.value)
    assert await _rows(db_session) == {}


async def test_a_failed_walk_writes_nothing_even_after_pages_have_arrived(db_session: AsyncSession) -> None:
    """The scan succeeds and the show call dies: the whole pass is collected before a row is touched."""
    attempts: list[httpx.Request] = []
    scan = page(library_items())

    def answer_then_die(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1:
            return scan
        raise httpx.ConnectError("no route to host", request=request)

    http = build_jellyfin_http(A_JELLYFIN_BASE_URL, transport=httpx.MockTransport(answer_then_die))
    client = JellyfinClient(A_JELLYFIN_BASE_URL, SecretStr(A_RECORDED_JELLYFIN_KEY), http=http)

    with pytest.raises(JellyfinUnavailableError):
        await library_sync.sync_library(db_session, client, clock=lambda: A_FIRST_PASS)

    assert await _rows(db_session) == {}


async def test_the_cursor_is_the_latest_last_seen_at_over_live_rows(db_session: AsyncSession) -> None:
    """R87. Two rows, two stamps, and the walk asks from the later of them - never from the earlier."""
    db_session.add_all(
        [
            JellyfinItem(
                jellyfin_id=IRON_MAN_ID,
                kind=JellyfinItemKind.MOVIE,
                name="Iron Man",
                first_seen_at=AN_EARLIER_STAMP,
                last_seen_at=AN_EARLIER_STAMP,
            ),
            JellyfinItem(
                jellyfin_id=SPIDER_MAN_ID,
                kind=JellyfinItemKind.MOVIE,
                name="Spider-Man",
                first_seen_at=AN_EARLIER_STAMP,
                last_seen_at=A_LATER_STAMP,
            ),
        ]
    )
    await db_session.flush()
    responder = JellyfinLibrary()

    result = await library_sync.sync_library(db_session, client_for(responder), clock=lambda: A_SECOND_PASS)

    assert result.incremental is True
    assert responder.requests[0].url.params[CURSOR_PARAM] == A_LATER_STAMP.isoformat()


async def test_an_empty_index_walks_the_whole_library(db_session: AsyncSession) -> None:
    """R87's third step: there is nothing to be incremental about, so the first pass sees everything."""
    responder = fixture_library()

    result = await library_sync.sync_library(db_session, client_for(responder), clock=lambda: A_FIRST_PASS)

    assert result.incremental is False
    assert CURSOR_PARAM not in responder.requests[0].url.params


async def test_an_index_holding_only_removed_rows_walks_fully_again(db_session: AsyncSession) -> None:
    """`removed_at IS NULL` scopes the max, so a library that vanished entirely is rediscovered in full."""
    db_session.add(
        JellyfinItem(
            jellyfin_id=IRON_MAN_ID,
            kind=JellyfinItemKind.MOVIE,
            name="Iron Man",
            first_seen_at=AN_EARLIER_STAMP,
            last_seen_at=AN_EARLIER_STAMP,
            removed_at=A_LATER_STAMP,
        )
    )
    await db_session.flush()
    responder = fixture_library()

    result = await library_sync.sync_library(db_session, client_for(responder), clock=lambda: A_SECOND_PASS)

    assert result.incremental is False
    assert CURSOR_PARAM not in responder.requests[0].url.params


async def test_a_caller_may_hand_back_the_previous_passs_own_stamp(db_session: AsyncSession) -> None:
    """R87's first step, and the reason `LibrarySyncResult.synced_at` is worth keeping between passes."""
    responder = JellyfinLibrary()

    result = await library_sync.sync_library(
        db_session, client_for(responder), since=A_CALLER_HELD_CURSOR, clock=lambda: A_SECOND_PASS
    )

    assert result.incremental is True
    assert responder.requests[0].url.params[CURSOR_PARAM] == A_CALLER_HELD_CURSOR.isoformat()


async def test_full_overrides_a_cursor(db_session: AsyncSession) -> None:
    await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_FIRST_PASS)
    responder = JellyfinLibrary()

    result = await library_sync.sync_library(db_session, client_for(responder), full=True, clock=lambda: A_SECOND_PASS)

    assert result.incremental is False
    assert CURSOR_PARAM not in responder.requests[0].url.params
    # A full walk that saw nothing IS allowed to mark the library gone, which is the other half of the rule.
    assert result.removed == LIBRARY_ROWS


async def test_an_incremental_pass_sees_a_new_episode_of_an_unchanged_series(db_session: AsyncSession) -> None:
    """R89. The series record was not re-saved, so the scan does not return it and the show call is never
    made for it - the direct episode walk is the ONLY way this file is ever indexed."""
    await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_FIRST_PASS)
    responder = JellyfinLibrary(changed_episodes=[_a_new_episode_file()])

    result = await library_sync.sync_library(db_session, client_for(responder), clock=lambda: A_SECOND_PASS)

    assert result.incremental is True
    assert (result.seen, result.added, result.removed) == (1, 1, 0)
    arrived = (await _rows(db_session))[A_NEW_EPISODE_FILE_ID]
    assert arrived.kind is JellyfinItemKind.EPISODE
    assert arrived.series_jellyfin_id == ONE_PIECE_SERIES_ID
    assert arrived.index_number == 4
    # And it was asked for without the TMDB filter, which an episode file would almost never satisfy.
    delta = next(request for request in responder.requests if request.url.params.get(TYPES_PARAM) == EPISODE_TYPE)
    assert TMDB_FILTER_PARAM not in delta.url.params
    assert delta.url.params[CURSOR_PARAM] == A_FIRST_PASS.isoformat()


async def test_a_full_pass_asks_for_no_episode_delta(db_session: AsyncSession) -> None:
    """It would be a second walk of every episode in the library for nothing: the show calls cover them."""
    responder = fixture_library()

    await library_sync.sync_library(db_session, client_for(responder), full=True, clock=lambda: A_FIRST_PASS)

    assert [request for request in responder.requests if request.url.params.get(TYPES_PARAM) == EPISODE_TYPE] == []


async def test_the_pass_logs_one_key_value_record(db_session: AsyncSession, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger=LOGGER_NAME):
        await library_sync.sync_library(db_session, client_for(fixture_library()), clock=lambda: A_FIRST_PASS)

    record = _sync_record(caplog)
    assert "job=library_sync" in record
    assert f"seen={LIBRARY_ROWS}" in record
    assert f"added={LIBRARY_ROWS}" in record
    assert "updated=0 removed=0" in record
    assert "outcome=synced" in record


async def test_a_refused_pass_logs_the_reason_as_a_class_name(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO", logger=LOGGER_NAME), pytest.raises(JellyfinUnavailableError):
        await library_sync.sync_library(
            db_session, client_for(fixture_library(), base_url=None), clock=lambda: A_FIRST_PASS
        )

    record = _sync_record(caplog)
    assert "outcome=JellyfinUnavailableError" in record
    assert A_RECORDED_JELLYFIN_KEY not in record


async def test_a_skipped_type_is_logged_bounded_and_scrubbed(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """`Type` is free text from the server, and it lands in a log line: it may not forge a record."""
    forged: dict[str, object] = {"Id": "a" * 32, "Name": "x", "Type": "Box\r\nSet " + "z" * 200}

    with caplog.at_level("INFO", logger=LOGGER_NAME):
        await library_sync.sync_library(
            db_session, client_for(JellyfinLibrary(scan=[forged])), clock=lambda: A_FIRST_PASS
        )

    skipped = next(record.getMessage() for record in caplog.records if "library_sync_skipped" in record.getMessage())
    assert "\n" not in skipped and "\r" not in skipped
    assert len(skipped.split("type=", 1)[1]) <= MAX_JELLYFIN_ID_LENGTH
