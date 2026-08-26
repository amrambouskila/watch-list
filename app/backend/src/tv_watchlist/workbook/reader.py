"""Read a workbook into the API's category representation."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from tv_watchlist.constants import (
    DEFAULT_ACCENT_RGB,
    FIRST_DATA_ROW,
    HEADER_ROW,
    IN_PROGRESS,
    SKIPPED,
    TRANSPARENT_ARGB,
    WATCHED,
)
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.models.column_spec import ColumnSpec
from tv_watchlist.models.reference_sheet import ReferenceSheet
from tv_watchlist.models.watch_counts import WatchCounts
from tv_watchlist.models.watch_row import WatchRow
from tv_watchlist.workbook.cells import cell_text, last_data_row
from tv_watchlist.workbook.locking import is_locked_by_excel
from tv_watchlist.workbook.naming import category_id
from tv_watchlist.workbook.schema import build_columns, watch_column


def _accent(sheet: Worksheet) -> str:
    """Accent colour taken from the sheet's own header fill."""
    default = f"#{DEFAULT_ACCENT_RGB[2:]}"
    fill = sheet.cell(row=HEADER_ROW, column=1).fill
    if fill is None or fill.patternType is None:
        return default
    rgb = getattr(fill.fgColor, "rgb", None)
    if not isinstance(rgb, str) or len(rgb) != 8 or rgb.upper() == TRANSPARENT_ARGB:
        return default
    return f"#{rgb[2:]}"


def _count(statuses: list[str]) -> WatchCounts:
    watched = sum(1 for status in statuses if status == WATCHED)
    in_progress = sum(1 for status in statuses if status == IN_PROGRESS)
    skipped = sum(1 for status in statuses if status == SKIPPED)
    total = len(statuses)
    return WatchCounts(
        total=total,
        watched=watched,
        in_progress=in_progress,
        skipped=skipped,
        unwatched=total - watched - in_progress - skipped,
        trackable=total - skipped,
    )


def _reference_sheets(sheets: list[Worksheet]) -> list[ReferenceSheet]:
    references: list[ReferenceSheet] = []
    for sheet in sheets:
        width = sheet.max_column
        header = [cell_text(sheet.cell(row=HEADER_ROW, column=column).value) for column in range(1, width + 1)]
        rows = [
            [cell_text(sheet.cell(row=row, column=column).value) for column in range(1, width + 1)]
            for row in range(FIRST_DATA_ROW, sheet.max_row + 1)
        ]
        references.append(ReferenceSheet(title=sheet.title, header=header, rows=[row for row in rows if any(row)]))
    return references


def read_category(path: Path) -> CategoryDetail:
    """Load one workbook as a fully populated category."""
    workbook = load_workbook(path)
    sheet = workbook.worksheets[0]
    columns: list[ColumnSpec] = build_columns(sheet)
    watch = watch_column(columns)
    end_row = last_data_row(sheet, sheet.max_column)

    rows: list[WatchRow] = []
    statuses: list[str] = []
    for row_number in range(FIRST_DATA_ROW, end_row + 1):
        cells = {column.key: cell_text(sheet.cell(row=row_number, column=column.index).value) for column in columns}
        if not any(value.strip() for value in cells.values()):
            continue
        rows.append(WatchRow(row=row_number, cells=cells))
        statuses.append(cells.get(watch.key, "").strip() if watch else "")

    return CategoryDetail(
        id=category_id(path),
        name=path.stem,
        file_name=path.name,
        sheet_title=sheet.title,
        accent=_accent(sheet),
        mtime=path.stat().st_mtime,
        has_watch_column=watch is not None,
        locked_by_excel=is_locked_by_excel(path),
        counts=_count(statuses),
        columns=columns,
        rows=rows,
        reference_sheets=_reference_sheets(workbook.worksheets[1:]),
    )
