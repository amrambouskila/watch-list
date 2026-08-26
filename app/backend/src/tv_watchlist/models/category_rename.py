"""Request body for renaming a category's workbook."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tv_watchlist.constants import MAX_FILENAME_STEM_LENGTH


class CategoryRename(BaseModel):
    """The new filename stem, without the .xlsx suffix, guarded by the client's last-known mtime."""

    stem: str = Field(min_length=1, max_length=MAX_FILENAME_STEM_LENGTH)
    expected_mtime: float
