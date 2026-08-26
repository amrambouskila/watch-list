"""One data row of a watch-order sheet."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WatchRow(BaseModel):
    """A sheet row keyed by column key; `row` is the 1-based Excel row number."""

    row: int = Field(ge=2)
    cells: dict[str, str]
