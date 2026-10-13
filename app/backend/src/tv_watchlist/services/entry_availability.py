from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from tv_watchlist.data.enums import Availability


class EntryAvailability(BaseModel):
    """One computed entry state and its title-level movie or series id."""

    model_config = ConfigDict(frozen=True)

    availability: Availability
    jellyfin_item_id: uuid.UUID | None = None
