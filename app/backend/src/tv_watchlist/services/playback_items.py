from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clients.jellyfin_client import JellyfinClient
from tv_watchlist.constants import MAX_ENTRIES_PAGE_SIZE
from tv_watchlist.data.enums import Availability, JellyfinItemKind, ResolutionState
from tv_watchlist.data.errors import EntryNotFoundError, JellyfinUnavailableError
from tv_watchlist.data.models import Category, CuratedEntry, CuratedEntryItem, JellyfinItem
from tv_watchlist.ingest.episode_orders import NO_LABEL
from tv_watchlist.models.playback_item_read import PlaybackItemRead
from tv_watchlist.services.episode_match import MatchState, episodes_for_entries
from tv_watchlist.services.library_selections import library_selections_for


async def items_for_entry(
    session: AsyncSession,
    client: JellyfinClient,
    entry_id: uuid.UUID,
    *,
    limit: int = MAX_ENTRIES_PAGE_SIZE,
    offset: int = 0,
) -> list[PlaybackItemRead]:
    """Read an ordered queue page without dropping unavailable slots or deriving another numbering."""
    entry = await session.scalar(
        select(CuratedEntry)
        .join(Category, Category.id == CuratedEntry.category_id)
        .where(CuratedEntry.id == entry_id, CuratedEntry.removed_at.is_(None), Category.retired_at.is_(None))
    )
    if entry is None:
        raise EntryNotFoundError(str(entry_id))
    if not client.configured or client.closed or not await client.health():
        raise JellyfinUnavailableError("Jellyfin unavailable")
    slots = list(
        await session.scalars(
            select(CuratedEntryItem)
            .where(CuratedEntryItem.curated_entry_id == entry_id)
            .order_by(CuratedEntryItem.position_in_entry)
            .limit(limit)
            .offset(offset)
        )
    )
    resolved = entry.resolution_state in (ResolutionState.AUTO, ResolutionState.CONFIRMED)
    title_ids = {slot.movie_title_id for slot in slots if slot.movie_title_id is not None}
    if entry.title_id is not None:
        title_ids.add(entry.title_id)
    selections = await library_selections_for(session, title_ids) if resolved and slots else {}
    episode_matches = (
        (await episodes_for_entries(session, [entry], selections=selections))[entry_id]
        if resolved and any(slot.episode_id is not None for slot in slots)
        else []
    )
    matches = {match.item_id: match for match in episode_matches}
    movie_ids = {
        selections[slot.movie_title_id].item_id
        for slot in slots
        if slot.movie_title_id in selections and selections[slot.movie_title_id].item_id is not None
    }
    live_movies = (
        set(
            await session.scalars(
                select(JellyfinItem.id).where(
                    JellyfinItem.id.in_(movie_ids),
                    JellyfinItem.kind == JellyfinItemKind.MOVIE,
                    JellyfinItem.removed_at.is_(None),
                )
            )
        )
        if movie_ids
        else set()
    )
    result: list[PlaybackItemRead] = []
    for slot in slots:
        availability = Availability.NOT_IN_LIBRARY
        file_id = None
        match = matches.get(slot.id)
        if match is not None:
            if match.state is MatchState.AMBIGUOUS:
                availability = Availability.AMBIGUOUS
            elif match.state is MatchState.MATCHED:
                availability, file_id = Availability.IN_LIBRARY, match.jellyfin_item_id
        elif slot.movie_title_id in selections:
            selected = selections[slot.movie_title_id]
            if selected.ambiguous:
                availability = Availability.AMBIGUOUS
            elif selected.item_id in live_movies:
                availability, file_id = Availability.IN_LIBRARY, selected.item_id
        result.append(
            PlaybackItemRead(
                id=slot.id,
                entry_id=entry_id,
                episode_id=slot.episode_id,
                movie_title_id=slot.movie_title_id,
                position_in_entry=slot.position_in_entry,
                absolute_position=slot.absolute_position,
                availability=availability,
                jellyfin_item_id=file_id,
                order_type=match.order_type if match is not None else None,
                order_label=match.order_label if match is not None else NO_LABEL,
                covers_range=match.covers_range if match is not None else False,
            )
        )
    return result
