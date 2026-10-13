"""The rollback fixture itself: a test may commit, and the database is still clean afterwards."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tv_watchlist.data.models import Category


async def test_a_committed_row_is_gone_once_the_fixture_rolls_back(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    """A commit inside a test releases a SAVEPOINT and never reaches the database.

    Asserting the instance survived the commit would prove only `expire_on_commit=False`. The proof has to
    come from OUTSIDE the fixture's transaction, so it opens a second connection: the outer transaction is
    still open and uncommitted there, so a committed-but-savepointed row is invisible to it.
    """
    category = Category(slug=f"probe-{uuid.uuid4().hex}", file_name="Probe.xlsx", sheet_title="Probe", accent="#1F2937")
    db_session.add(category)
    await db_session.flush()
    await db_session.commit()

    async with engine.connect() as outside:
        visible = await outside.scalar(text("SELECT count(*) FROM category WHERE id = :id"), {"id": category.id})
    assert visible == 0
