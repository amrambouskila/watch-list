"""The Postgres projection of one category's rows.

Served alongside `GET /api/categories/{id}`, never instead of it: `CategoryDetail` stays the workbook's
editing contract and this carries the derived side - resolution, titles and progress (CLAUDE.md 13.5).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from tv_watchlist.api.dependencies import get_jellyfin_client
from tv_watchlist.clients.jellyfin_client import JellyfinClient
from tv_watchlist.config import Settings, get_settings
from tv_watchlist.constants import MAX_ENTRIES_PAGE_SIZE
from tv_watchlist.data.session import SessionDep
from tv_watchlist.models.curated_entry_read import CuratedEntryRead
from tv_watchlist.services import entries

router = APIRouter(prefix="/api/categories", tags=["entries"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
JellyfinDep = Annotated[JellyfinClient, Depends(get_jellyfin_client)]


@router.get("/{category_id}/entries", response_model=list[CuratedEntryRead])
async def list_category_entries(
    category_id: str,
    session: SessionDep,
    settings: SettingsDep,
    jellyfin: JellyfinDep,
    # The cap is the default as well as the ceiling, so the common call carries a whole category and an
    # over-large one is refused at the boundary rather than served.
    limit: Annotated[int, Query(ge=1, le=MAX_ENTRIES_PAGE_SIZE)] = MAX_ENTRIES_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CuratedEntryRead]:
    """One page of a category's projection, in the sheet's own order."""
    return await entries.list_entries(session, settings, category_id, limit=limit, offset=offset, jellyfin=jellyfin)
