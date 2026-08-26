"""Find the workbooks that make up the library."""

from __future__ import annotations

from pathlib import Path

from tv_watchlist.constants import EXCEL_LOCK_PREFIX, TEMP_WRITE_PREFIX, WORKBOOK_SUFFIX
from tv_watchlist.workbook.errors import CategoryNotFoundError
from tv_watchlist.workbook.naming import category_id


def workbook_paths(library_dir: Path) -> list[Path]:
    """Every category workbook in the library, alphabetically, ignoring Excel scratch files."""
    if not library_dir.is_dir():
        return []
    return sorted(
        path
        for path in library_dir.glob(f"*{WORKBOOK_SUFFIX}")
        if path.is_file() and not path.name.startswith((EXCEL_LOCK_PREFIX, TEMP_WRITE_PREFIX, "."))
    )


def resolve(library_dir: Path, wanted_id: str) -> Path:
    """The workbook whose derived id matches, or a CategoryNotFoundError."""
    for path in workbook_paths(library_dir):
        if category_id(path) == wanted_id:
            return path
    raise CategoryNotFoundError(wanted_id)


def addressed_by(library_dir: Path, wanted_id: str, *, besides: Path | None = None) -> Path | None:
    """The workbook already answering to an id, ignoring one path the caller is about to move."""
    return next(
        (path for path in workbook_paths(library_dir) if category_id(path) == wanted_id and path != besides),
        None,
    )
