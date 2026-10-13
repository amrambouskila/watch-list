"""Direct edits to a workbook copy, bypassing the app's own writer, to provoke a specific reaction."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from openpyxl import load_workbook


def narrow_the_status_dropdown(path: Path, index: int, offered: Sequence[str]) -> None:
    """Rewrite a copy's dropdown to a foreign vocabulary, so a test can prove the mirror skips it."""
    workbook = load_workbook(path)
    sheet = workbook.worksheets[0]
    for validation in sheet.data_validations.dataValidation:
        if any(area.min_col <= index <= area.max_col for area in validation.sqref.ranges):
            validation.formula1 = '"{options}"'.format(options=",".join(offered))
    workbook.save(path)
