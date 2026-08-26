"""The `<stem>__<stamp>` convention every file in the backups folder is filed under."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from tv_watchlist.constants import RETIRED_STAMP_PREFIX

SEPARATOR: Final[str] = "__"


def filed_as(stem: str, stamp: str, suffix: str) -> str:
    """The filename one stem and one stamp make."""
    return f"{stem}{SEPARATOR}{stamp}{suffix}"


def stem_and_stamp(path: Path) -> tuple[str, str] | None:
    """
    The stem and stamp a backup filename carries, or None when it was not filed by this app.

    Read from the right: a stem may hold the separator itself, but a stamp written here never does,
    so anything ahead of the last separator is the stem however many the owner put in the name.
    """
    stem, separator, stamp = path.stem.rpartition(SEPARATOR)
    return (stem, stamp) if separator and stem else None


def belongs_to(path: Path, stem: str) -> bool:
    """True when this file was filed under exactly that stem, not merely one beginning with it."""
    read = stem_and_stamp(path)
    return read is not None and read[0] == stem


def is_a_retirement(path: Path) -> bool:
    """True when this file is a retired category rather than a restore point of a live one."""
    read = stem_and_stamp(path)
    return read is not None and read[1].startswith(RETIRED_STAMP_PREFIX)
