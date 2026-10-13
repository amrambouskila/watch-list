"""Derived progress for one curated entry."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from tv_watchlist.data.enums import WatchEventKind


class EntryProgress(BaseModel):
    """Derived progress for one curated entry, straight off `curated_entry_watch_state`."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    kind: WatchEventKind
    episode_total: int = Field(ge=0)
    episode_completed: int = Field(ge=0)
    episode_skipped: int = Field(ge=0)
    episode_started: int = Field(ge=0)
    as_of: datetime | None = None
