from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from episode_join_support import a_category, a_film, a_series_file, a_show, an_entry, an_episode_file, file_id
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from provider_fixtures import JELLYFIN, RecordingResponder, fixture_text_response, jellyfin_client_for
from statement_support import counted_statements
from tv_watchlist.clients.jellyfin_client import JellyfinClient
from tv_watchlist.clock import utcnow
from tv_watchlist.data.enums import Availability, JellyfinItemKind, ResolutionState, UnitKind
from tv_watchlist.data.models import CuratedEntry, JellyfinItem, Title
from tv_watchlist.ingest.expansion import rebuild_items
from tv_watchlist.services.availability import availability_for


@pytest.fixture
async def healthy_jellyfin() -> AsyncIterator[JellyfinClient]:
    client, responder = jellyfin_client_for(responder=RecordingResponder(fixture_text_response(JELLYFIN, "health")))
    yield client
    assert all(request.url.path == "/health" for request in responder.requests)
    await client.aclose()


async def test_an_empty_page_needs_neither_a_database_nor_a_health_probe() -> None:
    client, responder = jellyfin_client_for()
    try:
        result = await availability_for(AsyncSession(), client, [])
    finally:
        await client.aclose()
    assert result.entries == {}
    assert result.notice is None
    assert responder.requests == []


async def _movie(session: AsyncSession, *, candidates: int = 1) -> tuple[CuratedEntry, Title, list[JellyfinItem]]:
    title = await a_film(session, "A Film", tmdb_id=4242)
    category = await a_category(session)
    entry = await an_entry(session, category, title_id=title.id, unit_kind=UnitKind.MOVIE)
    files = [
        JellyfinItem(jellyfin_id=file_id(index), kind=JellyfinItemKind.MOVIE, tmdb_id=title.tmdb_id, name=title.name)
        for index in range(1, candidates + 1)
    ]
    session.add_all(files)
    await session.flush()
    await rebuild_items(session, category.id)
    return entry, title, files


async def _series(session: AsyncSession) -> tuple[CuratedEntry, Title, JellyfinItem]:
    title = await a_show(session, "A Show", episodes=3, tmdb_id=4242)
    category = await a_category(session)
    entry = await an_entry(session, category, title_id=title.id, unit_kind=UnitKind.SERIES)
    series = await a_series_file(session, jellyfin_id=file_id(100), name=title.name, tmdb_id=title.tmdb_id)
    await rebuild_items(session, category.id)
    return entry, title, series


async def test_an_unconfigured_jellyfin_reports_not_in_library_for_every_entry_with_a_notice(
    db_session: AsyncSession,
) -> None:
    entry, _, _ = await _movie(db_session)
    client, responder = jellyfin_client_for(base_url=None)
    try:
        result = await availability_for(db_session, client, [entry])
    finally:
        await client.aclose()
    assert result.notice == "Jellyfin is not configured"
    assert result.entries[entry.id].availability is Availability.NOT_IN_LIBRARY
    assert result.entries[entry.id].jellyfin_item_id is None
    assert not responder.requests


async def test_an_unreachable_jellyfin_is_the_same_as_unconfigured_and_never_raises(
    db_session: AsyncSession,
) -> None:
    entry, title, files = await _movie(db_session)
    title.jellyfin_item_id = files[0].id
    await db_session.flush()
    client, responder = jellyfin_client_for(responder=RecordingResponder(httpx.Response(503)))
    try:
        result = await availability_for(db_session, client, [entry])
    finally:
        await client.aclose()
    assert result.notice == "Jellyfin unreachable"
    assert result.entries[entry.id].availability is Availability.NOT_IN_LIBRARY
    assert result.entries[entry.id].jellyfin_item_id is None
    assert len(responder.requests) == 1


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [(0, Availability.NOT_IN_LIBRARY), (1, Availability.IN_LIBRARY), (2, Availability.AMBIGUOUS)],
)
async def test_movie_candidates_produce_the_three_explicit_states(
    db_session: AsyncSession, healthy_jellyfin: JellyfinClient, candidates: int, expected: Availability
) -> None:
    entry, _, files = await _movie(db_session, candidates=candidates)
    result = await availability_for(db_session, healthy_jellyfin, [entry])
    assert result.notice is None
    assert result.entries[entry.id].availability is expected
    assert result.entries[entry.id].jellyfin_item_id == (files[0].id if candidates == 1 else None)


async def test_a_stored_pick_wins_over_re_derivation(
    db_session: AsyncSession, healthy_jellyfin: JellyfinClient
) -> None:
    entry, title, files = await _movie(db_session, candidates=2)
    title.jellyfin_item_id = files[1].id
    await db_session.flush()
    result = await availability_for(db_session, healthy_jellyfin, [entry])
    assert result.entries[entry.id].availability is Availability.IN_LIBRARY
    assert result.entries[entry.id].jellyfin_item_id == files[1].id


