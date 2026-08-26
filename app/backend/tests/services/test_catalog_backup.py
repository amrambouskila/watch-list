"""Which writes are guaranteed a restore point, and which the throttle is allowed to coalesce."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final

import pytest

from library_choice import a_name_the_library_does_not_hold
from tv_watchlist.config import Settings
from tv_watchlist.constants import FIRST_DATA_ROW, WORKBOOK_SUFFIX
from tv_watchlist.models.category_rename import CategoryRename
from tv_watchlist.models.row_change import RowChange
from tv_watchlist.models.row_write import RowWrite
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.naming import workbook_filename
from workbook_facts import WorkbookFacts

Write = Callable[[Catalog, WorkbookFacts, float], Awaitable[None]]

TICKS: Final[int] = 3
CELL_EDIT: Final[str] = "ticked by hand"
RESEARCHED_NOTE: Final[str] = "the whole rewrite an agent proposed"
APPENDED_TITLE: Final[str] = "One more entry"
FRESH_STEM: Final[str] = Path(workbook_filename(a_name_the_library_does_not_hold("Renamed Watch Order"))).stem


def restore_points(settings: Settings, subject: WorkbookFacts) -> list[bytes]:
    """The contents of every backup copy taken of this workbook so far."""
    return [path.read_bytes() for path in sorted(settings.backup_dir.glob(f"{subject.stem}__*{WORKBOOK_SUFFIX}"))]


async def a_hand_edit(catalog: Catalog, subject: WorkbookFacts) -> None:
    """The routine single-cell write the throttle exists for, which spends this process's snapshot."""
    detail = await catalog.detail(subject.category_id)
    await catalog.update_row(
        subject.category_id,
        FIRST_DATA_ROW,
        RowWrite(cells={subject.free_text_key: CELL_EDIT}, expected_mtime=detail.mtime),
    )


async def a_bulk_apply(catalog: Catalog, subject: WorkbookFacts, mtime: float) -> None:
    await catalog.apply_changes(
        subject.category_id,
        [RowChange(kind="revise", row=FIRST_DATA_ROW, cells={subject.free_text_key: RESEARCHED_NOTE})],
        mtime,
    )


async def a_row_deletion(catalog: Catalog, subject: WorkbookFacts, mtime: float) -> None:
    await catalog.delete_row(subject.category_id, FIRST_DATA_ROW, mtime)


async def a_row_append(catalog: Catalog, subject: WorkbookFacts, mtime: float) -> None:
    await catalog.append_row(
        subject.category_id, RowWrite(cells={subject.title_key: APPENDED_TITLE}, expected_mtime=mtime)
    )


async def a_rename(catalog: Catalog, subject: WorkbookFacts, mtime: float) -> None:
    await catalog.rename_category(subject.category_id, CategoryRename(stem=FRESH_STEM, expected_mtime=mtime))


@pytest.mark.parametrize(
    "write", [a_bulk_apply, a_row_deletion, a_row_append, a_rename], ids=["apply", "delete", "append", "rename"]
)
async def test_a_write_beyond_a_single_cell_snapshots_even_when_a_hand_edit_just_did(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path, write: Write
) -> None:
    await a_hand_edit(catalog, subject)
    about_to_be_rewritten = subject_path.read_bytes()

    await write(catalog, subject, (await catalog.detail(subject.category_id)).mtime)

    assert about_to_be_rewritten in restore_points(settings, subject)


async def test_a_run_of_hand_edits_is_still_coalesced_into_one_restore_point(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    untouched = subject_path.read_bytes()

    for _ in range(TICKS):
        await a_hand_edit(catalog, subject)

    assert restore_points(settings, subject) == [untouched]


async def test_a_second_write_in_the_same_second_does_not_overwrite_the_first_restore_point(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    """Backup names are stamped to the second, and two writes beyond a single cell can share one."""
    untouched = subject_path.read_bytes()

    await a_row_deletion(catalog, subject, (await catalog.detail(subject.category_id)).mtime)
    await a_bulk_apply(catalog, subject, (await catalog.detail(subject.category_id)).mtime)

    assert untouched in restore_points(settings, subject)
