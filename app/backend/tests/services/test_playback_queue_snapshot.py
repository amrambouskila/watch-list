from __future__ import annotations

import uuid

import pytest
from episode_join_support import a_category, a_film, a_second_numbering, a_show, an_entry
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from statement_support import counted_statements
from tv_watchlist.clock import utcnow
from tv_watchlist.data.enums import ResolutionState, UnitKind
from tv_watchlist.data.models import Category, CuratedEntry, CuratedEntryItem, Episode, EpisodeOrder, Title
from tv_watchlist.ingest.expansion import rebuild_items
from tv_watchlist.services.playback_queue_snapshot import capture_playback_queue


@pytest.fixture
async def queue(db_session: AsyncSession) -> tuple[Category, CuratedEntry, CuratedEntry, CuratedEntry, CuratedEntry]:
    category = await a_category(db_session)
    show = await a_show(db_session, "A Show", episodes=3, tmdb_id=1399)
    film = await a_film(db_session, "A Film", tmdb_id=603)
    first = await an_entry(
        db_session,
        category,
        title_id=show.id,
        unit_kind=UnitKind.EPISODES,
        order_type="aired",
        span_start=1,
        span_end=2,
    )
    movie = await an_entry(db_session, category, title_id=film.id, unit_kind=UnitKind.MOVIE, position=2)
    repeated = await an_entry(
        db_session,
        category,
        title_id=show.id,
        unit_kind=UnitKind.EPISODES,
        order_type="aired",
        span_start=2,
        span_end=3,
        position=3,
    )
    barrier = await an_entry(db_session, category, title_id=None, unit_kind=UnitKind.UNKNOWN, position=4)
    barrier.resolution_state = ResolutionState.UNRESOLVED
    await db_session.flush()
    await rebuild_items(db_session, category.id)
    return category, first, movie, repeated, barrier


async def test_all_covered_occurrences_are_kept_in_order_and_category_scope(
    db_session: AsyncSession,
    engine: AsyncEngine,
    queue: tuple[Category, CuratedEntry, CuratedEntry, CuratedEntry, CuratedEntry],
) -> None:
    category, first, _, repeated, _ = queue
    episode = await db_session.scalar(
        select(Episode).where(Episode.title_id == first.title_id, Episode.episode_number == 2)
    )
    other = await a_category(db_session, "other")
    await an_entry(db_session, other, title_id=first.title_id, unit_kind=UnitKind.SERIES)
    await rebuild_items(db_session, other.id)
    with counted_statements(engine) as statements:
        result = await capture_playback_queue(db_session, category.id, "episode", frozenset({episode.id}))
    assert len(statements) == 2
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert [
        (item.entry_id, item.subject_id_snapshot, item.tmdb_key, item.position_in_entry) for item in result.occurrences
    ] == [
        (first.id, episode.id, "tv:1399:s1:e2", 2),
        (repeated.id, episode.id, "tv:1399:s1:e2", 1),
    ]
    assert all(item.subject_kind == "episode" for item in result.occurrences)


async def test_movie_occurrence_and_cache_rebuild_keep_logical_snapshot(
    db_session: AsyncSession,
    queue: tuple[Category, CuratedEntry, CuratedEntry, CuratedEntry, CuratedEntry],
) -> None:
    category, _, movie, _, _ = queue
    result = await capture_playback_queue(db_session, category.id, "title", frozenset({movie.title_id}))
    old_ids = set(await db_session.scalars(select(CuratedEntryItem.id)))
    await rebuild_items(db_session, category.id)
    assert old_ids.isdisjoint(set(await db_session.scalars(select(CuratedEntryItem.id))))
    assert await capture_playback_queue(db_session, category.id, "title", frozenset({movie.title_id})) == result
    assert [(item.entry_id, item.tmdb_key, item.position_in_entry) for item in result.occurrences] == [
        (movie.id, "movie:603", 1)
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"position": 5},
        {"resolution_state": ResolutionState.CONFIRMED},
        {"order_type": "absolute"},
        {"order_label": "Another order"},
        {"span_start": 2},
        {"span_end": 3},
        {"season_number": 2},
        {"unit_kind": UnitKind.SERIES},
        {"raw_title": "Changed title"},
        {"raw_unit": "Changed unit"},
        {"raw_release": "2001"},
        {"removed_at": utcnow()},
        {"title_id": None},
    ],
)
async def test_semantic_entry_edits_invalidate_fingerprint_without_cached_orm_reads(
    db_session: AsyncSession,
    queue: tuple[Category, CuratedEntry, CuratedEntry, CuratedEntry, CuratedEntry],
    change: dict[str, object],
) -> None:
    category, first, _, _, _ = queue
    before = await capture_playback_queue(db_session, category.id, "episode", frozenset())
    await db_session.execute(
        update(CuratedEntry)
        .where(CuratedEntry.id == first.id)
        .values(**change)
        .execution_options(synchronize_session=False)
    )
    after = await capture_playback_queue(db_session, category.id, "episode", frozenset())
    assert after.fingerprint != before.fingerprint


