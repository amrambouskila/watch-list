"""Rebuilding the Jellyfin library index on demand.

One route, and it is the owner's button rather than a schedule: Phase 3 keeps the walk a thing that is
asked for - by the launcher at start, or from the UI after files are added - because a background timer
against a media server that may be mid-scan is a cost with no reader (CLAUDE.md section 13.5).

It promises "a disabled feature, never a 500". The mechanism is R72's: `sync_library` converts every
provider failure into `JellyfinUnavailableError`, a `ProjectionError` subclass registered in both of
`api/errors.py`'s tables at 503, and this route therefore catches nothing at all.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import AfterValidator

from tv_watchlist.api.dependencies import get_jellyfin_client
from tv_watchlist.clients.jellyfin_client import JellyfinClient
from tv_watchlist.data.session import SessionDep
from tv_watchlist.models.library_sync_result import LibrarySyncResult
from tv_watchlist.services import library_sync

router = APIRouter(prefix="/api/library", tags=["library"])

JellyfinClientDep = Annotated[JellyfinClient, Depends(get_jellyfin_client)]


def _aware(value: datetime | None) -> datetime | None:
    """A cursor without an offset is ambiguous by exactly the machine's timezone, so it is refused."""
    # Raised during request validation, so it is a 422 naming the field rather than an asyncpg error
    # several frames into a walk: `date_last_saved` and `last_seen_at` are both `timestamptz`.
    if value is not None and value.tzinfo is None:
        raise ValueError("since must carry a UTC offset, e.g. 2026-09-22T09:00:00+00:00")
    return value


# The previous pass's own `synced_at`, handed back. Optional, because nothing in Phase 3 schedules this
# route - a caller that keeps no stamp gets the table's own `max(last_seen_at)` instead (R87).
SinceQuery = Annotated[datetime | None, AfterValidator(_aware), Query()]


@router.post("/sync", response_model=LibrarySyncResult)
async def sync_library(
    session: SessionDep,
    client: JellyfinClientDep,
    full: Annotated[bool, Query()] = False,
    since: SinceQuery = None,
) -> LibrarySyncResult:
    """Walk the library into `jellyfin_item`, and answer with what the pass changed.

    The commit is here rather than in the service, for the reason every other write route gives: one
    request is one pass, and nothing below the boundary closes a transaction it did not open.

    `full` forces a whole-library walk, and only a full walk is allowed to mark a row removed. `since` is
    the previous pass's `synced_at` handed back; without either, the pass is incremental from the table's
    own `max(last_seen_at)` and full only while the index is empty (R87). Two overlapping requests do not
    race: `sync_library` takes a transaction-scoped advisory lock before it reads anything.
    """
    result = await library_sync.sync_library(session, client, full=full, since=since)
    await session.commit()
    return result
