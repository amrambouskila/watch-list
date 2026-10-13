from __future__ import annotations

import uuid

import pytest
from episode_join_support import (
    a_category,
    a_film,
    a_series_file,
    a_show,
    an_entry,
    an_episode_file,
    file_id,
    files_from_fixture,
    fixture_series_id,
    one_piece_with_its_orderings,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from provider_fixtures import JELLYFIN, fixture_text_response, jellyfin_client_for
from statement_support import counted_statements
from tv_watchlist.clock import utcnow
from tv_watchlist.data.enums import Availability, JellyfinItemKind, ResolutionState, UnitKind
from tv_watchlist.data.errors import EntryNotFoundError, JellyfinUnavailableError
from tv_watchlist.data.models import CuratedEntryItem, EpisodeOrder, JellyfinItem
from tv_watchlist.ingest.expansion import rebuild_items
from tv_watchlist.services.playback_items import items_for_entry


async def test_episode_slots_keep_range_file_ids_and_queue_positions(db_session: AsyncSession) -> None:
    category = await a_category(db_session)
    title = await a_show(db_session, "A Show", episodes=3, tmdb_id=4242)
    entry = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.SERIES)
    series = await a_series_file(db_session, jellyfin_id=file_id(100), name=title.name, tmdb_id=title.tmdb_id)
    file = await an_episode_file(db_session, series_jellyfin_id=series.jellyfin_id, season=1, number=1, number_end=2)
    await rebuild_items(db_session, category.id)
    client, _ = jellyfin_client_for(fixture_text_response(JELLYFIN, "health"))
    try:
        rows = await items_for_entry(db_session, client, entry.id)
    finally:
        await client.aclose()
    assert [row.position_in_entry for row in rows] == [1, 2, 3]
    assert [row.absolute_position for row in rows] == [1, 2, 3]
    assert [row.jellyfin_item_id for row in rows] == [file.id, file.id, None]
    assert [row.covers_range for row in rows] == [True, True, False]
    assert [row.availability for row in rows] == [Availability.IN_LIBRARY] * 2 + [Availability.NOT_IN_LIBRARY]
    assert all(row.episode_id and row.movie_title_id is None and row.entry_id == entry.id for row in rows)
    assert all(row.order_type == "aired" and row.order_label == "" for row in rows)


@pytest.mark.parametrize("candidates", [0, 1, 2])
async def test_movie_slots_use_existing_three_state_selection(db_session: AsyncSession, candidates: int) -> None:
    category = await a_category(db_session)
    title = await a_film(db_session, "A Film", tmdb_id=4242)
    entry = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.MOVIE)
    files = [
        JellyfinItem(jellyfin_id=file_id(index), kind=JellyfinItemKind.MOVIE, name=title.name, tmdb_id=title.tmdb_id)
        for index in range(candidates)
    ]
    db_session.add_all(files)
    await db_session.flush()
    await rebuild_items(db_session, category.id)
    client, _ = jellyfin_client_for(fixture_text_response(JELLYFIN, "health"))
    try:
        rows = await items_for_entry(db_session, client, entry.id)
    finally:
        await client.aclose()
    assert len(rows) == 1
    row = rows[0]
    assert (
        row.availability == (Availability.NOT_IN_LIBRARY, Availability.IN_LIBRARY, Availability.AMBIGUOUS)[candidates]
    )
    assert row.jellyfin_item_id == (files[0].id if candidates == 1 else None)
    assert row.movie_title_id == title.id and row.episode_id is None
    assert (row.order_type, row.order_label, row.covers_range) == (None, "", False)


@pytest.mark.parametrize("removed", ["unknown", "entry", "category"])
async def test_unknown_and_removed_entries_are_404_before_health(db_session: AsyncSession, removed: str) -> None:
    category = await a_category(db_session)
    entry = await an_entry(db_session, category, title_id=None, unit_kind=UnitKind.UNKNOWN)
    if removed == "entry":
        entry.removed_at = utcnow()
    if removed == "category":
        category.retired_at = utcnow()
    await db_session.flush()
    client, responder = jellyfin_client_for(base_url=None)
    try:
        with pytest.raises(EntryNotFoundError):
            await items_for_entry(db_session, client, uuid.uuid4() if removed == "unknown" else entry.id)
    finally:
        await client.aclose()
    assert not responder.requests


