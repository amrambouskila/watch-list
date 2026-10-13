from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

import pytest
from episode_join_support import a_category, a_series_file, a_show, an_entry, an_episode_file, file_id
from ingest_support import order_ingest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tv_watchlist.data.enums import ExternalSource, UnitKind, WatchEventKind, WatchSubjectKind
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
from tv_watchlist.ingest.episode_orders import OrderSlot
from tv_watchlist.ingest.expansion import rebuild_items
from tv_watchlist.models.playback_queue_snapshot import PlaybackQueueSnapshot
from tv_watchlist.models.watch_event_create import WatchEventCreate
from tv_watchlist.services import playback_events
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.playback_queue_snapshot import capture_playback_queue


@dataclass(frozen=True)
class _NumberedPlayback:
    entry: CuratedEntry
    file: JellyfinItem
    title_ids: tuple[uuid.UUID, uuid.UUID]
    episodes: tuple[tuple[uuid.UUID, ...], tuple[uuid.UUID, ...]]

    def body(self) -> WatchEventCreate:
        return WatchEventCreate(
            subject_kind=WatchSubjectKind.EPISODE,
            subject_id=self.episodes[0][0],
            kind=WatchEventKind.COMPLETED,
            position_seconds=300,
            runtime_seconds=300,
        )

    def slots(self, index: int, *, changed: bool = True) -> tuple[OrderSlot, ...]:
        first, second, third = self.episodes[index]
        ordered = (first, third, second) if changed else (first, second, third)
        return tuple(OrderSlot(episode, number, 1, number) for number, episode in enumerate(ordered, start=1))


@pytest.fixture
async def numbered_playback(engine: AsyncEngine) -> AsyncIterator[_NumberedPlayback]:
    async with AsyncSession(engine, expire_on_commit=False) as seed:
        category = await a_category(seed, f"numbering-{uuid.uuid4()}")
        selected = await a_show(seed, "Selected show", episodes=3, tmdb_id=999)
        other = await a_show(seed, "Interleaved show", episodes=3, tmdb_id=998)
        entry = await an_entry(seed, category, title_id=selected.id, unit_kind=UnitKind.SERIES)
        await an_entry(seed, category, title_id=other.id, unit_kind=UnitKind.SERIES, position=2)
        await rebuild_items(seed, category.id)
        series = await a_series_file(seed, jellyfin_id=file_id(100), name=selected.name, tmdb_id=selected.tmdb_id)
        file = await an_episode_file(seed, series_jellyfin_id=series.jellyfin_id, season=1, number=1, number_end=2)
        first_episodes = tuple(
            await seed.scalars(
                select(Episode.id).where(Episode.title_id == selected.id).order_by(Episode.episode_number)
            )
        )
        other_episodes = tuple(
            await seed.scalars(select(Episode.id).where(Episode.title_id == other.id).order_by(Episode.episode_number))
        )
        await seed.commit()
    try:
        yield _NumberedPlayback(entry, file, (selected.id, other.id), (first_episodes, other_episodes))
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(CuratedEntry).where(CuratedEntry.category_id == category.id))
            await cleanup.execute(delete(Category).where(Category.id == category.id))
            await cleanup.execute(delete(Title).where(Title.id.in_((selected.id, other.id))))
            await cleanup.execute(delete(JellyfinItem).where(JellyfinItem.id.in_((file.id, series.id))))
            await cleanup.commit()


