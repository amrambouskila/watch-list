"""Structural fingerprint of a workbook, used to prove writes preserve Excel constructs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook


def fingerprint(path: Path) -> dict[str, dict[str, Any]]:
    """Every structural and stylistic property a write must not disturb."""
    workbook = load_workbook(path)
    result: dict[str, dict[str, Any]] = {}
    for sheet in workbook.worksheets:
        header = sheet.cell(row=1, column=1)
        result[sheet.title] = {
            "dimensions": (sheet.max_row, sheet.max_column),
            "tables": {name: sheet.tables[name].ref for name in sheet.tables},
            "table_columns": {
                name: [column.name for column in sheet.tables[name].tableColumns] for name in sheet.tables
            },
            "validations": sorted(
                (validation.formula1 or "", str(validation.sqref))
                for validation in sheet.data_validations.dataValidation
            ),
            "conditional_ranges": sorted(str(entry.sqref) for entry in sheet.conditional_formatting),
            "conditional_rule_count": sum(len(entry.rules) for entry in sheet.conditional_formatting),
            "widths": {key: value.width for key, value in sheet.column_dimensions.items() if value.width},
            "header_style": (
                header.font.bold,
                header.font.color.rgb if header.font.color else None,
                header.fill.fgColor.rgb if header.fill else None,
                header.fill.patternType if header.fill else None,
                header.alignment.horizontal,
            ),
            "body_style": (
                sheet.cell(row=2, column=2).alignment.wrap_text,
                sheet.cell(row=2, column=2).alignment.vertical,
                sheet.cell(row=2, column=2).font.name,
            ),
        }
    return result
