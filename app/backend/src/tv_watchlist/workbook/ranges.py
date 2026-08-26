"""Keep a sheet's table, dropdowns, and highlight rules covering the whole data range."""

from __future__ import annotations

from openpyxl.formatting.formatting import ConditionalFormattingList
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import range_boundaries
from openpyxl.worksheet.cell_range import CellRange, MultiCellRange
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableColumn, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from tv_watchlist.constants import (
    FIRST_DATA_ROW,
    HEADER_ROW,
    TABLE_STYLE_NAME,
    WATCHED,
    WATCHED_HIGHLIGHT_RGB,
)


def inline_list(choices: list[str]) -> str:
    """Excel inline-list validation formula for the given options."""
    return '"{}"'.format(",".join(choices))


def _stretched(ranges: list[CellRange], last_row: int) -> MultiCellRange:
    rebuilt: list[CellRange] = []
    seen: set[str] = set()
    for source in ranges:
        max_row = last_row if source.min_row == FIRST_DATA_ROW else source.max_row
        candidate = CellRange(
            min_col=source.min_col, min_row=source.min_row, max_col=source.max_col, max_row=max(max_row, source.min_row)
        )
        if candidate.coord not in seen:
            seen.add(candidate.coord)
            rebuilt.append(candidate)
    return MultiCellRange(rebuilt)


def _sync_tables(sheet: Worksheet, last_row: int, column_count: int) -> None:
    """
    Resize the table that owns the grid.

    Only the table anchored at A1 is the watch order; a lookup table the owner added elsewhere
    on the sheet keeps its own range, because two tables sharing a reference make Excel treat
    the file as corrupt.
    """
    reference = f"A{HEADER_ROW}:{get_column_letter(column_count)}{max(last_row, FIRST_DATA_ROW)}"
    headers = [str(sheet.cell(row=HEADER_ROW, column=index).value or "") for index in range(1, column_count + 1)]
    for name in list(sheet.tables):
        table = sheet.tables[name]
        min_col, min_row, _, _ = range_boundaries(table.ref)
        if min_col != 1 or min_row != HEADER_ROW:
            continue
        table.ref = reference
        table.tableColumns = [TableColumn(id=index + 1, name=header) for index, header in enumerate(headers)]
        if table.autoFilter is not None:
            table.autoFilter.ref = reference


def _sync_validations(sheet: Worksheet, last_row: int) -> None:
    """Stretch each dropdown, then drop the duplicates stretching can expose."""
    kept: list[DataValidation] = []
    seen: set[tuple[str | None, str | None, str]] = set()
    for validation in sheet.data_validations.dataValidation:
        validation.sqref = _stretched(list(validation.sqref.ranges), last_row)
        signature = (validation.type, validation.formula1, str(validation.sqref))
        if signature in seen:
            continue
        seen.add(signature)
        kept.append(validation)
    sheet.data_validations.dataValidation = kept


def _sync_conditional_formatting(sheet: Worksheet, last_row: int) -> None:
    preserved = [(list(entry.sqref.ranges), list(entry.rules)) for entry in sheet.conditional_formatting]
    sheet.conditional_formatting = ConditionalFormattingList()
    for source_ranges, rules in preserved:
        target = _stretched(source_ranges, last_row)
        for rule in rules:
            sheet.conditional_formatting.add(str(target), rule)


def sync(sheet: Worksheet, last_row: int, column_count: int) -> None:
    """Stretch table, dropdown, and highlight ranges to cover rows 2..last_row."""
    _sync_tables(sheet, last_row, column_count)
    _sync_validations(sheet, last_row)
    _sync_conditional_formatting(sheet, last_row)


def add_choice_validation(sheet: Worksheet, column_index: int, last_row: int, choices: list[str]) -> None:
    """Attach an inline dropdown to one column's data range."""
    letter = get_column_letter(column_index)
    # A list that already offers an empty option reaches blank through the list itself; the flag
    # is only needed for a dropdown that has none, which would otherwise force a value everywhere.
    validation = DataValidation(type="list", formula1=inline_list(choices), allow_blank="" not in choices)
    sheet.add_data_validation(validation)
    validation.add(f"{letter}{FIRST_DATA_ROW}:{letter}{max(last_row, FIRST_DATA_ROW)}")


def add_watched_highlight(sheet: Worksheet, column_index: int, last_row: int) -> None:
    """Green-fill rule matching the one the library's other workbooks already use."""
    letter = get_column_letter(column_index)
    target = f"{letter}{FIRST_DATA_ROW}:{letter}{max(last_row, FIRST_DATA_ROW)}"
    sheet.conditional_formatting.add(
        target,
        FormulaRule(
            formula=[f'{letter}{FIRST_DATA_ROW}="{WATCHED}"'],
            fill=PatternFill(start_color=WATCHED_HIGHLIGHT_RGB, end_color=WATCHED_HIGHLIGHT_RGB, fill_type="solid"),
        ),
    )


def build_table(name: str, headers: list[str], last_row: int) -> Table:
    """A named table matching the library's style, spanning the header plus data rows."""
    reference = f"A{HEADER_ROW}:{get_column_letter(len(headers))}{max(last_row, FIRST_DATA_ROW)}"
    table = Table(displayName=name, name=name, ref=reference)
    table.tableColumns = [TableColumn(id=index + 1, name=header) for index, header in enumerate(headers)]
    table.tableStyleInfo = TableStyleInfo(
        name=TABLE_STYLE_NAME,
        showRowStripes=True,
        showColumnStripes=False,
        showFirstColumn=False,
        showLastColumn=False,
    )
    table.autoFilter = None
    return table
