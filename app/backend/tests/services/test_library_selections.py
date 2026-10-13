from __future__ import annotations

import pytest
from episode_join_support import a_category, a_film, a_series_file, a_show, an_entry, an_episode_file, file_id
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from provider_fixtures import JELLYFIN, fixture_text_response, jellyfin_client_for
from statement_support import counted_statements
from tv_watchlist.clock import utcnow
from tv_watchlist.data.enums import Availability, JellyfinItemKind, UnitKind
from tv_watchlist.data.models import JellyfinItem
from tv_watchlist.ingest.expansion import rebuild_items
from tv_watchlist.services.availability import availability_for
from tv_watchlist.services.episode_match import MatchState, episodes_for_entry
from tv_watchlist.services.library_selections import library_selections_for


async def test_equal_movie_and_series_provider_ids_do_not_cross_match(db_session: AsyncSession) -> None:
    film = await a_film(db_session, "Same Name", tmdb_id=4242)
    show = await a_show(db_session, "Same Name", episodes=1, tmdb_id=4242)
    series = await a_series_file(db_session, jellyfin_id=file_id(1), name=show.name, tmdb_id=show.tmdb_id)
    movie = JellyfinItem(jellyfin_id=file_id(2), kind=JellyfinItemKind.MOVIE, name=film.name, tmdb_id=film.tmdb_id)
    db_session.add(movie)
    await db_session.flush()
    results = await library_selections_for(db_session, [film.id, show.id])
    assert results[film.id].item_id == movie.id
    assert results[film.id].series_ids == ()
    assert results[show.id].item_id == series.id
    assert results[show.id].series_ids == (series.jellyfin_id,)


async def test_names_and_null_provider_ids_never_match(db_session: AsyncSession) -> None:
    title = await a_show(db_session, "Same Name", episodes=1)
    await a_series_file(db_session, jellyfin_id=file_id(1), name=title.name, tmdb_id=None)
    result = (await library_selections_for(db_session, [title.id]))[title.id]
    assert result.item_id is None
    assert result.series_ids == ()
    assert result.ambiguous is False


@pytest.mark.parametrize("parent_live", [True, False])
async def test_an_episode_pick_preserves_its_series_scope_and_returns_only_a_live_title_level_id(
    db_session: AsyncSession, parent_live: bool
) -> None:
    title = await a_show(db_session, "A Show", episodes=1, tmdb_id=4242)
    series = await a_series_file(db_session, jellyfin_id=file_id(100), name=title.name, tmdb_id=title.tmdb_id)
    episode = await an_episode_file(db_session, series_jellyfin_id=series.jellyfin_id, season=1, number=1)
    title.jellyfin_item_id = episode.id
    if not parent_live:
        series.removed_at = utcnow()
    await db_session.flush()
    result = (await library_selections_for(db_session, [title.id]))[title.id]
    assert result.series_ids == (series.jellyfin_id,)
    assert result.item_id == (series.id if parent_live else None)


async def test_an_empty_title_page_needs_no_database() -> None:
    assert await library_selections_for(AsyncSession(), []) == {}


