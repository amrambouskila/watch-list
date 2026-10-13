from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from episode_join_support import a_category, a_film, a_series_file, a_show, an_entry, an_episode_file, file_id
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tv_watchlist.data.enums import (
    JellyfinItemKind,
    ResolutionState,
    UnitKind,
    WatchEventKind,
    WatchEventSource,
    WatchSubjectKind,
)
from tv_watchlist.data.errors import PlaybackStateError
from tv_watchlist.data.models import (
    Category,
    CuratedEntry,
    EpisodeOrder,
    JellyfinItem,
    PlaybackCompletion,
    PlaybackCompletionEvent,
    Title,
    WatchEvent,
)
from tv_watchlist.ingest.expansion import rebuild_items
from tv_watchlist.models.watch_event_create import WatchEventCreate
from tv_watchlist.services.playback_events import record_playback_event
from tv_watchlist.services.watch_events import record_watch_event


@pytest.fixture
async def range_context(db_session: AsyncSession) -> tuple[CuratedEntry, JellyfinItem, list[EpisodeOrder]]:
    category = await a_category(db_session)
    title = await a_show(db_session, "A range", episodes=3, tmdb_id=999)
    orders = list(await db_session.scalars(select(EpisodeOrder).order_by(EpisodeOrder.sequence)))
    for order in orders:
        order.order_type, order.label = "regional", "Stored order"
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
        order_label="Stored order",
    )
    series = await a_series_file(db_session, jellyfin_id=file_id(100), name=title.name, tmdb_id=title.tmdb_id)
    file = await an_episode_file(db_session, series_jellyfin_id=series.jellyfin_id, season=9, number=11, number_end=13)
    await rebuild_items(db_session, category.id)
    return entry, file, orders


def completion_body(subject_id: uuid.UUID) -> WatchEventCreate:
    return WatchEventCreate(
        subject_kind=WatchSubjectKind.EPISODE,
        subject_id=subject_id,
        kind=WatchEventKind.COMPLETED,
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
        position_seconds=301,
        runtime_seconds=300,
    )


async def test_receipt_records_exact_membership_and_actual_numbering_for_each_same_stamp_completion(
    db_session: AsyncSession,
    range_context: tuple[CuratedEntry, JellyfinItem, list[EpisodeOrder]],
) -> None:
    entry, file, orders = range_context
    selected_ids = []
    for _ in range(2):
        result = await record_playback_event(db_session, completion_body(orders[1].episode_id), entry.id, file.id)
        selected_ids.append(result.id)
    receipts = list(await db_session.scalars(select(PlaybackCompletion)))
    assert len(receipts) == 2
    assert {receipt.selected_watch_event_id for receipt in receipts} == set(selected_ids)
    all_members: set[uuid.UUID] = set()
    for receipt in receipts:
        assert receipt.category_id == entry.category_id and receipt.source_entry_id == entry.id
        assert receipt.jellyfin_item_id_snapshot == file.id and receipt.jellyfin_id_snapshot == file.jellyfin_id
        assert (receipt.order_type, receipt.order_label) == ("regional", "Stored order")
        assert (receipt.parent_index_number, receipt.index_number, receipt.index_number_end) == (9, 11, 13)
        assert len(receipt.queue_fingerprint) == 64
        assert receipt.occurrence_snapshot == [
            {
                "entry_id": str(entry.id),
                "subject_kind": "episode",
                "subject_id_snapshot": str(orders[1].episode_id),
                "tmdb_key": "tv:999:s1:e2",
                "position_in_entry": 1,
            }
        ]
        members = list(
            await db_session.scalars(
                select(WatchEvent)
                .join(PlaybackCompletionEvent, PlaybackCompletionEvent.watch_event_id == WatchEvent.id)
                .where(PlaybackCompletionEvent.completion_id == receipt.id)
            )
        )
        assert len(members) == 3
        assert {event.episode_id for event in members} == {order.episode_id for order in orders}
        ids = {event.id for event in members}
        assert receipt.selected_watch_event_id in ids and ids.isdisjoint(all_members)
        all_members.update(ids)
        assert all(event.position_seconds == event.runtime_seconds == 300 for event in members)


