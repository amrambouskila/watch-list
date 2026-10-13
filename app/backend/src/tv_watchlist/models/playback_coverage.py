from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PlaybackCoverage(BaseModel):
    """Immutable evidence captured from the locked file and its validated stored numbering."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_kind: Literal["episode", "title"]
    subject_ids: frozenset[uuid.UUID]
    jellyfin_item_id_snapshot: uuid.UUID
    jellyfin_id_snapshot: str
    order_type: str | None = None
    order_label: str = ""
    parent_index_number: int | None = None
    index_number: int | None = None
    index_number_end: int | None = None
