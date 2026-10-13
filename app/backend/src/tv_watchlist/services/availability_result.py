from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from tv_watchlist.services.entry_availability import EntryAvailability


class AvailabilityResult(BaseModel):
    """A page of computed states, plus a service-only configuration or outage notice."""

    model_config = ConfigDict(frozen=True)

    entries: dict[uuid.UUID, EntryAvailability]
    notice: str | None = None
