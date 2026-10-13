"""TMDB-only episode refreshes participate in the same receipt-coherence transaction gate."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Literal

import pytest
from episode_join_support import a_category, a_series_file, a_show, an_entry, an_episode_file, file_id
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from review_support import tmdb_runtime
from statement_support import counted_statements
from tv_watchlist.config import Settings
from tv_watchlist.data.enums import UnitKind, WatchEventKind, WatchSubjectKind
from tv_watchlist.data.episode_order_lock import try_episode_order_locks
from tv_watchlist.data.errors import PlaybackStateError
from tv_watchlist.data.models import (
    Category,
    CuratedEntry,
    Episode,
    JellyfinItem,
    PlaybackCompletion,
    Title,
    WatchEvent,
)
from tv_watchlist.ingest.episode_order_busy_error import EpisodeOrderBusyError
from tv_watchlist.ingest.expansion import rebuild_items
from tv_watchlist.ingest.runtime import IngestRuntime
from tv_watchlist.ingest.tmdb_ingest import TmdbIngest
from tv_watchlist.models.playback_queue_snapshot import PlaybackQueueSnapshot
from tv_watchlist.models.tmdb.tmdb_episode import TmdbEpisode
from tv_watchlist.models.tmdb.tmdb_season import TmdbSeason
from tv_watchlist.models.watch_event_create import WatchEventCreate
from tv_watchlist.services import playback_events
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.playback_queue_snapshot import capture_playback_queue


@pytest.fixture
async def tmdb_playback(
    engine: AsyncEngine, settings: Settings, catalog: Catalog
) -> AsyncIterator[tuple[CuratedEntry, JellyfinItem, Episode, IngestRuntime]]:
    async with AsyncSession(engine, expire_on_commit=False) as seed:
        category = await a_category(seed, f"tmdb-numbering-{uuid.uuid4()}")
        title = await a_show(seed, "TMDB-only show", episodes=1, tmdb_id=999)
        entry = await an_entry(seed, category, title_id=title.id, unit_kind=UnitKind.SERIES)
        await rebuild_items(seed, category.id)
        series = await a_series_file(seed, jellyfin_id=file_id(100), name=title.name, tmdb_id=999)
        file = await an_episode_file(seed, series_jellyfin_id=series.jellyfin_id, season=1, number=1)
        episode = await seed.scalar(select(Episode).where(Episode.title_id == title.id))
        assert episode is not None
        await seed.commit()
    runtime = tmdb_runtime(settings, catalog, engine)
    try:
        async with AsyncSession(engine) as session:
            assert runtime.reconciler(session)._orders is None
            assert runtime.tmdb_client(session).configured
        yield entry, file, episode, runtime
    finally:
        await runtime.aclose()
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(CuratedEntry).where(CuratedEntry.id == entry.id))
            await cleanup.execute(delete(Category).where(Category.id == category.id))
            await cleanup.execute(delete(Title).where(Title.id == title.id))
            await cleanup.execute(delete(JellyfinItem).where(JellyfinItem.id.in_((file.id, series.id))))
            await cleanup.commit()


def _details(episode: Episode, number: int) -> TmdbSeason:
    return TmdbSeason(
        id=1,
        season_number=1,
        episodes=(TmdbEpisode(id=episode.tmdb_episode_id, season_number=1, episode_number=number),),
    )


def _completion(episode: Episode) -> WatchEventCreate:
    return WatchEventCreate(
        subject_kind=WatchSubjectKind.EPISODE,
        subject_id=episode.id,
        kind=WatchEventKind.COMPLETED,
        position_seconds=300,
        runtime_seconds=300,
    )


@pytest.mark.parametrize("insert", [False, True])
async def test_held_reader_refuses_actual_tmdb_upsert_and_caller_rollback_removes_prior_writes(
    engine: AsyncEngine,
    tmdb_playback: tuple[CuratedEntry, JellyfinItem, Episode, IngestRuntime],
    insert: bool,
) -> None:
    _, _, episode, runtime = tmdb_playback
    details = _details(episode, 4)
    if insert:
        details = details.model_copy(
            update={"episodes": (details.episodes[0].model_copy(update={"id": episode.tmdb_episode_id + 100}),)}
        )
    async with AsyncSession(engine) as reader, AsyncSession(engine) as writer:
        assert await try_episode_order_locks(reader, [episode.title_id], shared=True)
        await writer.execute(update(Title).where(Title.id == episode.title_id).values(name="Uncommitted refresh"))
        ingest = TmdbIngest(writer, runtime.tmdb_client(writer))
        known = await ingest._episode_index(episode.title_id)
        with counted_statements(engine) as statements:
            with pytest.raises(EpisodeOrderBusyError, match="numbering is busy"):
                await asyncio.wait_for(
                    ingest._stored_episodes(episode.title_id, episode.season_id, details, known), timeout=1
                )
        assert len(statements) == 1 and "pg_try_advisory_xact_lock" in statements[0]
        assert writer.in_transaction()
        assert await writer.scalar(select(Episode.episode_number).where(Episode.id == episode.id)) == 1
        await writer.rollback()
        assert await writer.scalar(select(Title.name).where(Title.id == episode.title_id)) == "TMDB-only show"
        assert await writer.scalar(select(func.count()).select_from(Episode)) == 1


async def test_tmdb_refresh_between_captured_queue_and_events_cannot_splice_old_and_new_keys(
    engine: AsyncEngine,
    tmdb_playback: tuple[CuratedEntry, JellyfinItem, Episode, IngestRuntime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, file, episode, runtime = tmdb_playback
    async with AsyncSession(engine) as reader, AsyncSession(engine) as writer:
        ingest = TmdbIngest(writer, runtime.tmdb_client(writer))

        async def refresh_after_capture(
            session: AsyncSession,
            category_id: uuid.UUID,
            subject_kind: Literal["episode", "title"],
            subject_ids: frozenset[uuid.UUID],
        ) -> PlaybackQueueSnapshot:
            snapshot = await capture_playback_queue(session, category_id, subject_kind, subject_ids)
            known = await ingest._episode_index(episode.title_id)
            with pytest.raises(EpisodeOrderBusyError):
                await ingest._stored_episodes(episode.title_id, episode.season_id, _details(episode, 4), known)
            await writer.rollback()
            return snapshot

        monkeypatch.setattr(playback_events, "capture_playback_queue", refresh_after_capture)
        result = await playback_events.record_playback_event(reader, _completion(episode), entry.id, file.id)
        receipt = await reader.scalar(select(PlaybackCompletion))
        assert receipt is not None
        assert receipt.occurrence_snapshot[0]["tmdb_key"] == result.tmdb_key == "tv:999:s1:e1"
        current = await capture_playback_queue(reader, entry.category_id, "episode", frozenset({episode.id}))
        assert receipt.queue_fingerprint == current.fingerprint


async def test_tmdb_writer_first_refuses_completion_then_retry_captures_the_fresh_pair(
    engine: AsyncEngine,
    tmdb_playback: tuple[CuratedEntry, JellyfinItem, Episode, IngestRuntime],
) -> None:
    entry, file, episode, runtime = tmdb_playback
    async with AsyncSession(engine) as writer, AsyncSession(engine) as reader:
        ingest = TmdbIngest(writer, runtime.tmdb_client(writer))
        await ingest._stored_episodes(
            episode.title_id, episode.season_id, _details(episode, 4), await ingest._episode_index(episode.title_id)
        )
        with pytest.raises(PlaybackStateError, match="numbering is changing"):
            await asyncio.wait_for(
                playback_events.record_playback_event(reader, _completion(episode), entry.id, file.id), timeout=1
            )
        assert await reader.scalar(select(func.count()).select_from(WatchEvent)) == 0
        assert await reader.scalar(select(func.count()).select_from(PlaybackCompletion)) == 0
        await reader.rollback()
        await writer.commit()
        result = await playback_events.record_playback_event(reader, _completion(episode), entry.id, file.id)
        receipt = await reader.scalar(select(PlaybackCompletion))
        assert receipt is not None
        assert receipt.occurrence_snapshot[0]["tmdb_key"] == result.tmdb_key == "tv:999:s1:e4"
        current = await capture_playback_queue(reader, entry.category_id, "episode", frozenset({episode.id}))
        assert receipt.queue_fingerprint == current.fingerprint


@pytest.mark.parametrize("empty", [False, True])
async def test_unchanged_or_empty_episode_payload_needs_no_lock_or_dml(
    engine: AsyncEngine,
    tmdb_playback: tuple[CuratedEntry, JellyfinItem, Episode, IngestRuntime],
    empty: bool,
) -> None:
    _, _, episode, runtime = tmdb_playback
    details = _details(episode, 1)
    if empty:
        details = details.model_copy(update={"episodes": ()})
    async with AsyncSession(engine) as reader, AsyncSession(engine) as writer:
        assert await try_episode_order_locks(reader, [episode.title_id], shared=True)
        ingest = TmdbIngest(writer, runtime.tmdb_client(writer))
        known = await ingest._episode_index(episode.title_id)
        with counted_statements(engine) as statements:
            result = await ingest._stored_episodes(episode.title_id, episode.season_id, details, known)
        assert statements == []
        assert result.inserted == result.updated == 0
        assert result.unchanged == (0 if empty else 1)
