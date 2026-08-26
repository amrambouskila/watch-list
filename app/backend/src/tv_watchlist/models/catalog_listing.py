"""The full library listing."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tv_watchlist.models.category_summary import CategorySummary
from tv_watchlist.models.shadowed_workbook import ShadowedWorkbook
from tv_watchlist.models.unreadable_workbook import UnreadableWorkbook


class CatalogListing(BaseModel):
    """Every category in the library, plus anything that failed to load or could not be reached."""

    categories: list[CategorySummary]
    unreadable: list[UnreadableWorkbook] = Field(default_factory=list)
    shadowed: list[ShadowedWorkbook] = Field(default_factory=list)
    library_dir: str