@pytest.mark.parametrize("mode", ["progressed", "generic-ui", "generic-player"])
async def test_only_contextual_completed_player_events_create_receipts(
    db_session: AsyncSession,
    range_context: tuple[CuratedEntry, JellyfinItem, list[EpisodeOrder]],
    mode: str,
) -> None:
    entry, file, orders = range_context
    body = completion_body(orders[1].episode_id)
    if mode == "progressed":
        await record_playback_event(
            db_session, body.model_copy(update={"kind": WatchEventKind.PROGRESSED}), entry.id, file.id
        )
    else:
        await record_watch_event(
            db_session, body, source=WatchEventSource.PLAYER if mode == "generic-player" else WatchEventSource.UI
        )
    assert await db_session.scalar(select(func.count()).select_from(WatchEvent)) == 1
    assert await db_session.scalar(select(func.count()).select_from(PlaybackCompletion)) == 0
    assert await db_session.scalar(select(func.count()).select_from(PlaybackCompletionEvent)) == 0


@pytest.mark.parametrize("end", [None, 12])
async def test_single_episode_receipts_preserve_the_actual_optional_end_index(
    db_session: AsyncSession,
    range_context: tuple[CuratedEntry, JellyfinItem, list[EpisodeOrder]],
    end: int | None,
) -> None:
    entry, file, orders = range_context
    file.index_number, file.index_number_end = 12, end
    await db_session.flush()
    event = await record_playback_event(db_session, completion_body(orders[1].episode_id), entry.id, file.id)
    receipt = await db_session.scalar(select(PlaybackCompletion))
    assert receipt is not None and receipt.selected_watch_event_id == event.id
    assert receipt.index_number == 12 and receipt.index_number_end == end
    assert await db_session.scalar(select(func.count()).select_from(PlaybackCompletionEvent)) == 1
    assert await db_session.scalar(select(func.count()).select_from(WatchEvent)) == 1


async def test_movie_replays_create_distinct_receipts_without_episode_numbering(db_session: AsyncSession) -> None:
    category = await a_category(db_session)
    title = await a_film(db_session, "Movie", tmdb_id=999)
    first = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.MOVIE)
    selected = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.MOVIE, position=2)
    file = JellyfinItem(jellyfin_id=file_id(1), kind=JellyfinItemKind.MOVIE, name=title.name, tmdb_id=title.tmdb_id)
    db_session.add(file)
    await db_session.flush()
    await rebuild_items(db_session, category.id)
    body = completion_body(title.id).model_copy(update={"subject_kind": WatchSubjectKind.TITLE})
    for _ in range(2):
        await record_playback_event(db_session, body, selected.id, file.id)
    receipts = list(await db_session.scalars(select(PlaybackCompletion)))
    assert len(receipts) == 2
    for receipt in receipts:
        assert receipt.source_entry_id == selected.id
        assert receipt.order_type is None and receipt.order_label == ""
        assert receipt.parent_index_number is receipt.index_number is receipt.index_number_end is None
        assert [item["entry_id"] for item in receipt.occurrence_snapshot] == [str(first.id), str(selected.id)]
        assert (
            await db_session.scalar(
                select(func.count())
                .select_from(PlaybackCompletionEvent)
                .where(
                    PlaybackCompletionEvent.completion_id == receipt.id,
                )
            )
            == 1
        )


