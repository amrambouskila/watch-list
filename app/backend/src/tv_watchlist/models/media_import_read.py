"""One file's provenance record, as the API exposes it."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from tv_watchlist.data.enums import MediaImportIdentifiedBy, MediaImportSource, MediaImportStatus


class MediaImportRead(BaseModel):
    """One file's journey from where the owner put it to where Jellyfin found it. Never deleted; superseded."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    title_id: uuid.UUID | None = None
    episode_id: uuid.UUID | None = None
    jellyfin_item_id: uuid.UUID | None = None
    source: MediaImportSource
    source_path: str
    original_name: str
    size_bytes: int = Field(gt=0)
    file_path: str | None = None
    file_sha256: str | None = None
    identified_by: MediaImportIdentifiedBy | None = None
    identification_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: MediaImportStatus
    error: str | None = None
    found_at: datetime
    imported_at: datetime | None = None
    superseded_at: datetime | None = None
    superseded_by_id: uuid.UUID | None = None
    # Derived from the eagerly loaded `title` relationship, never a column of its own - the caller
    # `selectinload()`s it before converting, or the ORM's `lazy="raise_on_sql"` raises here rather than
    # lazy-loading (CLAUDE.md section 5.15).
    title_name: str | None = None