@pytest.mark.parametrize("remaining", [0, 1, 2])
async def test_a_soft_deleted_pick_is_ambiguous_while_any_candidate_survives(
    db_session: AsyncSession, healthy_jellyfin: JellyfinClient, remaining: int
) -> None:
    entry, title, files = await _movie(db_session, candidates=remaining + 1)
    title.jellyfin_item_id = files[0].id
    files[0].removed_at = utcnow()
    await db_session.flush()
    result = await availability_for(db_session, healthy_jellyfin, [entry])
    expected = Availability.AMBIGUOUS if remaining else Availability.NOT_IN_LIBRARY
    assert result.entries[entry.id].availability is expected
    assert result.entries[entry.id].jellyfin_item_id is None


@pytest.mark.parametrize("state", [ResolutionState.UNRESOLVED, ResolutionState.REJECTED])
async def test_an_unresolved_or_rejected_entry_is_not_in_library_even_with_stale_candidates(
    db_session: AsyncSession, healthy_jellyfin: JellyfinClient, state: ResolutionState
) -> None:
    entry, _, _ = await _movie(db_session)
    entry.resolution_state = state
    await db_session.flush()
    result = await availability_for(db_session, healthy_jellyfin, [entry])
    assert result.entries[entry.id].availability is Availability.NOT_IN_LIBRARY


@pytest.mark.parametrize("found", [0, 1, 3])
async def test_every_episode_slot_must_match_before_the_entry_is_in_library(
    db_session: AsyncSession, healthy_jellyfin: JellyfinClient, found: int
) -> None:
    entry, _, series = await _series(db_session)
    for number in range(1, found + 1):
        await an_episode_file(db_session, series_jellyfin_id=series.jellyfin_id, season=1, number=number)
    result = await availability_for(db_session, healthy_jellyfin, [entry])
    expected = Availability.IN_LIBRARY if found == 3 else Availability.NOT_IN_LIBRARY
    assert result.entries[entry.id].availability is expected
    assert result.entries[entry.id].jellyfin_item_id == (series.id if found == 3 else None)


async def test_a_live_series_pick_does_not_turn_a_partially_present_span_into_in_library(
    db_session: AsyncSession, healthy_jellyfin: JellyfinClient
) -> None:
    entry, title, series = await _series(db_session)
    title.jellyfin_item_id = series.id
    await an_episode_file(db_session, series_jellyfin_id=series.jellyfin_id, season=1, number=1)
    await db_session.flush()
    result = await availability_for(db_session, healthy_jellyfin, [entry])
    assert result.entries[entry.id].availability is Availability.NOT_IN_LIBRARY
    assert result.entries[entry.id].jellyfin_item_id is None


async def test_an_empty_series_queue_does_not_claim_the_title_is_in_library(
    db_session: AsyncSession, healthy_jellyfin: JellyfinClient
) -> None:
    title = await a_show(db_session, "A Show", episodes=0, tmdb_id=4242)
    category = await a_category(db_session)
    entry = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.SERIES)
    await a_series_file(db_session, jellyfin_id=file_id(100), name=title.name, tmdb_id=title.tmdb_id)
    result = await availability_for(db_session, healthy_jellyfin, [entry])
    assert result.entries[entry.id].availability is Availability.NOT_IN_LIBRARY


async def test_an_ambiguous_slot_wins_over_missing_slots(
    db_session: AsyncSession, healthy_jellyfin: JellyfinClient
) -> None:
    entry, _, series = await _series(db_session)
    for index in range(1, 3):
        await an_episode_file(
            db_session, series_jellyfin_id=series.jellyfin_id, season=1, number=1, jellyfin_id=file_id(index)
        )
    result = await availability_for(db_session, healthy_jellyfin, [entry])
    assert result.entries[entry.id].availability is Availability.AMBIGUOUS
    assert result.entries[entry.id].jellyfin_item_id is None


async def test_a_multi_episode_file_satisfies_every_covered_slot_but_the_wire_id_is_the_series(
    db_session: AsyncSession, healthy_jellyfin: JellyfinClient
) -> None:
    entry, _, series = await _series(db_session)
    file = await an_episode_file(db_session, series_jellyfin_id=series.jellyfin_id, season=1, number=1, number_end=3)
    result = await availability_for(db_session, healthy_jellyfin, [entry])
    assert result.entries[entry.id].availability is Availability.IN_LIBRARY
    assert result.entries[entry.id].jellyfin_item_id == series.id
    assert result.entries[entry.id].jellyfin_item_id != file.id


async def test_page_query_count_is_constant_across_entries_and_episodes(
    db_session: AsyncSession, engine: AsyncEngine, healthy_jellyfin: JellyfinClient
) -> None:
    entry, title, series = await _series(db_session)
    await an_episode_file(db_session, series_jellyfin_id=series.jellyfin_id, season=1, number=1, number_end=3)
    category = await a_category(db_session, slug="another-category")
    extra = [
        await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.SERIES, position=position)
        for position in range(1, 21)
    ]
    await rebuild_items(db_session, category.id)
    with counted_statements(engine) as one:
        await availability_for(db_session, healthy_jellyfin, [entry])
    with counted_statements(engine) as many:
        result = await availability_for(db_session, healthy_jellyfin, [entry, *extra])
    assert len(one) == len(many) == 2
    assert all(value.availability is Availability.IN_LIBRARY for value in result.entries.values())
