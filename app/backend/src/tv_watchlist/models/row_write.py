"""Request body for creating or updating a single sheet row."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tv_watchlist.models.cell_text import sanitize


class RowWrite(BaseModel):
    """Cell values keyed by column key, guarded by the client's last-known mtime."""

    cells: dict[str, str] = Field(default_factory=dict)
    expected_mtime: float

    def sanitized_cells(self) -> dict[str, str]:
        """Cell values stripped of characters Excel rejects and clipped to a cell's capacity."""
        return {key: sanitize(value) for key, value in self.cells.items()}
