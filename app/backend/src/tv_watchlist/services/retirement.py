"""Take a category out of the library by moving it into the backups folder, never by unlinking it."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from tv_watchlist.constants import BACKUP_TIMESTAMP_FORMAT, RETIRED_STAMP_PREFIX, WORKBOOK_SUFFIX
from tv_watchlist.workbook import backup, heroes
from tv_watchlist.workbook.errors import WorkbookLockedError
from tv_watchlist.workbook.freshness import guard_fresh
from tv_watchlist.workbook.locking import is_locked_by_excel
from tv_watchlist.workbook.naming import category_id


def retire_category(path: Path, heroes_dir: Path, backup_dir: Path, expected_mtime: float) -> Path:
    """Move a category's workbook and its artwork aside under one stamp, and say where the workbook went."""
    guard_fresh(path, expected_mtime)
    retired_id = category_id(path)
    # Windows will not move a file Excel is holding open, so the refusal has to come before anything does.
    if is_locked_by_excel(path):
        raise WorkbookLockedError(path.name)
    backup_dir.mkdir(parents=True, exist_ok=True)
    # One stamp for both files, so a workbook and the artwork that belongs to it are visibly one retirement.
    stamp = f"{RETIRED_STAMP_PREFIX}{dt.datetime.now().strftime(BACKUP_TIMESTAMP_FORMAT)}"
    destination = backup.free_destination(backup_dir, path.stem, stamp, WORKBOOK_SUFFIX)
    try:
        shutil.move(path, destination)
    except PermissionError as error:
        raise WorkbookLockedError(path.name) from error
    # Every suffix, not just the one a card paints: an image left behind would be inherited by the
    # next category to take this id.
    for artwork in heroes.hero_files(heroes_dir, retired_id):
        shutil.move(artwork, backup.free_destination(backup_dir, retired_id, stamp, artwork.suffix))
    return destination
