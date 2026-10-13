"""What one pass of the Jellyfin library sync did."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LibrarySyncResult(BaseModel):
    """Counts from one walk of the owner's Jellyfin, and whether it was allowed to soft-delete.

    `incremental` is not decoration. A full scan may mark a row `removed_at` because absence from the
    walk proves the file is gone; an incremental one may not, because it only asked for what changed
    since a cursor. A reader who cannot tell the two apart cannot tell "nothing vanished" from "nothing
    was looked at", so the flag travels with the counts (CLAUDE.md section 13.5).

    `synced_at` is this run's own stamp, and it is the cursor a later incremental run may be handed: 12.1
    does not declare `DateLastSaved` on an item, so the table's own max can legitimately be NULL (R79).
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    seen: int = Field(ge=0)
    added: int = Field(ge=0)
    updated: int = Field(ge=0)
    removed: int = Field(ge=0)
    synced_at: datetime
    incremental: bool
