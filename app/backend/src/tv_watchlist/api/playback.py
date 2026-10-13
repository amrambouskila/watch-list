from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.api.dependencies import get_catalog, get_jellyfin_client
from tv_watchlist.api.playback_response import PlaybackResponse
from tv_watchlist.clients.jellyfin_client import JellyfinClient
from tv_watchlist.constants import MAX_ENTRIES_PAGE_SIZE, RANGE_HEADER_PATTERN
from tv_watchlist.data.enums import JellyfinItemKind
from tv_watchlist.data.errors import (
    JellyfinUnavailableError,
    PlaybackItemNotFoundError,
    PlaybackRangeError,
)
from tv_watchlist.data.models import JellyfinItem
from tv_watchlist.data.session import SessionDep, get_session
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.models.playback_item_read import PlaybackItemRead
from tv_watchlist.models.position_write import PositionWrite
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.playback_items import items_for_entry
from tv_watchlist.services.playback_position import project_playback_position

router = APIRouter(prefix="/api/playback", tags=["playback"])
JellyfinDep = Annotated[JellyfinClient, Depends(get_jellyfin_client)]
CatalogDep = Annotated[Catalog, Depends(get_catalog)]
# The stream body owns no ORM state, so its database connection must not outlive the route function.
StreamSessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
_RANGE = re.compile(RANGE_HEADER_PATTERN)


def _range_header(request: Request) -> str | None:
    values = request.headers.getlist("range")
    if not values:
        return None
    match = _RANGE.fullmatch(values[0])
    if len(values) != 1 or match is None:
        raise PlaybackRangeError("Invalid byte range")
    start, end = (number.lstrip("0") or "0" for number in match.groups())
    # Compare decimal strings rather than int(): HTTP input can exceed Python's integer digit limit.
    if match[2] and (len(start), start) > (len(end), end):
        raise PlaybackRangeError("Reversed byte range")
    return values[0]


@router.get("/entries/{entry_id}/items", response_model=list[PlaybackItemRead])
async def list_items(
    entry_id: uuid.UUID,
    session: SessionDep,
    client: JellyfinDep,
    limit: Annotated[int, Query(ge=1, le=MAX_ENTRIES_PAGE_SIZE)] = MAX_ENTRIES_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PlaybackItemRead]:
    """A queue page with file-level selection, kept separate from title-level entry availability."""
    return await items_for_entry(session, client, entry_id, limit=limit, offset=offset)


@router.post("/entries/{entry_id}/position", response_model=CategoryDetail)
async def write_position(
    entry_id: uuid.UUID, body: PositionWrite, session: SessionDep, catalog: CatalogDep
) -> CategoryDetail:
    """Project a durable player snapshot without appending another event on workbook retries."""
    detail = await project_playback_position(
        session, catalog, entry_id, body.watch_event_id, expected_mtime=body.expected_mtime
    )
    await session.commit()
    return detail


@router.get("/{jellyfin_item_id}/stream", response_class=StreamingResponse)
async def stream(
    jellyfin_item_id: uuid.UUID, request: Request, session: StreamSessionDep, client: JellyfinDep
) -> PlaybackResponse:
    """Relay one live movie or episode with the sole caller-supplied upstream header, Range."""
    range_header = _range_header(request)
    item = await session.scalar(
        select(JellyfinItem).where(
            JellyfinItem.id == jellyfin_item_id,
            JellyfinItem.removed_at.is_(None),
            JellyfinItem.kind.in_((JellyfinItemKind.MOVIE, JellyfinItemKind.EPISODE)),
        )
    )
    if item is None:
        raise PlaybackItemNotFoundError(str(jellyfin_item_id))
    if not client.configured or client.closed or not await client.health():
        raise JellyfinUnavailableError("Jellyfin unavailable")
    return PlaybackResponse(client.stream(item.jellyfin_id, range_header=range_header))