@pytest.mark.parametrize("title_index", [0, 1])
@pytest.mark.parametrize("changed", [False, True])
async def test_real_numbering_writer_cannot_change_or_compare_evidence_between_coverage_and_queue_capture(
    engine: AsyncEngine,
    numbered_playback: _NumberedPlayback,
    monkeypatch: pytest.MonkeyPatch,
    title_index: int,
    changed: bool,
) -> None:
    context = numbered_playback
    async with AsyncSession(engine) as reader, AsyncSession(engine) as writer:

        async def race_before_capture(
            session: AsyncSession,
            category_id: uuid.UUID,
            subject_kind: Literal["episode", "title"],
            subject_ids: frozenset[uuid.UUID],
        ) -> PlaybackQueueSnapshot:
            ingest, _ = order_ingest(writer)
            with pytest.raises(EpisodeOrderBusyError):
                await asyncio.wait_for(
                    ingest._stored_ordering(
                        context.title_ids[title_index],
                        "aired",
                        "",
                        ExternalSource.TMDB,
                        context.slots(title_index, changed=changed),
                    ),
                    timeout=1,
                )
            await writer.rollback()
            return await capture_playback_queue(session, category_id, subject_kind, subject_ids)

        monkeypatch.setattr(playback_events, "capture_playback_queue", race_before_capture)
        await playback_events.record_playback_event(reader, context.body(), context.entry.id, context.file.id)
        assert set(await reader.scalars(select(WatchEvent.episode_id))) == set(context.episodes[0][:2])
        receipt = await reader.scalar(select(PlaybackCompletion))
        assert receipt is not None
        snapshot = await capture_playback_queue(
            reader, context.entry.category_id, "episode", frozenset(context.episodes[0][:2])
        )
        assert receipt.queue_fingerprint == snapshot.fingerprint


async def test_writer_first_refuses_player_before_events_then_retry_uses_new_coverage(
    engine: AsyncEngine,
    numbered_playback: _NumberedPlayback,
) -> None:
    context = numbered_playback
    async with AsyncSession(engine) as writer, AsyncSession(engine) as reader:
        ingest, _ = order_ingest(writer)
        await ingest._stored_ordering(context.title_ids[0], "aired", "", ExternalSource.TMDB, context.slots(0))
        with pytest.raises(PlaybackStateError, match="numbering is changing"):
            await asyncio.wait_for(
                playback_events.record_playback_event(
                    reader,
                    context.body(),
                    context.entry.id,
                    context.file.id,
                ),
                timeout=1,
            )
        assert await reader.scalar(select(func.count()).select_from(WatchEvent)) == 0
        assert await reader.scalar(select(func.count()).select_from(PlaybackCompletion)) == 0
        await reader.rollback()
        await writer.commit()
        await playback_events.record_playback_event(reader, context.body(), context.entry.id, context.file.id)
        assert set(await reader.scalars(select(WatchEvent.episode_id))) == {
            context.episodes[0][0],
            context.episodes[0][2],
        }
        receipt = await reader.scalar(select(PlaybackCompletion))
        assert receipt is not None
        current = await capture_playback_queue(
            reader, context.entry.category_id, "episode", frozenset(context.episodes[0][::2])
        )
        assert receipt.queue_fingerprint == current.fingerprint


async def test_opposing_multi_title_writers_refuse_instead_of_waiting_and_rollback_earlier_episode_changes(
    engine: AsyncEngine,
    numbered_playback: _NumberedPlayback,
) -> None:
    context = numbered_playback
    async with AsyncSession(engine) as first, AsyncSession(engine) as second:
        first_ingest, _ = order_ingest(first)
        second_ingest, _ = order_ingest(second)
        await first_ingest._stored_ordering(context.title_ids[0], "aired", "", ExternalSource.TMDB, context.slots(0))
        await second_ingest._stored_ordering(context.title_ids[1], "aired", "", ExternalSource.TMDB, context.slots(1))
        await first.execute(
            update(Episode).where(Episode.id == context.episodes[0][0]).values(name="Uncommitted change")
        )
        with pytest.raises(EpisodeOrderBusyError):
            await asyncio.wait_for(
                first_ingest._stored_ordering(
                    context.title_ids[1],
                    "aired",
                    "",
                    ExternalSource.TMDB,
                    context.slots(1),
                ),
                timeout=1,
            )
        with pytest.raises(EpisodeOrderBusyError):
            await asyncio.wait_for(
                second_ingest._stored_ordering(
                    context.title_ids[0],
                    "aired",
                    "",
                    ExternalSource.TMDB,
                    context.slots(0),
                ),
                timeout=1,
            )
        await first.rollback()
        await second.rollback()
        assert await first.scalar(select(Episode.name).where(Episode.id == context.episodes[0][0])) is None
        await playback_events.record_playback_event(first, context.body(), context.entry.id, context.file.id)
        assert set(await first.scalars(select(WatchEvent.episode_id))) == set(context.episodes[0][:2])


