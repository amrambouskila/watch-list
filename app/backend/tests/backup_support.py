"""Reading back the restore points a write left behind, shared by every suite that asserts on them."""

from __future__ import annotations

from tv_watchlist.config import Settings
from tv_watchlist.constants import WORKBOOK_SUFFIX
from workbook_facts import WorkbookFacts


def restore_points(settings: Settings, subject: WorkbookFacts) -> list[bytes]:
    """The contents of every backup copy taken of this workbook so far."""
    return [path.read_bytes() for path in sorted(settings.backup_dir.glob(f"{subject.stem}__*{WORKBOOK_SUFFIX}"))]
