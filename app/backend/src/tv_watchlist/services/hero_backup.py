"""Keep the artwork a category is losing, so replacing a card image is never destroying one."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from tv_watchlist.constants import BACKUP_TIMESTAMP_FORMAT, HERO_SUFFIXES
from tv_watchlist.workbook.backup import free_destination


def retire_heroes(heroes_dir: Path, backup_dir: Path, category_id: str) -> None:
    """Leave the category with no hero file, each one it had moved aside under a timestamp."""
    stamp = dt.datetime.now().strftime(BACKUP_TIMESTAMP_FORMAT)
    for suffix in HERO_SUFFIXES:
        standing = heroes_dir / f"{category_id}{suffix}"
        if not standing.is_file():
            continue
        backup_dir.mkdir(parents=True, exist_ok=True)
        # A hand-made, hand-recoloured mark is the one thing in this app that cannot be fetched
        # again, so the image being replaced is moved rather than unlinked -- and moved to a name
        # nothing already holds, because the stamp is only accurate to the second and two picks for
        # one category can easily fall inside one.
        shutil.move(standing, free_destination(backup_dir, category_id, stamp, suffix))
