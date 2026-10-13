from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clients.jellyfin_client import JellyfinClient
from tv_watchlist.data.enums import Availability, ResolutionState, UnitKind
from tv_watchlist.data.models import CuratedEntry
from tv_watchlist.services.availability_result import AvailabilityResult
from tv_watchlist.services.entry_availability import EntryAvailability
from tv_watchlist.services.episode_match import MatchState, episodes_for_entries
from tv_watchlist.services.library_selections import library_selections_for

JELLYFIN_UNCONFIGURED_NOTICE: Final[str] = "Jellyfin is not configured"
JELLYFIN_UNREACHABLE_NOTICE: Final[str] = "Jellyfin unreachable"
NOT_IN_LIBRARY: Final[EntryAvailability] = EntryAvailability(availability=Availability.NOT_IN_LIBRARY)
AMBIGUOUS: Final[EntryAvailability] = EntryAvailability(availability=Availability.AMBIGUOUS)


async def availability_for(
    session: AsyncSession, client: JellyfinClient | None, entries: Sequence[CuratedEntry]
) -> AvailabilityResult:
    """Compute a page with one health probe, one title lookup and one batched episode join."""
    result = {entry.id: NOT_IN_LIBRARY for entry in entries}
    if not entries:
        return AvailabilityResult(entries=result)
    if client is None or not client.configured:
        return AvailabilityResult(entries=result, notice=JELLYFIN_UNCONFIGURED_NOTICE)
    if not await client.health():
        return AvailabilityResult(entries=result, notice=JELLYFIN_UNREACHABLE_NOTICE)
    resolved = [
        entry
        for entry in entries
        if entry.title_id is not None and entry.resolution_state in (ResolutionState.AUTO, ResolutionState.CONFIRMED)
    ]
    selections = await library_selections_for(session, {entry.title_id for entry in resolved if entry.title_id})
    episodes = [entry for entry in resolved if entry.unit_kind is not UnitKind.MOVIE]
    matches = await episodes_for_entries(session, episodes, selections=selections)
    for entry in resolved:
        selected = selections[entry.title_id]
        if entry.unit_kind is not UnitKind.MOVIE:
            states = {match.state for match in matches[entry.id]}
            if MatchState.AMBIGUOUS in states:
                result[entry.id] = AMBIGUOUS
                continue
            if states != {MatchState.MATCHED}:
                continue
        if selected.ambiguous:
            result[entry.id] = AMBIGUOUS
        elif selected.item_id is not None:
            result[entry.id] = EntryAvailability(
                availability=Availability.IN_LIBRARY, jellyfin_item_id=selected.item_id
            )
    return AvailabilityResult(entries=result)