async def test_unconfigured_jellyfin_refuses_even_an_empty_queue(db_session: AsyncSession) -> None:
    category = await a_category(db_session)
    entry = await an_entry(db_session, category, title_id=None, unit_kind=UnitKind.UNKNOWN)
    client, responder = jellyfin_client_for(base_url=None)
    try:
        with pytest.raises(JellyfinUnavailableError):
            await items_for_entry(db_session, client, entry.id)
    finally:
        await client.aclose()
    assert not responder.requests


async def test_recorded_one_piece_slots_reuse_numbering_and_keep_each_range_slot(db_session: AsyncSession) -> None:
    title = await one_piece_with_its_orderings(db_session)
    category = await a_category(db_session)
    entry = await an_entry(
        db_session,
        category,
        title_id=title.id,
        unit_kind=UnitKind.EPISODES,
        order_type="absolute",
        span_start=1,
        span_end=4,
    )
    series = await a_series_file(db_session, jellyfin_id=fixture_series_id(), name=title.name, tmdb_id=title.tmdb_id)
    files = await files_from_fixture(db_session, series_jellyfin_id=series.jellyfin_id)
    await rebuild_items(db_session, category.id)
    client, _ = jellyfin_client_for(fixture_text_response(JELLYFIN, "health"))
    try:
        rows = await items_for_entry(db_session, client, entry.id)
    finally:
        await client.aclose()
    assert [row.jellyfin_item_id for row in rows] == [files[0].id, files[1].id, files[2].id, files[2].id]
    assert [row.covers_range for row in rows] == [False, False, True, True]
    assert all(row.order_type == "absolute" for row in rows)
    assert len({row.id for row in rows}) == 4


@pytest.mark.parametrize("state", [ResolutionState.UNRESOLVED, ResolutionState.REJECTED])
async def test_stale_queue_of_an_unresolved_entry_does_not_become_playable(
    db_session: AsyncSession, state: ResolutionState
) -> None:
    category = await a_category(db_session)
    title = await a_film(db_session, "A Film", tmdb_id=4242)
    entry = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.MOVIE)
    db_session.add(
        JellyfinItem(jellyfin_id=file_id(1), kind=JellyfinItemKind.MOVIE, name=title.name, tmdb_id=title.tmdb_id)
    )
    await db_session.flush()
    await rebuild_items(db_session, category.id)
    entry.resolution_state = state
    await db_session.flush()
    client, _ = jellyfin_client_for(fixture_text_response(JELLYFIN, "health"))
    try:
        rows = await items_for_entry(db_session, client, entry.id)
    finally:
        await client.aclose()
    assert len(rows) == 1
    assert rows[0].availability is Availability.NOT_IN_LIBRARY
    assert rows[0].jellyfin_item_id is None


