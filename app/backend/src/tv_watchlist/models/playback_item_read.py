from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from tv_watchlist.data.enums import Availability


class PlaybackItemRead(BaseModel):
    """One stored queue slot and its selected movie or episode file, never a series id."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    entry_id: uuid.UUID
    episode_id: uuid.UUID | None
    movie_title_id: uuid.UUID | None
    position_in_entry: int = Field(ge=1)
    absolute_position: int = Field(ge=1)
    availability: Availability
    jellyfin_item_id: uuid.UUID | None
    order_type: str | None
    order_label: str
    covers_range: bool
