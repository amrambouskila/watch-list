"""One work as the API exposes it."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from tv_watchlist.data.enums import MediaType


class TitleRead(BaseModel):
    """A resolved title. Runtime is whole seconds; `poster_url` is served from disk, never stored here."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    media_type: MediaType
    # Nullable, like the column: a hand-entered local title with no provider match is a first-class
    # record (CLAUDE.md section 5.13, risk register R2).
    tmdb_id: int | None = None
    name: str
    original_name: str | None = None
    first_air_date: date | None = None
    last_air_date: date | None = None
    runtime_seconds: int | None = Field(default=None, gt=0)
    episode_count: int | None = Field(default=None, ge=0)
    season_count: int | None = Field(default=None, ge=0)
    status: str | None = None
    # `/heroes/<artwork.local_path>?v=<st_mtime_ns>`, computed by the service the way CategorySummary.hero_url
    # is. Absent from the ORM class, so the default stands whenever no poster's bytes are cached.
    poster_url: str | None = None
