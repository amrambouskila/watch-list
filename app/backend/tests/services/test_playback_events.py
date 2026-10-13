from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from episode_join_support import a_category, a_film, a_series_file, a_show, an_entry, an_episode_file, file_id
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.data.enums import (
    JellyfinItemKind,
    ResolutionState,
    UnitKind,
    WatchEventKind,
    WatchEventSource,
    WatchSubjectKind,
)
from tv_watchlist.data.errors import PlaybackStateError
from tv_watchlist.data.models import CuratedEntryItem, EpisodeOrder, JellyfinItem, WatchEvent
from tv_watchlist.ingest.expansion import rebuild_items
from tv_watchlist.models.watch_event_create import WatchEventCreate
from tv_watchlist.services.episode_match import episodes_for_entry
from tv_watchlist.services.playback_events import _covered_episodes, record_playback_event


async def test_movie_snapshot_names_the_selected_duplicate_entry(db_session: AsyncSession) -> None:
    category = await a_category(db_session)
    title = await a_film(db_session, "Movie", tmdb_id=999)
    await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.MOVIE)
    selected = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.MOVIE, position=2)
    file = JellyfinItem(jellyfin_id=file_id(1), kind=JellyfinItemKind.MOVIE, name=title.name, tmdb_id=title.tmdb_id)
    db_session.add(file)
    await db_session.flush()
    await rebuild_items(db_session, category.id)
    result = await record_playback_event(
        db_session,
        WatchEventCreate(
            subject_kind=WatchSubjectKind.TITLE,
            subject_id=title.id,
            kind=WatchEventKind.PROGRESSED,
            position_seconds=301,
            runtime_seconds=300,
        ),
        selected.id,
        file.id,
    )
    assert result.source is WatchEventSource.PLAYER
    assert result.curated_entry_id == selected.id
    assert result.category_id == category.id
    assert result.position_seconds == 300
    assert result.progress is not None and result.progress.kind is WatchEventKind.PROGRESSED


@pytest.mark.parametrize("completed", [False, True])
async def test_range_completes_all_contained_episodes_only_when_ended(
    db_session: AsyncSession, completed: bool
) -> None:
    category = await a_category(db_session)
    title = await a_show(db_session, "Show", episodes=3, tmdb_id=999)
    entry = await an_entry(
        db_session,
        category,
        title_id=title.id,
        unit_kind=UnitKind.EPISODES,
        span_start=2,
        span_end=2,
        order_type="aired",
    )
    series = await a_series_file(db_session, jellyfin_id=file_id(100), name=title.name, tmdb_id=title.tmdb_id)
    file = await an_episode_file(db_session, series_jellyfin_id=series.jellyfin_id, season=1, number=1, number_end=3)
    await rebuild_items(db_session, category.id)
    slot = await db_session.scalar(select(CuratedEntryItem).where(CuratedEntryItem.curated_entry_id == entry.id))
    assert slot is not None and slot.episode_id is not None
    stamp = datetime(2026, 9, 24, tzinfo=UTC)
    result = await record_playback_event(
        db_session,
        WatchEventCreate(
            subject_kind=WatchSubjectKind.EPISODE,
            subject_id=slot.episode_id,
            kind=WatchEventKind.COMPLETED if completed else WatchEventKind.PROGRESSED,
            occurred_at=stamp,
            position_seconds=301 if completed else 299,
            runtime_seconds=300,
        ),
        entry.id,
        file.id,
    )
    events = list(await db_session.scalars(select(WatchEvent)))
    assert len(events) == (3 if completed else 1)
    assert all(event.source is WatchEventSource.PLAYER and event.category_id == category.id for event in events)
    assert all(event.position_seconds == (300 if completed else 299) for event in events)
    assert all(event.occurred_at == stamp for event in events)
    assert result.curated_entry_id == entry.id
    assert result.progress is not None and result.progress.episode_completed == int(completed)
    assert next(event for event in events if event.id == result.id).episode_id == slot.episode_id


@pytest.mark.parametrize("fault", ["gap", "duplicate-number", "early", "runtime", "wrong-file", "wrong-subject"])
async def test_invalid_completion_is_refused_before_any_event(db_session: AsyncSession, fault: str) -> None:
    category = await a_category(db_session)
    title = await a_show(db_session, "Show", episodes=3, tmdb_id=999)
    entry = await an_entry(
        db_session,
        category,
        title_id=title.id,
        unit_kind=UnitKind.EPISODES,
        span_start=2,
        span_end=2,
        order_type="aired",
    )
    series = await a_series_file(db_session, jellyfin_id=file_id(100), name=title.name, tmdb_id=title.tmdb_id)
    file = await an_episode_file(db_session, series_jellyfin_id=series.jellyfin_id, season=1, number=1, number_end=3)
    await rebuild_items(db_session, category.id)
    slot = await db_session.scalar(select(CuratedEntryItem).where(CuratedEntryItem.curated_entry_id == entry.id))
    assert slot is not None and slot.episode_id is not None
    orders = list(await db_session.scalars(select(EpisodeOrder).order_by(EpisodeOrder.sequence)))
    if fault == "gap":
        await db_session.delete(orders[0])
    if fault == "duplicate-number":
        orders[0].order_episode_number = 3
    await db_session.flush()
    with pytest.raises(PlaybackStateError):
        await record_playback_event(
            db_session,
            WatchEventCreate(
                subject_kind=WatchSubjectKind.EPISODE,
                subject_id=uuid.uuid4() if fault == "wrong-subject" else slot.episode_id,
                kind=WatchEventKind.COMPLETED,
                position_seconds=299 if fault == "early" else 300,
                runtime_seconds=None if fault == "runtime" else 300,
            ),
            entry.id,
            uuid.uuid4() if fault == "wrong-file" else file.id,
        )
    assert await db_session.scalar(select(func.count()).select_from(WatchEvent)) == 0


