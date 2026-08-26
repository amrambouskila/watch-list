"""Rename a category by renaming its workbook, which is where its name actually lives."""

from __future__ import annotations

import os
from pathlib import Path

from tv_watchlist.constants import WORKBOOK_SUFFIX
from tv_watchlist.workbook import discovery
from tv_watchlist.workbook.errors import DuplicateCategoryError, InvalidNameError, WorkbookLockedError
from tv_watchlist.workbook.locking import is_locked_by_excel
from tv_watchlist.workbook.naming import category_id
from tv_watchlist.workbook.stem import validate_stem


def rename_workbook(path: Path, stem: str) -> Path:
    """Move the workbook to a new filename in the same folder; its contents are untouched."""
    cleaned = validate_stem(stem)
    destination = path.with_name(f"{cleaned}{WORKBOOK_SUFFIX}")
    if destination == path:
        return path
    # Windows compares filenames case-insensitively, so only a differing case is a true self-rename.
    if destination.exists() and destination.name.lower() != path.name.lower():
        raise DuplicateCategoryError(destination.name)
    # A free filename is not a free category: punctuation and spacing drop out of an id, so this
    # filename can be one nothing holds while the id it derives is already spoken for. The loser of
    # an id clash is not merely hidden — every read and write lands on the other workbook.
    shadowed = discovery.addressed_by(path.parent, category_id(destination), besides=path)
    if shadowed is not None:
        raise DuplicateCategoryError(shadowed.name)
    if is_locked_by_excel(path):
        raise WorkbookLockedError(path.name)
    try:
        os.rename(path, destination)
    except FileExistsError as error:
        raise DuplicateCategoryError(destination.name) from error
    except PermissionError as error:
        raise WorkbookLockedError(path.name) from error
    except OSError as error:
        raise InvalidNameError(f"{cleaned} ({error.strerror or error})") from error
    return destination
