"""Request body for generating a brand-new category workbook."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from tv_watchlist.constants import (
    DEFAULT_ACCENT_RGB,
    DEFAULT_NEW_CATEGORY_COLUMNS,
    HEX_COLOR_PATTERN,
    MAX_NEW_CATEGORY_COLUMNS,
    MAX_NEW_CATEGORY_ROWS,
    MAX_TITLE_LENGTH,
)
from tv_watchlist.models.cell_text import sanitize

# The one place column keys are minted, so a request's vocabulary matches what the reader
# will derive from the headers this request writes.
from tv_watchlist.workbook.schema import unique_key


class CategoryCreate(BaseModel):
    """A new workbook: display name, accent colour, columns, and either seed titles or full rows."""

    name: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    accent: str = Field(default=f"#{DEFAULT_ACCENT_RGB[2:]}", pattern=HEX_COLOR_PATTERN)
    columns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_NEW_CATEGORY_COLUMNS), max_length=MAX_NEW_CATEGORY_COLUMNS
    )
    titles: list[str] = Field(default_factory=list, max_length=MAX_NEW_CATEGORY_ROWS)
    rows: list[dict[str, str]] = Field(default_factory=list, max_length=MAX_NEW_CATEGORY_ROWS)

    @field_validator("name", "columns", "titles", mode="after")
    @classmethod
    def _sanitize(cls, value: str | list[str]) -> str | list[str]:
        if isinstance(value, str):
            return sanitize(value, MAX_TITLE_LENGTH)
        return [sanitize(item, MAX_TITLE_LENGTH) for item in value]

    @field_validator("rows", mode="after")
    @classmethod
    def _sanitize_cells(cls, value: list[dict[str, str]]) -> list[dict[str, str]]:
        return [{key: sanitize(cell) for key, cell in row.items()} for row in value]

    def column_keys(self) -> list[str]:
        """Column keys these headers derive, in sheet order."""
        taken: set[str] = set()
        return [unique_key(label, index, taken) for index, label in enumerate(self.columns, start=1)]

    @model_validator(mode="after")
    def _reject_incoherent_rows(self) -> CategoryCreate:
        if self.titles and self.rows:
            raise ValueError("supply either titles or rows, not both")
        known = set(self.column_keys())
        for row in self.rows:
            unknown = next((key for key in row if key not in known), None)
            if unknown is not None:
                raise ValueError(f"row key {unknown!r} is not one of this category's column keys")
        return self
