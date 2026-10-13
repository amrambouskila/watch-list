"""One episode as the API exposes it."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class EpisodeRead(BaseModel):
    """One episode as the API exposes it. Runtime is whole seconds."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    title_id: uuid.UUID
    # A key, never a human SxxEyy: TMDB numbers anime absolutely inside season buckets, so what the UI
    # prints comes from `episode_order` (CLAUDE.md section 11, rule 9).
    season_number: int = Field(ge=0)
    episode_number: int = Field(ge=0)
    name: str | None = None
    air_date: date | None = None
    runtime_seconds: int | None = Field(default=None, gt=0)
    # `/heroes/<artwork.local_path>?v=<st_mtime_ns>`, the same shape as `TitleRead.poster_url`: served
    # from disk by whichever service exposes an episode, never a column on this row.
    still_url: str | None = None
