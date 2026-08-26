"""Progress tally for one category."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WatchCounts(BaseModel):
    """Row counts by watch status. `trackable` excludes skipped rows."""

    total: int = Field(ge=0)
    watched: int = Field(ge=0)
    in_progress: int = Field(ge=0)
    skipped: int = Field(ge=0)
    unwatched: int = Field(ge=0)
    trackable: int = Field(ge=0)
