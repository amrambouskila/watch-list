"""The library context block every chat session opens with."""

from __future__ import annotations

from tv_watchlist.agent.constants import (
    DIGEST_COLUMN_SEPARATOR,
    DIGEST_STATUS_MARKERS,
    DIGEST_TITLE_SEPARATOR,
    DIGEST_UNKNOWN_STATUS_MARKER,
)
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.models.column_spec import ColumnSpec
from tv_watchlist.models.watch_row import WatchRow
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.schema import watch_column

_LEGEND = DIGEST_COLUMN_SEPARATOR.join(
    f"[{marker}] {status or 'not yet watched'}" for status, marker in DIGEST_STATUS_MARKERS.items()
)


def _title_column(columns: list[ColumnSpec]) -> ColumnSpec:
    return next((column for column in columns if column.role == "title"), columns[0])


def _marked_title(row: WatchRow, title_key: str, watch_key: str | None) -> str:
    status = row.cells.get(watch_key, "") if watch_key is not None else ""
    marker = DIGEST_STATUS_MARKERS.get(status, DIGEST_UNKNOWN_STATUS_MARKER)
    return f"[{marker}] {row.cells.get(title_key, '')}"


def _category_block(detail: CategoryDetail) -> str:
    watch = watch_column(detail.columns)
    title_key = _title_column(detail.columns).key
    keys = DIGEST_COLUMN_SEPARATOR.join(column.key for column in detail.columns)
    titles = DIGEST_TITLE_SEPARATOR.join(
        _marked_title(row, title_key, watch.key if watch is not None else None) for row in detail.rows
    )
    return f"## {detail.id} — {detail.name} ({len(detail.rows)} rows)\ncolumns: {keys}\ntitles: {titles}"


async def build_library_digest(catalog: Catalog) -> str:
    """Every category, its column vocabulary, and every title it already tracks with its status."""
    listing = await catalog.listing()
    details = [await catalog.detail(summary.id) for summary in listing.categories]
    tracked = sum(len(detail.rows) for detail in details)
    header = (
        f"LIBRARY DIGEST — {len(details)} categories, {tracked} rows already tracked.\n"
        f"Status: {_LEGEND}.\n"
        "Cells are keyed by the column keys listed under each category. "
        "Call get_category for a category's full rows before proposing an edit."
    )
    return "\n\n".join([header, *(_category_block(detail) for detail in details)])
