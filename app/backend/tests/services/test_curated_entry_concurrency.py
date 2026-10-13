from __future__ import annotations

import asyncio
import uuid

import pytest
from episode_join_support import a_category, a_film, an_entry, file_id
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import selectinload

from review_support import tmdb_runtime
from tv_watchlist.clock import utcnow
from tv_watchlist.config import Settings
from tv_watchlist.data.enums import JellyfinItemKind, ResolutionState, UnitKind, WatchEventKind, WatchSubjectKind
from tv_watchlist.data.errors import EntryNotFoundError, ResolutionConflictError
from tv_watchlist.data.models import Category, CuratedEntry, JellyfinItem, Title
from tv_watchlist.ingest.expansion import rebuild_items
from tv_watchlist.models.resolution_update import ResolutionUpdate
from tv_watchlist.models.watch_event_create import WatchEventCreate
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.locked_curated_entry import locked_curated_entry
from tv_watchlist.services.playback_events import record_playback_event
from tv_watchlist.services.resolution_review import NOT_CONFIGURED, apply_resolution, retry_resolution


@pytest.mark.parametrize("action", ["confirm", "reject", "retry"])
async def test_review_waits_for_the_actual_player_snapshot_transaction(
    engine: AsyncEngine, settings: Settings, catalog: Catalog, action: str
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as seed:
        category = await a_category(seed, f"review-fence-{uuid.uuid4()}")
        title = await a_film(seed, "A fenced movie", tmdb_id=999)
        entry = await an_entry(seed, category, title_id=title.id, unit_kind=UnitKind.MOVIE)
        file = JellyfinItem(jellyfin_id=file_id(1), kind=JellyfinItemKind.MOVIE, name=title.name, tmdb_id=999)
        seed.add(file)
        await seed.flush()
        await rebuild_items(seed, category.id)
        await seed.commit()
    runtime = tmdb_runtime(settings, catalog, engine, token=None)
    try:
        async with AsyncSession(engine) as player, AsyncSession(engine) as reviewer:
            await record_playback_event(
                player,
                WatchEventCreate(
                    subject_kind=WatchSubjectKind.TITLE,
                    subject_id=title.id,
                    kind=WatchEventKind.PROGRESSED,
                    position_seconds=60,
                    runtime_seconds=300,
                ),
                entry.id,
                file.id,
            )
            operation = (
                retry_resolution(reviewer, settings, runtime, entry.id)
                if action == "retry"
                else apply_resolution(
                    reviewer, settings, runtime, entry.id, ResolutionUpdate.model_validate({"action": action})
                )
            )
            waiting = asyncio.create_task(operation)
            try:
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(waiting), timeout=0.1)
                await player.rollback()
                if action == "retry":
                    with pytest.raises(ResolutionConflictError, match=NOT_CONFIGURED):
                        await asyncio.wait_for(waiting, timeout=2)
                else:
                    result = await asyncio.wait_for(waiting, timeout=2)
                    assert result.resolution_state is (
                        ResolutionState.CONFIRMED if action == "confirm" else ResolutionState.REJECTED
                    )
            finally:
                if not waiting.done():
                    waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)
    finally:
        await runtime.aclose()
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(CuratedEntry).where(CuratedEntry.id == entry.id))
            await cleanup.execute(delete(Category).where(Category.id == category.id))
            await cleanup.execute(delete(Title).where(Title.id == title.id))
            await cleanup.execute(delete(JellyfinItem).where(JellyfinItem.id == file.id))
            await cleanup.commit()


async def test_review_refreshes_a_held_entry_and_its_eager_title_after_waiting(
    engine: AsyncEngine, settings: Settings, catalog: Catalog
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as seed:
        category = await a_category(seed, f"fresh-review-{uuid.uuid4()}")
        previous = await a_film(seed, "Previous title")
        current = await a_film(seed, "Current title")
        entry = await an_entry(seed, category, title_id=previous.id, unit_kind=UnitKind.MOVIE)
        await seed.commit()
    runtime = tmdb_runtime(settings, catalog, engine, token=None)
    try:
        async with AsyncSession(engine) as owner, AsyncSession(engine) as reviewer:
            held = await reviewer.scalar(
                select(CuratedEntry).where(CuratedEntry.id == entry.id).options(selectinload(CuratedEntry.title))
            )
            assert held is not None and held.title is not None and held.title.id == previous.id
            await locked_curated_entry(owner, entry.id)
            await owner.execute(
                update(CuratedEntry)
                .where(CuratedEntry.id == entry.id)
                .values(title_id=current.id, resolution_note="Fresh resolver evidence")
            )
            waiting = asyncio.create_task(
                apply_resolution(reviewer, settings, runtime, entry.id, ResolutionUpdate(action="confirm"))
            )
            try:
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(waiting), timeout=0.1)
                await owner.commit()
                result = await asyncio.wait_for(waiting, timeout=2)
                assert result.title is not None and result.title.id == current.id
                assert result.resolution_note.startswith("Fresh resolver evidence")
                assert held.title is not None and held.title.id == current.id
            finally:
                if not waiting.done():
                    waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)
    finally:
        await runtime.aclose()
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(CuratedEntry).where(CuratedEntry.id == entry.id))
            await cleanup.execute(delete(Category).where(Category.id == category.id))
            await cleanup.execute(delete(Title).where(Title.id.in_((previous.id, current.id))))
            await cleanup.commit()


@pytest.mark.parametrize("retry", [False, True])
async def test_review_refuses_an_entry_of_a_retired_category(
    db_session: AsyncSession, settings: Settings, catalog: Catalog, engine: AsyncEngine, retry: bool
) -> None:
    category = await a_category(db_session)
    entry = await an_entry(db_session, category, title_id=None, unit_kind=UnitKind.UNKNOWN)
    category.retired_at = utcnow()
    await db_session.flush()
    runtime = tmdb_runtime(settings, catalog, engine, token=None)
    try:
        with pytest.raises(EntryNotFoundError):
            if retry:
                await retry_resolution(db_session, settings, runtime, entry.id)
            else:
                await apply_resolution(db_session, settings, runtime, entry.id, ResolutionUpdate(action="confirm"))
    finally:
        await runtime.aclose()