@pytest.mark.parametrize("parent_tmdb_id", [9999, None])
@pytest.mark.parametrize("pick_live", [True, False])
@pytest.mark.parametrize("exact_candidate", [True, False])
async def test_only_a_live_episode_pick_preserves_its_parent_after_provider_metadata_changes(
    db_session: AsyncSession,
    engine: AsyncEngine,
    parent_tmdb_id: int | None,
    pick_live: bool,
    exact_candidate: bool,
) -> None:
    title = await a_show(db_session, "A Show", episodes=1, tmdb_id=4242)
    category = await a_category(db_session)
    entry = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.SERIES)
    await rebuild_items(db_session, category.id)
    parent = await a_series_file(db_session, jellyfin_id=file_id(100), name=title.name, tmdb_id=title.tmdb_id)
    picked = await an_episode_file(
        db_session, series_jellyfin_id=parent.jellyfin_id, season=1, number=1, jellyfin_id=file_id(200)
    )
    title.jellyfin_item_id = picked.id
    await db_session.flush()
    jellyfin, _ = jellyfin_client_for(fixture_text_response(JELLYFIN, "health"))
    try:
        baseline = await availability_for(db_session, jellyfin, [entry])
        assert baseline.entries[entry.id].availability is Availability.IN_LIBRARY
        assert baseline.entries[entry.id].jellyfin_item_id == parent.id

        parent.tmdb_id = parent_tmdb_id
        picked.removed_at = None if pick_live else utcnow()
        fallback_series_ids: tuple[str, ...] = ()
        if exact_candidate:
            candidate = await a_series_file(
                db_session, jellyfin_id=file_id(101), name=title.name, tmdb_id=title.tmdb_id
            )
            await an_episode_file(
                db_session, series_jellyfin_id=candidate.jellyfin_id, season=1, number=1, jellyfin_id=file_id(201)
            )
            fallback_series_ids = (candidate.jellyfin_id,)
        await db_session.flush()

        selection = (await library_selections_for(db_session, [title.id]))[title.id]
        matches = await episodes_for_entry(db_session, entry)
        with counted_statements(engine) as statements:
            result = await availability_for(db_session, jellyfin, [entry])
    finally:
        await jellyfin.aclose()

    assert len(statements) == 2
    assert selection.series_ids == ((parent.jellyfin_id,) if pick_live else fallback_series_ids)
    assert matches[0].state is (
        MatchState.MATCHED if pick_live else MatchState.AMBIGUOUS if exact_candidate else MatchState.NOT_IN_LIBRARY
    )
    assert matches[0].jellyfin_item_id == (picked.id if pick_live else None)
    assert result.entries[entry.id].availability is (
        Availability.IN_LIBRARY
        if pick_live
        else Availability.AMBIGUOUS
        if exact_candidate
        else Availability.NOT_IN_LIBRARY
    )
    assert result.entries[entry.id].jellyfin_item_id == (parent.id if pick_live else None)


@pytest.mark.parametrize("candidates", [0, 1, 2])
async def test_a_live_episode_pick_without_a_parent_preserves_exact_id_candidate_fallback(
    db_session: AsyncSession, candidates: int
) -> None:
    title = await a_show(db_session, "A Show", episodes=1, tmdb_id=4242)
    category = await a_category(db_session)
    entry = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.SERIES)
    await rebuild_items(db_session, category.id)
    series_rows: list[JellyfinItem] = []
    files: list[JellyfinItem] = []
    for index in range(candidates):
        series = await a_series_file(
            db_session, jellyfin_id=file_id(100 + index), name=title.name, tmdb_id=title.tmdb_id
        )
        series_rows.append(series)
        files.append(
            await an_episode_file(
                db_session, series_jellyfin_id=series.jellyfin_id, season=1, number=1, jellyfin_id=file_id(index)
            )
        )
    picked = JellyfinItem(jellyfin_id=file_id(200), kind=JellyfinItemKind.EPISODE, name="Episode without a parent")
    db_session.add(picked)
    await db_session.flush()
    title.jellyfin_item_id = picked.id
    await db_session.flush()

    selection = (await library_selections_for(db_session, [title.id]))[title.id]
    matches = await episodes_for_entry(db_session, entry)
    jellyfin, _ = jellyfin_client_for(fixture_text_response(JELLYFIN, "health"))
    try:
        result = await availability_for(db_session, jellyfin, [entry])
    finally:
        await jellyfin.aclose()

    assert set(selection.series_ids) == {series.jellyfin_id for series in series_rows}
    assert matches[0].state is (MatchState.NOT_IN_LIBRARY, MatchState.MATCHED, MatchState.AMBIGUOUS)[candidates]
    assert matches[0].jellyfin_item_id == (files[0].id if candidates == 1 else None)
    assert (
        result.entries[entry.id].availability
        is (
            Availability.NOT_IN_LIBRARY,
            Availability.IN_LIBRARY,
            Availability.AMBIGUOUS,
        )[candidates]
    )
    assert result.entries[entry.id].jellyfin_item_id == (series_rows[0].id if candidates == 1 else None)
