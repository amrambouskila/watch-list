"""One row of a curated watch order, as the API exposes it."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from tv_watchlist.data.enums import Availability, ResolutionState, UnitKind
from tv_watchlist.models.entry_progress import EntryProgress
from tv_watchlist.models.title_read import TitleRead


class CuratedEntryRead(BaseModel):
    """One row of a curated watch order, resolved as far as it currently is."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    # The workbook this row belongs to, by the id its filename derives (R82). The review queue spans
    # every category at once, so a row with no category on it is a row a reviewer cannot place - and the
    # queue's own query already joins `category` for the slug it orders by.
    category_slug: str
    position: int = Field(ge=1)
    sheet_row: int | None = None
    unit_kind: UnitKind
    # Not OrderType: the numbering a row names may be one TheTVDB adds tomorrow, read at runtime from
    # `GET /v4/seasons/types` and never a closed set in this codebase (CLAUDE.md section 5.13).
    order_type: str | None = None
    order_label: str = ""
    span_start: int | None = Field(default=None, ge=1)
    span_end: int | None = Field(default=None, ge=1)
    resolution_state: ResolutionState
    resolution_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # Why the row is in the state it is in, in one line: the resolver's own sentence, the expansion's
    # `queue: ` clause and a reviewer's `review: ` clause. The review queue (T30) and the unresolved
    # view (T57) both render it - a row a human is asked to judge has to say what was already tried.
    resolution_note: str = ""
    raw_title: str
    raw_unit: str
    raw_release: str
    # The verbatim row, shaped exactly like `WatchRow.cells` so the UI renders one from either store.
    cells: dict[str, str] = Field(validation_alias="raw_cells")
    title: TitleRead | None = None
    progress: EntryProgress
    availability: Availability
    jellyfin_item_id: uuid.UUID | None = None
