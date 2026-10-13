from __future__ import annotations

import asyncio
import uuid

import pytest
from episode_join_support import a_category, an_entry
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tv_watchlist.clock import utcnow
from tv_watchlist.data.enums import ResolutionState, UnitKind
from tv_watchlist.data.errors import EntryNotFoundError
from tv_watchlist.data.models import Category, CuratedEntry
from tv_watchlist.services.locked_curated_entry import locked_curated_entry


@pytest.mark.parametrize("missing", ["unknown", "entry", "category"])
async def test_only_live_entries_of_live_categories_can_record_or_project(
    db_session: AsyncSession,
    missing: str,
) -> None:
    category = await a_category(db_session)
    entry = await an_entry(db_session, category, title_id=None, unit_kind=UnitKind.UNKNOWN)
    if missing == "entry":
        entry.removed_at = utcnow()
    if missing == "category":
        category.retired_at = utcnow()
    await db_session.flush()
    with pytest.raises(EntryNotFoundError):
        await locked_curated_entry(db_session, uuid.uuid4() if missing == "unknown" else entry.id)


@pytest.mark.parametrize("commit", [False, True])
async def test_snapshot_lock_survives_until_the_callers_transaction_ends(engine: AsyncEngine, commit: bool) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as seed:
        category = await a_category(seed, slug=f"lock-{uuid.uuid4()}")
        entry = await an_entry(seed, category, title_id=None, unit_kind=UnitKind.UNKNOWN)
        await seed.commit()
    try:
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            await locked_curated_entry(first, entry.id)
            waiting = asyncio.create_task(locked_curated_entry(second, entry.id))
            try:
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(waiting), timeout=0.1)
                await first.commit() if commit else await first.rollback()
                other, owner = await asyncio.wait_for(waiting, timeout=2)
                assert other.id == entry.id and owner.id == category.id
            finally:
                if not waiting.done():
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(CuratedEntry).where(CuratedEntry.id == entry.id))
            await cleanup.execute(delete(Category).where(Category.id == category.id))
            await cleanup.commit()


@pytest.mark.parametrize("changed", ["resolution", "removed", "retired", "category"])
async def test_waiting_for_the_category_lock_reads_entry_changes_committed_by_its_previous_owner(
    engine: AsyncEngine,
    changed: str,
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as seed:
        category = await a_category(seed, slug=f"waiting-{uuid.uuid4()}")
        other = await a_category(seed, slug=f"other-{uuid.uuid4()}")
        entry = await an_entry(seed, category, title_id=None, unit_kind=UnitKind.UNKNOWN)
        await seed.commit()
    try:
        async with AsyncSession(engine) as writer, AsyncSession(engine) as reader:
            await writer.scalar(select(Category.id).where(Category.id == category.id).with_for_update())
            if changed == "resolution":
                await writer.execute(
                    update(CuratedEntry)
                    .where(CuratedEntry.id == entry.id)
                    .values(
                        resolution_state=ResolutionState.UNRESOLVED,
                    )
                )
            elif changed == "removed":
                await writer.execute(
                    update(CuratedEntry).where(CuratedEntry.id == entry.id).values(removed_at=utcnow())
                )
            elif changed == "retired":
                await writer.execute(update(Category).where(Category.id == category.id).values(retired_at=utcnow()))
            else:
                await writer.execute(
                    update(CuratedEntry).where(CuratedEntry.id == entry.id).values(category_id=other.id)
                )
            await writer.execute(update(Category).where(Category.id == category.id).values(sheet_title="Changed sheet"))
            waiting = asyncio.create_task(locked_curated_entry(reader, entry.id))
            try:
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(waiting), timeout=0.1)
                await writer.commit()
                if changed == "resolution":
                    fresh_entry, fresh_category = await asyncio.wait_for(waiting, timeout=2)
                    assert fresh_entry.resolution_state is ResolutionState.UNRESOLVED
                    assert fresh_category.sheet_title == "Changed sheet"
                else:
                    with pytest.raises(EntryNotFoundError):
                        await asyncio.wait_for(waiting, timeout=2)
            finally:
                if not waiting.done():
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(CuratedEntry).where(CuratedEntry.id == entry.id))
            await cleanup.execute(delete(Category).where(Category.id.in_((category.id, other.id))))
            await cleanup.commit()
