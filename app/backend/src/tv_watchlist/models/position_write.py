from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class PositionWrite(BaseModel):
    """Project one durable player event, guarded by the workbook's original modification stamp."""

    model_config = ConfigDict(extra="forbid")

    watch_event_id: uuid.UUID
    expected_mtime: float = Field(allow_inf_nan=False)
