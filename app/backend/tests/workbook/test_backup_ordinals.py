"""Copies sharing one second are numbered, and the numbering has to sort the way they were taken."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from tv_watchlist.constants import WORKBOOK_SUFFIX
from tv_watchlist.workbook.backup import free_destination

A_STAMP: Final[str] = "20260826-120000"
A_STEM: Final[str] = "A Watch Order"
# Past nine, so the copy whose ordinal grew a digit is inside the run rather than beyond it.
COPIES: Final[int] = 12


def test_copies_sharing_a_second_sort_in_the_order_they_were_taken(tmp_path: Path) -> None:
    """Pruning reads restore points in name order, so a tenth copy must not sort before the second."""
    taken: list[Path] = []
    for _ in range(COPIES):
        destination = free_destination(tmp_path, A_STEM, A_STAMP, WORKBOOK_SUFFIX)
        destination.write_bytes(b"")
        taken.append(destination)

    assert sorted(tmp_path.iterdir()) == taken


def test_the_first_copy_of_a_second_is_still_unnumbered(tmp_path: Path) -> None:
    """Numbering only settles ties, so the name a lone copy files under does not change."""
    assert free_destination(tmp_path, A_STEM, A_STAMP, WORKBOOK_SUFFIX).name == f"{A_STEM}__{A_STAMP}{WORKBOOK_SUFFIX}"
