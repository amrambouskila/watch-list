from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlaybackOccurrence(BaseModel):
    """One logical occurrence retained as evidence, never automatic skip permission."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_id: uuid.UUID
    subject_kind: Literal["episode", "title"]
    subject_id_snapshot: uuid.UUID
    tmdb_key: str | None = Field(max_length=64)
    position_in_entry: int = Field(ge=1, strict=True)
