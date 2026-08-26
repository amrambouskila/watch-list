"""Snapshot a workbook before this process modifies it for the first time."""

from __future__ import annotations

import datetime as dt
import shutil
import threading
import time
from pathlib import Path
from typing import Final

from tv_watchlist.constants import BACKUP_TIMESTAMP_FORMAT, WORKBOOK_SUFFIX
from tv_watchlist.workbook import backup_names

# The interval a write passes when it must never settle for an earlier snapshot: no elapsed time is
# ever less than zero, so nothing is skipped.
NO_THROTTLE: Final[float] = 0.0

# The first copy taken in a given second is unsuffixed; a second one earns "_02", and so on.
FIRST_SHARING_A_SECOND: Final[int] = 2
# Zero-padded, because the order these names sort in is the order pruning reads them in: unpadded, a
# tenth copy files as "_10", sorts ahead of "_2", and would be dropped as though it were the oldest.
# Two digits covers ninety-nine, and pruning leaves at most a retention window of copies of one
# workbook to collide inside a single second.
ORDINAL_WIDTH: Final[int] = 2

_last_snapshot: dict[Path, float] = {}
_guard = threading.Lock()


def free_destination(backup_dir: Path, stem: str, stamp: str, suffix: str) -> Path:
    """A name nothing in the backups folder already holds; the stamp is only accurate to the second."""
    candidate = backup_dir / backup_names.filed_as(stem, stamp, suffix)
    ordinal = FIRST_SHARING_A_SECOND
    # An underscore sorts after the suffix dot, so copies sharing a second stay behind that second
    # and ahead of the next one, which is the order pruning reads them in.
    while candidate.exists():
        candidate = backup_dir / backup_names.filed_as(stem, f"{stamp}_{ordinal:0{ORDINAL_WIDTH}d}", suffix)
        ordinal += 1
    return candidate


def _is_a_snapshot_of(path: Path, stem: str) -> bool:
    """A restore point of exactly this workbook: neither a neighbour's nor a retirement."""
    if not (path.is_file() and path.suffix == WORKBOOK_SUFFIX):
        return False
    # A retired category files under the same stem a later namesake would, and unlike a restore point
    # it is the only copy of itself: the retention window must never reach it.
    return backup_names.belongs_to(path, stem) and not backup_names.is_a_retirement(path)


def _prune(backup_dir: Path, stem: str, retention: int) -> None:
    """Drop all but the newest `retention` restore points of one workbook."""
    existing = sorted(path for path in backup_dir.iterdir() if _is_a_snapshot_of(path, stem))
    for stale in existing[:-retention]:
        stale.unlink(missing_ok=True)


def snapshot(path: Path, backup_dir: Path, retention: int, interval_seconds: float) -> Path | None:
    """
    Copy the workbook aside before it is modified, at most once per interval.

    A long editing session should leave a trail of restore points, not just one from whenever
    the server happened to start, and no copy ever displaces one already taken.
    """
    key = path.resolve()
    with _guard:
        previous = _last_snapshot.get(key)
        if previous is not None and time.monotonic() - previous < interval_seconds:
            return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime(BACKUP_TIMESTAMP_FORMAT)
    destination = free_destination(backup_dir, path.stem, stamp, WORKBOOK_SUFFIX)
    shutil.copy2(path, destination)
    # Recorded only once the copy exists, so a failed backup is retried rather than skipped.
    with _guard:
        _last_snapshot[key] = time.monotonic()
    _prune(backup_dir, path.stem, retention)
    return destination


def reset() -> None:
    """Forget when each workbook was last snapshotted; used by tests."""
    with _guard:
        _last_snapshot.clear()
