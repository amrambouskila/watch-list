"""The resolution review queue: the rows a heuristic could not settle, and the human decision about one.

Read beside `GET /api/categories/{id}/entries` rather than inside it: the queue spans every category at
once, which is what makes "what is still unreviewed" one request instead of nineteen (CLAUDE.md 18.2).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from tv_watchlist.api.dependencies import get_ingest_runtime, get_jellyfin_client
from tv_watchlist.clients.jellyfin_client import JellyfinClient
from tv_watchlist.config import Settings, get_settings
from tv_watchlist.constants import MAX_ENTRIES_PAGE_SIZE
from tv_watchlist.data.enums import ResolutionState
from tv_watchlist.data.session import SessionDep
from tv_watchlist.ingest.runtime import IngestRuntime
from tv_watchlist.models.curated_entry_read import CuratedEntryRead
from tv_watchlist.models.resolution_update import ResolutionUpdate
from tv_watchlist.services import resolution_review

router = APIRouter(prefix="/api/review", tags=["review"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
IngestRuntimeDep = Annotated[IngestRuntime, Depends(get_ingest_runtime)]
JellyfinDep = Annotated[JellyfinClient, Depends(get_jellyfin_client)]


@router.get("/entries", response_model=list[CuratedEntryRead])
async def review_queue(
    session: SessionDep,
    settings: SettingsDep,
    jellyfin: JellyfinDep,
    state: Annotated[list[ResolutionState] | None, Query()] = None,
    category_id: str | None = None,
    # The cap is the default as well as the ceiling, exactly as the projection route has it.
    limit: Annotated[int, Query(ge=1, le=MAX_ENTRIES_PAGE_SIZE)] = MAX_ENTRIES_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CuratedEntryRead]:
    """One page of the queue, worst first: unresolved before least-confident, then category and position."""
    states = resolution_review.DEFAULT_REVIEW_STATES if state is None else tuple(state)
    return await resolution_review.list_for_review(
        session, settings, states=states, category_slug=category_id, limit=limit, offset=offset, jellyfin=jellyfin
    )


@router.post("/entries/{entry_id}", response_model=CuratedEntryRead)
async def review_entry(
    entry_id: uuid.UUID,
    body: ResolutionUpdate,
    session: SessionDep,
    settings: SettingsDep,
    runtime: IngestRuntimeDep,
    jellyfin: JellyfinDep,
) -> CuratedEntryRead:
    """Confirm, correct or reject one entry's resolution, and answer with the row as it now stands.

    The commit is here rather than in the service: one request is one decision, and the service keeps the
    ingest's rule that nothing below the boundary closes a transaction it did not open. `settings` is
    injected and threaded through rather than read off the runtime, so this route and the queue above it
    compose poster URLs against the same `heroes_dir` - one request, one settings object.
    """
    read = await resolution_review.apply_resolution(session, settings, runtime, entry_id, body, jellyfin=jellyfin)
    await session.commit()
    return read


@router.post("/entries/{entry_id}/retry", response_model=CuratedEntryRead)
async def retry_entry(
    entry_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    runtime: IngestRuntimeDep,
    jellyfin: JellyfinDep,
) -> CuratedEntryRead:
    """Spend one search on one row and answer with what it now says (R71).

    No body: a retry asks nothing of the reviewer, it asks the provider again on their behalf. The commit
    is here for the same reason the decision above commits here - one request is one attempt - and a row
    that resolved no better than last time is a 200 carrying the new reason, never a refusal.
    """
    read = await resolution_review.retry_resolution(session, settings, runtime, entry_id, jellyfin=jellyfin)
    await session.commit()
    return read
