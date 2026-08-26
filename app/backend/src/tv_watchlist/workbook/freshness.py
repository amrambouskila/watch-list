"""Refuse a write aimed at a version of a workbook that is no longer the one on disk."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from tv_watchlist.workbook.errors import StaleWorkbookError

# An mtime crosses the wire as a JSON float and comes back rounded, so equality is too strict a test.
MTIME_TOLERANCE_SECONDS: Final[float] = 1e-6


def guard_fresh(path: Path, expected_mtime: float) -> None:
    """Raise unless the file still carries the timestamp the caller last read from it."""
    if abs(path.stat().st_mtime - expected_mtime) > MTIME_TOLERANCE_SECONDS:
        raise StaleWorkbookError(path.name)