async def test_empty_barriers_and_provider_numbering_are_part_of_the_fingerprint(
    db_session: AsyncSession,
    queue: tuple[Category, CuratedEntry, CuratedEntry, CuratedEntry, CuratedEntry],
) -> None:
    category, first, _, _, barrier = queue
    before = await capture_playback_queue(db_session, category.id, "episode", frozenset())
    barrier.raw_title = "Unresolved replacement"
    await db_session.flush()
    changed_barrier = await capture_playback_queue(db_session, category.id, "episode", frozenset())
    assert changed_barrier.fingerprint != before.fingerprint
    await db_session.execute(
        update(EpisodeOrder)
        .where(EpisodeOrder.title_id == first.title_id)
        .values(order_season_number=2)
        .execution_options(synchronize_session=False)
    )
    assert (
        await capture_playback_queue(db_session, category.id, "episode", frozenset())
    ).fingerprint != changed_barrier.fingerprint


async def test_watch_state_display_metadata_and_timestamps_are_not_semantic_queue_changes(
    db_session: AsyncSession,
    queue: tuple[Category, CuratedEntry, CuratedEntry, CuratedEntry, CuratedEntry],
) -> None:
    category, first, _, _, _ = queue
    before = await capture_playback_queue(db_session, category.id, "episode", frozenset())
    first.observed_watch_cell, first.mirrored_watch_cell = "Watched", "Watched"
    first.raw_cells = {"watched": "Watched"}
    first.last_seen_at, first.resolution_note = utcnow(), "Changed explanation"
    await db_session.execute(update(Title).values(name="Display changed", overview="Fresh description"))
    await db_session.flush()
    assert await capture_playback_queue(db_session, category.id, "episode", frozenset()) == before


async def test_provider_identity_changes_and_local_titles_have_explicit_null_keys(
    db_session: AsyncSession,
    queue: tuple[Category, CuratedEntry, CuratedEntry, CuratedEntry, CuratedEntry],
) -> None:
    category, first, movie, _, _ = queue
    before = await capture_playback_queue(db_session, category.id, "title", frozenset({movie.title_id}))
    await db_session.execute(update(Title).values(tmdb_id=None).execution_options(synchronize_session=False))
    after = await capture_playback_queue(db_session, category.id, "title", frozenset({movie.title_id}))
    assert after.fingerprint != before.fingerprint
    assert after.occurrences[0].tmdb_key is None
    episode = await db_session.scalar(select(Episode).where(Episode.title_id == first.title_id).limit(1))
    episodes = await capture_playback_queue(db_session, category.id, "episode", frozenset({episode.id}))
    assert all(item.tmdb_key is None for item in episodes.occurrences)


async def test_empty_or_retired_category_yields_no_occurrences(db_session: AsyncSession) -> None:
    category = await a_category(db_session)
    before = await capture_playback_queue(db_session, category.id, "title", frozenset({uuid.uuid4()}))
    assert before.occurrences == ()
    film = await a_film(db_session, "Retired")
    await an_entry(db_session, category, title_id=film.id, unit_kind=UnitKind.MOVIE)
    await rebuild_items(db_session, category.id)
    category.retired_at = utcnow()
    await db_session.flush()
    assert await capture_playback_queue(db_session, category.id, "title", frozenset({film.id})) == before


