"""Sidebar-level view of a category."""

from __future__ import annotations

from pydantic import BaseModel

from tv_watchlist.models.watch_counts import WatchCounts


class CategorySummary(BaseModel):
    """Everything the category list needs, without the row payload."""

    id: str
    name: str
    file_name: str
    sheet_title: str
    accent: str
    mtime: float
    has_watch_column: bool
    locked_by_excel: bool
    hero_url: str | None = None
    counts: WatchCounts
