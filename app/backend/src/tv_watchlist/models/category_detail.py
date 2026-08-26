"""Full category payload: schema, rows, and companion sheets."""

from __future__ import annotations

from tv_watchlist.models.category_summary import CategorySummary
from tv_watchlist.models.column_spec import ColumnSpec
from tv_watchlist.models.reference_sheet import ReferenceSheet
from tv_watchlist.models.watch_row import WatchRow


class CategoryDetail(CategorySummary):
    """A category plus its editable grid and read-only reference sheets."""

    columns: list[ColumnSpec]
    rows: list[WatchRow]
    reference_sheets: list[ReferenceSheet]