async def test_prior_episode_key_update_cannot_form_a_foreign_key_advisory_deadlock(
    engine: AsyncEngine,
    numbered_playback: _NumberedPlayback,
) -> None:
    context = numbered_playback
    async with AsyncSession(engine) as reader, AsyncSession(engine) as writer:
        assert await try_episode_order_locks(reader, context.title_ids, shared=True)
        await writer.execute(update(Episode).where(Episode.id == context.episodes[0][0]).values(episode_number=4))
        waiting = asyncio.create_task(
            playback_events.record_playback_event(
                reader,
                context.body(),
                context.entry.id,
                context.file.id,
            )
        )
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(waiting), timeout=0.1)
            ingest, _ = order_ingest(writer)
            with pytest.raises(EpisodeOrderBusyError):
                await asyncio.wait_for(
                    ingest._stored_ordering(
                        context.title_ids[0],
                        "aired",
                        "",
                        ExternalSource.TMDB,
                        context.slots(0),
                    ),
                    timeout=1,
                )
            await writer.rollback()
            result = await asyncio.wait_for(waiting, timeout=2)
            assert result.tmdb_key == "tv:999:s1:e1"
            assert await reader.scalar(select(Episode.episode_number).where(Episode.id == context.episodes[0][0])) == 1
            assert set(await reader.scalars(select(WatchEvent.episode_id))) == set(context.episodes[0][:2])
        finally:
            if not waiting.done():
                waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)


async def test_numbering_contention_keeps_the_existing_typed_http_conflict_without_recording_events(
    engine: AsyncEngine,
    numbered_playback: _NumberedPlayback,
    catalog: Catalog,
) -> None:
    from httpx import ASGITransport, AsyncClient

    from database_support import JoiningSessionFactory
    from tv_watchlist.api.dependencies import get_catalog
    from tv_watchlist.data.session import get_session, get_session_factory
    from tv_watchlist.main import create_app

    context = numbered_playback
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            async with (
                AsyncSession(engine) as writer,
                AsyncSession(
                    bind=connection,
                    join_transaction_mode="create_savepoint",
                ) as reader,
            ):
                ingest, _ = order_ingest(writer)
                await ingest._stored_ordering(context.title_ids[0], "aired", "", ExternalSource.TMDB, context.slots(0))
                app = create_app()
                app.dependency_overrides[get_session] = lambda: reader
                app.dependency_overrides[get_catalog] = lambda: catalog
                app.dependency_overrides[get_session_factory] = JoiningSessionFactory(reader)
                params = {"playback_entry_id": str(context.entry.id), "jellyfin_item_id": str(context.file.id)}
                async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
                    response = await client.post(
                        "/api/watch-events", params=params, json=context.body().model_dump(mode="json")
                    )
                    assert response.status_code == 409
                    assert response.json()["error"] == "PlaybackStateError"
                    assert await reader.scalar(select(func.count()).select_from(WatchEvent)) == 0
                    assert await reader.scalar(select(func.count()).select_from(PlaybackCompletion)) == 0
                    await reader.rollback()
                    await writer.rollback()
                    retry = await client.post(
                        "/api/watch-events", params=params, json=context.body().model_dump(mode="json")
                    )
                    assert retry.status_code == 201
                    assert await reader.scalar(select(func.count()).select_from(WatchEvent)) == 2
                    assert await reader.scalar(select(func.count()).select_from(PlaybackCompletion)) == 1
        finally:
            await transaction.rollback()
