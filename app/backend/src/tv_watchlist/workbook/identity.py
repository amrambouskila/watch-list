"""The hidden Row ID column that gives every sheet row an identity the app can hold on to."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from openpyxl.worksheet.worksheet import Worksheet

from tv_watchlist.constants import (
    FIRST_DATA_ROW,
    IDENTITY_COLUMN_WIDTH,
    IDENTITY_HEADER_LABEL,
)
from tv_watchlist.models.column_spec import ColumnSpec
from tv_watchlist.workbook import writer
from tv_watchlist.workbook.cells import last_data_row
from tv_watchlist.workbook.errors import RowNotFoundError
from tv_watchlist.workbook.schema import build_columns, identity_column


def ensure_identity_column_on(sheet: Worksheet, columns: list[ColumnSpec]) -> int:
    """Append the hidden Row ID column when the sheet has none, and return its 1-based index."""
    existing = identity_column(columns)
    if existing is not None:
        return existing.index
    # Hidden because it is the app's own bookkeeping: the owner curates the sheet, not these ids.
    index, _ = writer._append_styled_column(sheet, columns, IDENTITY_HEADER_LABEL, IDENTITY_COLUMN_WIDTH, hidden=True)
    return index


def write_row_ids_on(sheet: Worksheet, column_index: int, ids_by_row: Mapping[int, str]) -> None:
    """Record each row's identity; no row moves, so no range needs stretching afterwards."""
    last = last_data_row(sheet, column_index)
    # Every row is checked before any is written, so a batch naming one row off the end changes nothing.
    for row in ids_by_row:
        if row < FIRST_DATA_ROW or row > last:
            raise RowNotFoundError(str(row))
    for row, row_id in ids_by_row.items():
        sheet.cell(row=row, column=column_index).value = row_id


def ensure_identity_column(path: Path) -> None:
    """Give a workbook its hidden Row ID column, leaving a file that already has one untouched."""
    workbook, sheet = writer._open(path)
    columns = build_columns(sheet)
    if identity_column(columns) is not None:
        return
    ensure_identity_column_on(sheet, columns)
    writer._save(workbook, path)


def write_row_ids(path: Path, ids_by_row: Mapping[int, str]) -> None:
    """Record each row's identity in one atomic rewrite, minting the column if the sheet lacks one."""
    workbook, sheet = writer._open(path)
    index = ensure_identity_column_on(sheet, build_columns(sheet))
    write_row_ids_on(sheet, index, ids_by_row)
    writer._save(workbook, path)
