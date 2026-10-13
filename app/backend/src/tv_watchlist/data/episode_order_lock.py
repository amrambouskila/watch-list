"""Nonblocking transaction gates for shared playback reads and exclusive provider numbering writes."""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.constants import EPISODE_ORDER_LOCK_NAMESPACE


async def try_episode_order_locks(session: AsyncSession, title_ids: Collection[UUID], *, shared: bool) -> bool:
    """Acquire a batch without waiting; on False, the caller must roll back the whole transaction."""
    if not title_ids:
        return True
    statement = text(
        "SELECT bool_and(pg_try_advisory_xact_lock_shared(:namespace, hashtext(title_id))) "
        "FROM unnest(CAST(:title_ids AS text[])) AS titles(title_id)"
        if shared
        else "SELECT bool_and(pg_try_advisory_xact_lock(:namespace, hashtext(title_id))) "
        "FROM unnest(CAST(:title_ids AS text[])) AS titles(title_id)"
    )
    return bool(
        await session.scalar(
            statement,
            {"namespace": EPISODE_ORDER_LOCK_NAMESPACE, "title_ids": sorted({str(title_id) for title_id in title_ids})},
        )
    )
