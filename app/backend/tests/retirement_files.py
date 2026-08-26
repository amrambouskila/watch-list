"""Finding what a retirement left in the backups folder, and telling it from a routine snapshot."""

from __future__ import annotations

from pathlib import Path

from tv_watchlist.constants import RETIRED_STAMP_PREFIX, WORKBOOK_SUFFIX
from tv_watchlist.workbook import backup_names


def _filed_under(backup_dir: Path, stem: str, suffix: str) -> list[Path]:
    """Everything filed under exactly this stem, so a neighbouring name is never counted as one."""
    if not backup_dir.is_dir():
        return []
    return sorted(
        path for path in backup_dir.iterdir() if path.suffix == suffix and backup_names.belongs_to(path, stem)
    )


def retirements(backup_dir: Path, stem: str, suffix: str) -> list[Path]:
    """What has been retired under one name, which the retention window must never govern."""
    return [path for path in _filed_under(backup_dir, stem, suffix) if backup_names.is_a_retirement(path)]


def snapshots(backup_dir: Path, stem: str) -> list[Path]:
    """The routine restore points taken of one workbook, which the retention window does govern."""
    return [path for path in _filed_under(backup_dir, stem, WORKBOOK_SUFFIX) if not backup_names.is_a_retirement(path)]


def stamp_of(path: Path, stem: str) -> str:
    """The stamp a retirement was filed under, so a workbook and its artwork can be shown to share one."""
    return path.name[len(f"{stem}{backup_names.SEPARATOR}{RETIRED_STAMP_PREFIX}") : -len(path.suffix)]
