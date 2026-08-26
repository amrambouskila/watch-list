"""One row-level edit inside a proposed change to an existing category."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from tv_watchlist.constants import FIRST_DATA_ROW, HEADER_ROW, MAX_REASON_LENGTH
from tv_watchlist.models.cell_text import sanitize

RowChangeKind = Literal["add", "revise", "move", "remove"]


class RowChange(BaseModel):
    """A single add / revise / move / remove against a sheet's original row numbers."""

    kind: RowChangeKind
    row: int | None = Field(default=None, ge=FIRST_DATA_ROW)
    after_row: int | None = Field(default=None, ge=HEADER_ROW)
    cells: dict[str, str] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=MAX_REASON_LENGTH)

    @field_validator("cells", mode="after")
    @classmethod
    def _sanitize_cells(cls, value: dict[str, str]) -> dict[str, str]:
        return {key: sanitize(cell) for key, cell in value.items()}

    @model_validator(mode="after")
    def _check_kind_coherence(self) -> RowChange:
        if self.kind == "add":
            if self.row is not None:
                raise ValueError("an add change targets no existing row")
            if not self.cells:
                raise ValueError("an add change needs cells")
        if self.kind == "revise" and (self.row is None or not self.cells):
            raise ValueError("a revise change needs a row and cells")
        if self.kind == "move":
            if self.row is None or self.after_row is None:
                raise ValueError("a move change needs a row and an anchor")
            # A move only reseats a row; the writer never reads these, so a diff that showed them
            # would promise values no write would ever make.
            if self.cells:
                raise ValueError("a move change carries no cells")
        if self.kind == "remove":
            if self.row is None:
                raise ValueError("a remove change needs a row")
            if self.cells:
                raise ValueError("a remove change carries no cells")
        return self
