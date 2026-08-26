"""Cell styling that matches the look the library's workbooks already use."""

from __future__ import annotations

from copy import copy

from openpyxl.cell.cell import Cell
from openpyxl.styles import Alignment, Font, PatternFill

from tv_watchlist.constants import HEADER_FONT_RGB, WORKBOOK_FONT_NAME, WORKBOOK_FONT_SIZE


def apply_header_style(cell: Cell, accent_rgb: str) -> None:
    """Bold white text on the category's accent fill, centred."""
    cell.font = Font(name=WORKBOOK_FONT_NAME, size=WORKBOOK_FONT_SIZE, bold=True, color=HEADER_FONT_RGB)
    cell.fill = PatternFill(start_color=accent_rgb, end_color=accent_rgb, fill_type="solid")
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def apply_body_style(cell: Cell) -> None:
    """Wrapped, top-aligned body text."""
    cell.font = Font(name=WORKBOOK_FONT_NAME, size=WORKBOOK_FONT_SIZE)
    cell.alignment = Alignment(vertical="top", wrap_text=True)


def clone_style(source: Cell, target: Cell) -> None:
    """Copy one cell's visual style onto another."""
    target.font = copy(source.font)
    target.fill = copy(source.fill)
    target.border = copy(source.border)
    target.alignment = copy(source.alignment)
    target.number_format = source.number_format
    target.protection = copy(source.protection)
