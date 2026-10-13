"""One atomic workbook snapshot of numeric playback positions and eligible watch cells."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from tv_watchlist.constants import FIRST_DATA_ROW, POSITION_COLUMN_WIDTH, POSITION_HEADER_LABEL
from tv_watchlist.workbook import writer
from tv_watchlist.workbook.cells import last_data_row
from tv_watchlist.workbook.errors import RowNotFoundError
from tv_watchlist.workbook.schema import build_columns, position_column


def apply_position_writeback(
    path: Path, seconds_by_row: Mapping[int, int], cells_by_row: Mapping[int, Mapping[str, str]]
) -> None:
    """Project positions in integer seconds and public watch cells in one guarded atomic save."""
    workbook, sheet = writer._open(path)
    columns = build_columns(sheet)
    last = last_data_row(sheet, writer._grid_width(sheet, columns))
    for row in seconds_by_row:
        if row < FIRST_DATA_ROW or row > last:
            raise RowNotFoundError(str(row))
    writer._writeback_cells_on(sheet, columns, cells_by_row)
    existing = position_column(columns)
    if existing is None:
        index, _ = writer._append_styled_column(sheet, columns, POSITION_HEADER_LABEL, POSITION_COLUMN_WIDTH)
    else:
        index = existing.index
    for row, seconds in seconds_by_row.items():
        sheet.cell(row=row, column=index).value = seconds
    writer._save(workbook, path)
