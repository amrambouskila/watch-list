"""One stored watch fact, echoed back with the progress it derives."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from tv_watchlist.data.enums import WatchEventKind, WatchEventSource, WatchSubjectKind
from tv_watchlist.models.entry_progress import EntryProgress


class WatchEventRead(BaseModel):
    """The stored fact echoed back, plus the entry's derived progress so the UI repaints from the view,
    not the request (master plan section 6.6)."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    # Client-supplied and allowed to arrive late; `recorded_at` is server-assigned. The pair is what
    # makes the two DISTINCT ON views deterministic (CLAUDE.md section 11.2, rule 12).
    occurred_at: datetime
    recorded_at: datetime
    subject_kind: WatchSubjectKind
    kind: WatchEventKind
    source: WatchEventSource
    tmdb_key: str | None = None
    # The entry this event MOVES, which is the stored column only for a `curated_entry` subject: an
    # episode or movie event names the live queue slot holding it, because that is the row whose
    # progress changed and the row the mirror projects onto. `one_subject` forbids storing both.
    curated_entry_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    position_seconds: int | None = Field(default=None, ge=0)
    runtime_seconds: int | None = Field(default=None, gt=0)
    # None when no live queue slot holds the subject: an episode nothing curated covers is still a fact
    # worth logging, and a progress reading invented for it would be a lie.
    progress: EntryProgress | None = None