@pytest.mark.parametrize("table", ["playback_completion", "playback_completion_event"])
async def test_database_receipt_failure_rolls_back_every_sibling_event(
    db_session: AsyncSession,
    range_context: tuple[CuratedEntry, JellyfinItem, list[EpisodeOrder]],
    table: str,
) -> None:
    entry, file, orders = range_context
    await db_session.execute(
        text("""
        CREATE FUNCTION refuse_test_completion() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'test receipt refusal' USING ERRCODE = '23514'; END $$
    """)
    )
    await db_session.execute(
        text(f"""
        CREATE TRIGGER refuse_test_completion BEFORE INSERT ON {table}
        FOR EACH ROW EXECUTE FUNCTION refuse_test_completion()
    """)
    )
    with pytest.raises(IntegrityError, match="test receipt refusal"):
        async with db_session.begin_nested():
            await record_playback_event(db_session, completion_body(orders[1].episode_id), entry.id, file.id)
    for model in (WatchEvent, PlaybackCompletion, PlaybackCompletionEvent):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0


async def test_selection_refreshes_stale_identity_map_metadata_before_coverage(
    db_session: AsyncSession,
    range_context: tuple[CuratedEntry, JellyfinItem, list[EpisodeOrder]],
) -> None:
    entry, file, orders = range_context
    await db_session.execute(
        update(JellyfinItem)
        .where(JellyfinItem.id == file.id)
        .values(
            index_number=12,
            jellyfin_id=file_id(200),
        )
        .execution_options(synchronize_session=False)
    )
    assert file.index_number == 11
    await record_playback_event(db_session, completion_body(orders[1].episode_id), entry.id, file.id)
    receipt = await db_session.scalar(select(PlaybackCompletion))
    assert receipt is not None
    assert receipt.index_number == 12 and receipt.jellyfin_id_snapshot == file_id(200)
    assert set(await db_session.scalars(select(WatchEvent.episode_id))) == {order.episode_id for order in orders[1:]}


async def test_a_stale_entry_identity_cannot_complete_a_now_unresolved_subject(
    db_session: AsyncSession,
    range_context: tuple[CuratedEntry, JellyfinItem, list[EpisodeOrder]],
) -> None:
    entry, file, orders = range_context
    await db_session.execute(
        update(CuratedEntry)
        .where(CuratedEntry.id == entry.id)
        .values(
            resolution_state=ResolutionState.UNRESOLVED,
        )
        .execution_options(synchronize_session=False)
    )
    assert entry.resolution_state is ResolutionState.AUTO
    with pytest.raises(PlaybackStateError, match="resolved playback subject"):
        await record_playback_event(db_session, completion_body(orders[1].episode_id), entry.id, file.id)
    assert await db_session.scalar(select(func.count()).select_from(WatchEvent)) == 0


async def test_file_evidence_stays_locked_until_the_snapshot_transaction_ends(engine: AsyncEngine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as seed:
        category = await a_category(seed, f"file-lock-{uuid.uuid4()}")
        title = await a_film(seed, "A locked movie", tmdb_id=999)
        entry = await an_entry(seed, category, title_id=title.id, unit_kind=UnitKind.MOVIE)
        file = JellyfinItem(jellyfin_id=file_id(1), kind=JellyfinItemKind.MOVIE, name=title.name, tmdb_id=title.tmdb_id)
        seed.add(file)
        await seed.flush()
        await rebuild_items(seed, category.id)
        await seed.commit()
    try:
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            body = completion_body(title.id).model_copy(update={"subject_kind": WatchSubjectKind.TITLE})
            await record_playback_event(first, body, entry.id, file.id)
            waiting = asyncio.create_task(
                second.execute(update(JellyfinItem).where(JellyfinItem.id == file.id).values(jellyfin_id=file_id(2)))
            )
            try:
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(waiting), timeout=0.1)
                receipt = await first.scalar(select(PlaybackCompletion))
                assert receipt is not None and receipt.jellyfin_id_snapshot == file_id(1)
                await first.rollback()
                await asyncio.wait_for(waiting, timeout=2)
            finally:
                if not waiting.done():
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(CuratedEntry).where(CuratedEntry.id == entry.id))
            await cleanup.execute(delete(Category).where(Category.id == category.id))
            await cleanup.execute(delete(Title).where(Title.id == title.id))
            await cleanup.execute(delete(JellyfinItem).where(JellyfinItem.id == file.id))
            await cleanup.commit()
