"""The only write path into the append-only watch log.

`subject_id` is deliberately one field rather than three nullable ones: the API surface is a
discriminated pair, and the service maps `(subject_kind, subject_id)` onto the correct typed FK column
before the insert. The validator below duplicates the database `CHECK` on purpose - one rejects a bad
request with a 422 at the boundary, the other guarantees the invariant for every writer, including a
data migration that never passes through this model (CLAUDE.md section 5.15).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tv_watchlist.constants import MAX_DEVICE_LENGTH, MAX_NOTE_LENGTH
from tv_watchlist.data.enums import WatchEventKind, WatchSubjectKind


class WatchEventCreate(BaseModel):
    """Request body for recording one watch fact. This is the only write path into the log."""

    model_config = ConfigDict(extra="forbid")

    subject_kind: WatchSubjectKind
    subject_id: uuid.UUID
    kind: WatchEventKind
    category_id: uuid.UUID | None = None
    occurred_at: datetime | None = None
    position_seconds: int | None = Field(default=None, ge=0)
    runtime_seconds: int | None = Field(default=None, gt=0)
    device: str | None = Field(default=None, max_length=MAX_DEVICE_LENGTH)
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)

    @model_validator(mode="after")
    def _progress_carries_a_position(self) -> WatchEventCreate:
        if self.kind is WatchEventKind.PROGRESSED and self.position_seconds is None:
            raise ValueError("a progressed event needs position_seconds")
        return self
