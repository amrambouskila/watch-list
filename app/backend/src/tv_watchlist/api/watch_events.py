"""The only write into the append-only watch log, and the derived state it moves.

Two routes, one subject. The POST appends a fact and answers with the progress the view derives from
it, so the UI repaints from the database rather than from the request it just sent; the GET answers the
same thing on its own, for a screen that did not write anything (CLAUDE.md section 13.5).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tv_watchlist.api.dependencies import get_catalog
from tv_watchlist.data.session import SessionDep, get_session_factory
from tv_watchlist.models.entry_progress import EntryProgress
from tv_watchlist.models.watch_event_create import WatchEventCreate
from tv_watchlist.models.watch_event_read import WatchEventRead
from tv_watchlist.services import watch_events
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.playback_events import record_playback_event

router = APIRouter(prefix="/api", tags=["watch-events"])

CatalogDep = Annotated[Catalog, Depends(get_catalog)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]


@router.post("/watch-events", response_model=WatchEventRead, status_code=status.HTTP_201_CREATED)
async def create_watch_event(
    body: WatchEventCreate,
    session: SessionDep,
    catalog: CatalogDep,
    session_factory: SessionFactoryDep,
    background: BackgroundTasks,
    playback_entry_id: uuid.UUID | None = None,
    jellyfin_item_id: uuid.UUID | None = None,
) -> WatchEventRead:
    """Append one watch fact, and schedule the sheet cell it projects onto."""
    if (playback_entry_id is None) != (jellyfin_item_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Supply both playback_entry_id and jellyfin_item_id."
        )
    if playback_entry_id is not None and jellyfin_item_id is not None:
        read = await record_playback_event(session, body, playback_entry_id, jellyfin_item_id)
        await session.commit()
        return read
    read = await watch_events.record_watch_event(session, body)
    await session.commit()
    if read.curated_entry_id is not None:
        # Scheduled after the commit, never awaited: the mirror opens a workbook, and a watch event
        # must not wait on Excel - nor fail because somebody has the file open (CLAUDE.md section 0.2).
        # It takes its own session from the factory, because a background task outlives this request's.
        background.add_task(watch_events.mirror_recorded_entry, session_factory, catalog, read.curated_entry_id)
    return read


@router.get("/categories/{category_id}/entries/{entry_id}/progress", response_model=EntryProgress)
async def read_entry_progress(category_id: str, entry_id: uuid.UUID, session: SessionDep) -> EntryProgress:
    """One entry's derived state, read off the view rather than off any stored status."""
    return await watch_events.entry_progress(session, entry_id, category_slug=category_id)