async def test_completion_uses_actual_stored_numbering_not_tmdb_pairs(db_session: AsyncSession) -> None:
    category = await a_category(db_session)
    title = await a_show(db_session, "Show", episodes=3, tmdb_id=999)
    orders = list(await db_session.scalars(select(EpisodeOrder).order_by(EpisodeOrder.sequence)))
    for order in orders:
        order.order_type, order.label = "regional", "A stored order"
        order.order_season_number, order.order_episode_number = 9, order.sequence + 10
    await db_session.flush()
    entry = await an_entry(
        db_session,
        category,
        title_id=title.id,
        unit_kind=UnitKind.EPISODES,
        span_start=2,
        span_end=2,
        order_type="regional",
        order_label="A stored order",
    )
    series = await a_series_file(db_session, jellyfin_id=file_id(100), name=title.name, tmdb_id=title.tmdb_id)
    file = await an_episode_file(db_session, series_jellyfin_id=series.jellyfin_id, season=9, number=11, number_end=13)
    await rebuild_items(db_session, category.id)
    await record_playback_event(
        db_session,
        WatchEventCreate(
            subject_kind=WatchSubjectKind.EPISODE,
            subject_id=orders[1].episode_id,
            kind=WatchEventKind.COMPLETED,
            position_seconds=300,
            runtime_seconds=300,
        ),
        entry.id,
        file.id,
    )
    assert set(await db_session.scalars(select(WatchEvent.episode_id))) == {row.episode_id for row in orders}


@pytest.mark.parametrize("changed", ["deleted", "start", "end"])
async def test_a_range_changed_after_selection_is_refused(db_session: AsyncSession, changed: str) -> None:
    category = await a_category(db_session)
    title = await a_show(db_session, "Show", episodes=2, tmdb_id=999)
    entry = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.SERIES)
    series = await a_series_file(db_session, jellyfin_id=file_id(100), name=title.name, tmdb_id=title.tmdb_id)
    file = await an_episode_file(db_session, series_jellyfin_id=series.jellyfin_id, season=1, number=1, number_end=2)
    await rebuild_items(db_session, category.id)
    match = (await episodes_for_entry(db_session, entry))[0]
    file_uuid = file.id
    if changed == "deleted":
        await db_session.execute(delete(JellyfinItem).where(JellyfinItem.id == file_uuid))
    elif changed == "start":
        file.index_number = None
    else:
        file.index_number_end = None
    await db_session.flush()
    if changed == "deleted":
        with pytest.raises(PlaybackStateError, match="no longer available"):
            await record_playback_event(
                db_session,
                WatchEventCreate(
                    subject_kind=WatchSubjectKind.EPISODE,
                    subject_id=match.episode_id,
                    kind=WatchEventKind.COMPLETED,
                    position_seconds=300,
                    runtime_seconds=300,
                ),
                entry.id,
                file_uuid,
            )
    else:
        with pytest.raises(PlaybackStateError, match="range"):
            await _covered_episodes(db_session, entry, match, file)


@pytest.mark.parametrize(
    "fault",
    [
        "category",
        "started",
        "unset",
        "missing-position",
        "unresolved",
        "entry-subject",
        "movie-not-queued",
        "movie-ambiguous",
        "movie-removed",
        "movie-wrong-kind",
        "no-title",
    ],
)
async def test_invalid_movie_context_never_records_a_player_fact(db_session: AsyncSession, fault: str) -> None:
    category = await a_category(db_session)
    title = await a_film(db_session, "Movie", tmdb_id=999)
    entry = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.MOVIE)
    file = JellyfinItem(jellyfin_id=file_id(1), kind=JellyfinItemKind.MOVIE, name=title.name, tmdb_id=title.tmdb_id)
    db_session.add(file)
    await db_session.flush()
    if fault != "movie-not-queued":
        await rebuild_items(db_session, category.id)
    if fault == "unresolved":
        entry.resolution_state = ResolutionState.UNRESOLVED
    if fault == "movie-ambiguous":
        db_session.add(
            JellyfinItem(jellyfin_id=file_id(2), kind=JellyfinItemKind.MOVIE, name=title.name, tmdb_id=title.tmdb_id)
        )
    if fault == "movie-removed":
        file.removed_at = datetime.now(UTC)
    if fault == "movie-wrong-kind":
        file.kind = JellyfinItemKind.SERIES
    await db_session.flush()
    kind = {
        "started": WatchEventKind.STARTED,
        "unset": WatchEventKind.UNSET,
        "missing-position": WatchEventKind.COMPLETED,
    }.get(fault, WatchEventKind.PROGRESSED)
    body = WatchEventCreate(
        subject_kind=WatchSubjectKind.CURATED_ENTRY if fault == "entry-subject" else WatchSubjectKind.TITLE,
        subject_id=uuid.uuid4() if fault == "no-title" else title.id,
        kind=kind,
        category_id=uuid.uuid4() if fault == "category" else None,
        position_seconds=None if fault == "missing-position" else 300,
        runtime_seconds=300,
    )
    with pytest.raises(PlaybackStateError):
        await record_playback_event(db_session, body, entry.id, file.id)
    assert await db_session.scalar(select(func.count()).select_from(WatchEvent)) == 0
