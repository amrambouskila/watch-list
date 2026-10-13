from __future__ import annotations

import uuid
from collections.abc import Collection
from itertools import groupby

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from tv_watchlist.data.enums import JellyfinItemKind, MediaType
from tv_watchlist.data.models import JellyfinItem, Title
from tv_watchlist.services.library_selection import LibrarySelection


async def library_selections_for(
    session: AsyncSession, title_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, LibrarySelection]:
    """Fetch exact provider-id candidates and remembered picks for a whole page in one statement."""
    if not title_ids:
        return {}
    remembered = aliased(JellyfinItem)
    statement = (
        select(
            Title.id.label("title_id"),
            JellyfinItem.id.label("item_id"),
            JellyfinItem.kind,
            JellyfinItem.jellyfin_id,
            JellyfinItem.series_jellyfin_id,
            JellyfinItem.removed_at,
            (JellyfinItem.id == Title.jellyfin_item_id).label("picked"),
        )
        .select_from(Title)
        .outerjoin(remembered, remembered.id == Title.jellyfin_item_id)
        .join(
            JellyfinItem,
            or_(
                and_(
                    JellyfinItem.tmdb_id == Title.tmdb_id,
                    JellyfinItem.removed_at.is_(None),
                    or_(
                        and_(Title.media_type == MediaType.TV, JellyfinItem.kind == JellyfinItemKind.SERIES),
                        and_(Title.media_type == MediaType.MOVIE, JellyfinItem.kind == JellyfinItemKind.MOVIE),
                    ),
                ),
                JellyfinItem.id == Title.jellyfin_item_id,
                and_(
                    remembered.kind == JellyfinItemKind.EPISODE,
                    remembered.removed_at.is_(None),
                    JellyfinItem.kind == JellyfinItemKind.SERIES,
                    JellyfinItem.jellyfin_id == remembered.series_jellyfin_id,
                    JellyfinItem.removed_at.is_(None),
                ),
            ),
        )
        .where(Title.id.in_(title_ids))
        .order_by(Title.id, JellyfinItem.id)
    )
    rows = (await session.execute(statement)).all()
    selections = {title_id: LibrarySelection() for title_id in title_ids}
    selections.update(
        (title_id, LibrarySelection.from_rows(tuple(group)))
        for title_id, group in groupby(rows, key=lambda row: row.title_id)
    )
    return selections