@pytest.mark.parametrize("shape", ["ambiguous", "dangling", "no-numbering", "picked"])
async def test_episode_slots_keep_ambiguity_dangling_picks_and_missing_numbering_explicit(
    db_session: AsyncSession, shape: str
) -> None:
    category = await a_category(db_session)
    title = await a_show(db_session, "A Show", episodes=2, tmdb_id=4242)
    entry = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.SERIES)
    first = await a_series_file(db_session, jellyfin_id=file_id(100), name=title.name, tmdb_id=title.tmdb_id)
    second = await a_series_file(db_session, jellyfin_id=file_id(101), name=title.name, tmdb_id=title.tmdb_id)
    chosen = await an_episode_file(db_session, series_jellyfin_id=first.jellyfin_id, season=1, number=1)
    await an_episode_file(db_session, series_jellyfin_id=second.jellyfin_id, season=1, number=1, jellyfin_id=file_id(2))
    await rebuild_items(db_session, category.id)
    if shape in {"picked", "dangling"}:
        title.jellyfin_item_id = first.id
    if shape == "dangling":
        first.removed_at = utcnow()
    if shape == "no-numbering":
        await db_session.execute(delete(EpisodeOrder).where(EpisodeOrder.title_id == title.id))
    await db_session.flush()
    client, _ = jellyfin_client_for(fixture_text_response(JELLYFIN, "health"))
    try:
        rows = await items_for_entry(db_session, client, entry.id)
    finally:
        await client.aclose()
    assert len(rows) == 2
    expected = {
        "ambiguous": Availability.AMBIGUOUS,
        "dangling": Availability.AMBIGUOUS,
        "no-numbering": Availability.NOT_IN_LIBRARY,
        "picked": Availability.IN_LIBRARY,
    }[shape]
    assert rows[0].availability is expected
    assert rows[0].jellyfin_item_id == (chosen.id if shape == "picked" else None)
    assert rows[1].availability is (Availability.AMBIGUOUS if shape == "dangling" else Availability.NOT_IN_LIBRARY)
    assert rows[1].jellyfin_item_id is None
    if shape == "no-numbering":
        assert all(row.order_type is None for row in rows)


@pytest.mark.parametrize("pick", ["live", "dangling", "wrong-kind"])
async def test_movie_picks_keep_the_existing_selection_and_never_expose_a_series_id(
    db_session: AsyncSession, pick: str
) -> None:
    category = await a_category(db_session)
    title = await a_film(db_session, "A Film", tmdb_id=4242)
    entry = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.MOVIE)
    chosen = JellyfinItem(jellyfin_id=file_id(1), kind=JellyfinItemKind.MOVIE, name=title.name, tmdb_id=title.tmdb_id)
    other = JellyfinItem(jellyfin_id=file_id(2), kind=JellyfinItemKind.MOVIE, name=title.name, tmdb_id=title.tmdb_id)
    db_session.add_all([chosen, other])
    await db_session.flush()
    title.jellyfin_item_id = chosen.id
    if pick == "dangling":
        chosen.removed_at = utcnow()
    if pick == "wrong-kind":
        chosen.kind = JellyfinItemKind.SERIES
    await db_session.flush()
    await rebuild_items(db_session, category.id)
    client, _ = jellyfin_client_for(fixture_text_response(JELLYFIN, "health"))
    try:
        rows = await items_for_entry(db_session, client, entry.id)
    finally:
        await client.aclose()
    expected = {
        "live": Availability.IN_LIBRARY,
        "dangling": Availability.AMBIGUOUS,
        "wrong-kind": Availability.NOT_IN_LIBRARY,
    }
    assert rows[0].availability is expected[pick]
    assert rows[0].jellyfin_item_id == (chosen.id if pick == "live" else None)


async def test_paging_and_other_entries_do_not_leak_slots_or_add_per_slot_queries(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    category = await a_category(db_session)
    title = await a_show(db_session, "A Show", episodes=20, tmdb_id=4242)
    entry = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.SERIES)
    await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.SERIES, position=2)
    series = await a_series_file(db_session, jellyfin_id=file_id(100), name=title.name, tmdb_id=title.tmdb_id)
    await an_episode_file(db_session, series_jellyfin_id=series.jellyfin_id, season=1, number=1, number_end=20)
    await rebuild_items(db_session, category.id)
    expected = list(
        await db_session.scalars(
            select(CuratedEntryItem.id)
            .where(CuratedEntryItem.curated_entry_id == entry.id)
            .order_by(CuratedEntryItem.position_in_entry)
        )
    )
    client, _ = jellyfin_client_for(fixture_text_response(JELLYFIN, "health"))
    try:
        with counted_statements(engine) as one:
            first = await items_for_entry(db_session, client, entry.id, limit=1)
        with counted_statements(engine) as many:
            remaining = await items_for_entry(db_session, client, entry.id, offset=1)
        assert await items_for_entry(db_session, client, entry.id, offset=20) == []
    finally:
        await client.aclose()
    assert len(one) == len(many) == 4
    assert [row.id for row in first + remaining] == expected
    assert all(row.entry_id == entry.id for row in first + remaining)
