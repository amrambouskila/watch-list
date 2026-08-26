"""A retirement lives in the same folder as the snapshots, and must not be pruned away with them."""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from library_choice import a_name_the_library_does_not_hold, another_category
from retirement_files import retirements, snapshots
from tv_watchlist.config import Settings
from tv_watchlist.constants import WORKBOOK_SUFFIX
from tv_watchlist.services import retirement
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook import backup
from tv_watchlist.workbook.backup_names import SEPARATOR
from workbook_facts import WorkbookFacts

# Enough writes past the retention window that anything the window governs is certainly gone.
SNAPSHOTS_BEYOND_RETENTION: Final[int] = 5
# One more retirement of a name than the window would ever keep of anything.
RETIREMENTS_BEYOND_RETENTION: Final[int] = 1
# What the owner may put after the separator in a name of his own: the app builds this stem itself
# from a typed name like "Alpha_ 1999", and both sort ahead of any timestamp.
SEGMENTS_A_NAME_MAY_CARRY: Final[tuple[str, ...]] = ("1999", "-Side")


def take_a_snapshot(settings: Settings, path: Path) -> None:
    """One restore point of a workbook, with the throttle stood down so every call takes one."""
    backup.snapshot(path, settings.backup_dir, settings.backup_retention, backup.NO_THROTTLE)


async def test_a_retirement_outlives_a_new_workbook_of_the_same_name_filling_the_retention_window(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    """A namesake's snapshots share the retired workbook's stem, so the window must not count it."""
    original = subject_path.read_bytes()
    await catalog.retire_category(subject.category_id, (await catalog.detail(subject.category_id)).mtime)
    subject_path.write_bytes(another_category().copied_into(settings.library_dir).read_bytes())

    for _ in range(settings.backup_retention + SNAPSHOTS_BEYOND_RETENTION):
        take_a_snapshot(settings, subject_path)

    retired = retirements(settings.backup_dir, subject.stem, WORKBOOK_SUFFIX)
    assert [path.read_bytes() for path in retired] == [original]
    assert len(snapshots(settings.backup_dir, subject.stem)) == settings.backup_retention


def test_no_number_of_retirements_of_one_name_lets_the_retention_window_reach_them(
    settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    """Every retirement is the only copy of what it holds, so retention governs none of them."""
    original = subject_path.read_bytes()
    wanted = settings.backup_retention + RETIREMENTS_BEYOND_RETENTION

    for _ in range(wanted):
        subject_path.write_bytes(original)
        retirement.retire_category(subject_path, settings.heroes_dir, settings.backup_dir, subject_path.stat().st_mtime)
    # Pruning only ever runs from a snapshot, so a namesake has to take one for the window to move.
    subject_path.write_bytes(original)
    take_a_snapshot(settings, subject_path)

    assert len(retirements(settings.backup_dir, subject.stem, WORKBOOK_SUFFIX)) == wanted
    assert len(snapshots(settings.backup_dir, subject.stem)) == 1


@pytest.mark.parametrize("segment", SEGMENTS_A_NAME_MAY_CARRY)
def test_a_retirement_is_not_pruned_by_a_category_its_name_merely_begins_with(
    settings: Settings, subject: WorkbookFacts, subject_path: Path, segment: str
) -> None:
    """A stem may carry the separator, so a neighbour must never mistake this retirement for its own."""
    neighbour_stem = a_name_the_library_does_not_hold(f"{subject.stem}{SEPARATOR}{segment}")
    neighbour = settings.library_dir / f"{neighbour_stem}{WORKBOOK_SUFFIX}"
    neighbour.write_bytes(subject_path.read_bytes())
    original = neighbour.read_bytes()

    retirement.retire_category(neighbour, settings.heroes_dir, settings.backup_dir, neighbour.stat().st_mtime)
    for index in range(settings.backup_retention + SNAPSHOTS_BEYOND_RETENTION):
        subject_path.write_bytes(original + str(index).encode())
        take_a_snapshot(settings, subject_path)

    retired = retirements(settings.backup_dir, neighbour_stem, WORKBOOK_SUFFIX)
    assert [path.read_bytes() for path in retired] == [original]


@pytest.mark.parametrize("segment", SEGMENTS_A_NAME_MAY_CARRY)
def test_a_neighbours_restore_points_are_not_pruned_by_the_name_they_begin_with(
    settings: Settings, subject: WorkbookFacts, subject_path: Path, segment: str
) -> None:
    """Two categories whose stems share a leading segment keep two separate retention windows."""
    neighbour_stem = a_name_the_library_does_not_hold(f"{subject.stem}{SEPARATOR}{segment}")
    neighbour = settings.library_dir / f"{neighbour_stem}{WORKBOOK_SUFFIX}"
    neighbour.write_bytes(subject_path.read_bytes())

    for index in range(settings.backup_retention):
        neighbour.write_bytes(f"neighbour-{index}".encode())
        take_a_snapshot(settings, neighbour)
    for index in range(settings.backup_retention + SNAPSHOTS_BEYOND_RETENTION):
        subject_path.write_bytes(f"subject-{index}".encode())
        take_a_snapshot(settings, subject_path)

    assert len(snapshots(settings.backup_dir, neighbour_stem)) == settings.backup_retention
    assert len(snapshots(settings.backup_dir, subject.stem)) == settings.backup_retention
