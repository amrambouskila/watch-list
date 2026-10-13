from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.data.errors import EntryNotFoundError
from tv_watchlist.data.models import Category, CuratedEntry


async def locked_curated_entry(session: AsyncSession, entry_id: uuid.UUID) -> tuple[CuratedEntry, Category]:
    """Read fresh live curation under its category's transaction-scoped mutation fence."""
    category_id = await session.scalar(
        select(Category.id)
        .join(CuratedEntry, CuratedEntry.category_id == Category.id)
        .where(CuratedEntry.id == entry_id)
        .with_for_update(of=Category)
    )
    if category_id is None:
        raise EntryNotFoundError(str(entry_id))
    # A statement that waited for the category lock can still carry its older joined entry snapshot.
    found = (
        await session.execute(
            select(CuratedEntry, Category)
            .join(Category, Category.id == CuratedEntry.category_id)
            .where(
                CuratedEntry.id == entry_id,
                CuratedEntry.category_id == category_id,
                CuratedEntry.removed_at.is_(None),
                Category.retired_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
    ).first()
    if found is None:
        raise EntryNotFoundError(str(entry_id))
    return found[0], found[1]