async def test_repeated_movie_occurrences_remain_distinct_with_constant_query_count(
    db_session: AsyncSession,
    engine: AsyncEngine,
) -> None:
    category = await a_category(db_session)
    film = await a_film(db_session, "Repeated film", tmdb_id=603)
    entries = [
        await an_entry(db_session, category, title_id=film.id, unit_kind=UnitKind.MOVIE, position=position)
        for position in range(1, 101)
    ]
    await rebuild_items(db_session, category.id)
    entries[-1].removed_at = utcnow()
    await db_session.flush()
    with counted_statements(engine) as statements:
        result = await capture_playback_queue(db_session, category.id, "title", frozenset({film.id}))
    assert len(statements) == 1
    assert [item.entry_id for item in result.occurrences] == [entry.id for entry in entries[:-1]]
    assert {item.subject_id_snapshot for item in result.occurrences} == {film.id}


async def test_empty_entry_provider_identity_is_included_even_without_a_slot(
    db_session: AsyncSession,
    queue: tuple[Category, CuratedEntry, CuratedEntry, CuratedEntry, CuratedEntry],
) -> None:
    category, _, _, _, barrier = queue
    title = await a_film(db_session, "Unresolved candidate", tmdb_id=42)
    barrier.title_id = title.id
    await db_session.flush()
    before = await capture_playback_queue(db_session, category.id, "title", frozenset())
    await db_session.execute(
        update(Title).where(Title.id == title.id).values(tmdb_id=43).execution_options(synchronize_session=False)
    )
    assert (
        await capture_playback_queue(db_session, category.id, "title", frozenset())
    ).fingerprint != before.fingerprint


async def test_season_numbering_reuses_expansion_dispatch_and_never_falls_back(
    db_session: AsyncSession,
) -> None:
    category = await a_category(db_session)
    show = await a_show(db_session, "A show", episodes=2, tmdb_id=1399)
    await a_second_numbering(db_session, show, order_type="dvd", season_number=9, first_number=7)
    entry = await an_entry(
        db_session, category, title_id=show.id, unit_kind=UnitKind.SEASON, order_type="dvd", season_number=1
    )
    await rebuild_items(db_session, category.id)
    before = await capture_playback_queue(db_session, category.id, "episode", frozenset())
    await db_session.execute(
        update(EpisodeOrder).where(EpisodeOrder.order_type == "dvd").values(order_episode_number=99)
    )
    assert await capture_playback_queue(db_session, category.id, "episode", frozenset()) == before
    await db_session.execute(delete(EpisodeOrder).where(EpisodeOrder.order_type == "aired"))
    missing = await capture_playback_queue(db_session, category.id, "episode", frozenset())
    assert missing.fingerprint != before.fingerprint
    entry.order_type = "other-ignored-season-order"
    await db_session.flush()
    assert (
        await capture_playback_queue(db_session, category.id, "episode", frozenset())
    ).fingerprint != missing.fingerprint


@pytest.mark.parametrize("change", ["subject", "position", "episode_key"])
async def test_changed_logical_slot_identity_position_and_tmdb_key_invalidate_snapshot(
    db_session: AsyncSession,
    queue: tuple[Category, CuratedEntry, CuratedEntry, CuratedEntry, CuratedEntry],
    change: str,
) -> None:
    category, first, movie, _, _ = queue
    before = await capture_playback_queue(db_session, category.id, "episode", frozenset())
    if change == "subject":
        replacement = await a_film(db_session, "Replacement", tmdb_id=42)
        await db_session.execute(
            update(CuratedEntryItem)
            .where(CuratedEntryItem.curated_entry_id == movie.id)
            .values(movie_title_id=replacement.id)
        )
    elif change == "position":
        await db_session.execute(
            update(CuratedEntryItem).where(CuratedEntryItem.curated_entry_id == movie.id).values(position_in_entry=2)
        )
    else:
        await db_session.execute(
            update(Episode)
            .where(Episode.title_id == first.title_id, Episode.episode_number == 3)
            .values(episode_number=4)
        )
    assert (
        await capture_playback_queue(db_session, category.id, "episode", frozenset())
    ).fingerprint != before.fingerprint


async def test_covered_subject_filter_does_not_change_whole_queue_fingerprint(
    db_session: AsyncSession,
    queue: tuple[Category, CuratedEntry, CuratedEntry, CuratedEntry, CuratedEntry],
) -> None:
    category, _, movie, _, _ = queue
    episodes = await capture_playback_queue(db_session, category.id, "episode", frozenset())
    movies = await capture_playback_queue(db_session, category.id, "title", frozenset({movie.title_id}))
    assert episodes.fingerprint == movies.fingerprint
    assert episodes.occurrences == ()
    assert len(movies.occurrences) == 1
