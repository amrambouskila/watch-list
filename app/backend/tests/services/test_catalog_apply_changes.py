from __future__ import annotations

from pathlib import Path

import pytest

from tv_watchlist.config import Settings
from tv_watchlist.constants import FIRST_DATA_ROW
from tv_watchlist.models.row_change import RowChange
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.errors import StaleWorkbookError
from workbook_facts import WorkbookFacts

STALE_MTIME = 0.0
ANCHORED_TITLE = "Interlude"
FIRST_NOTE = "one"
SECOND_NOTE = "two"
DUPLICATE_REASON = "duplicate"
RESEARCHED_REASON = "researched"


@pytest.fixture
def unthrottled_catalog(settings: Settings) -> Catalog:
    """A catalog that snapshots on every write, so backups count the writes a call made."""
    return Catalog(settings.model_copy(update={"backup_interval_seconds": 0.0}))


async def test_a_batch_is_applied_and_the_reloaded_category_comes_back(
    catalog: Catalog, subject: WorkbookFacts
) -> None:
    before = await catalog.detail(subject.category_id)
    titles = [row.cells[subject.title_key] for row in before.rows]

    after = await catalog.apply_changes(
        subject.category_id,
        [
            RowChange(kind="remove", row=FIRST_DATA_ROW, reason=DUPLICATE_REASON),
            RowChange(
                kind="add",
                after_row=FIRST_DATA_ROW + 1,
                cells={subject.title_key: ANCHORED_TITLE},
                reason=RESEARCHED_REASON,
            ),
        ],
        before.mtime,
    )

    assert after.counts.total == before.counts.total
    assert [row.cells[subject.title_key] for row in after.rows] == [titles[1], ANCHORED_TITLE, *titles[2:]]
    assert after.mtime != before.mtime


async def test_a_whole_batch_leaves_one_backup_holding_the_pre_batch_workbook(
    unthrottled_catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    original = subject_path.read_bytes()
    before = await unthrottled_catalog.detail(subject.category_id)

    await unthrottled_catalog.apply_changes(
        subject.category_id,
        [
            RowChange(kind="revise", row=FIRST_DATA_ROW, cells={subject.free_text_key: FIRST_NOTE}),
            RowChange(kind="revise", row=FIRST_DATA_ROW + 1, cells={subject.free_text_key: SECOND_NOTE}),
            RowChange(kind="remove", row=FIRST_DATA_ROW + 2),
        ],
        before.mtime,
    )

    assert [snapshot.read_bytes() for snapshot in sorted(settings.backup_dir.iterdir())] == [original]


async def test_a_stale_mtime_refuses_the_batch_before_anything_is_written(
    catalog: Catalog, subject: WorkbookFacts, subject_path: Path
) -> None:
    before = subject_path.read_bytes()

    with pytest.raises(StaleWorkbookError):
        await catalog.apply_changes(subject.category_id, [RowChange(kind="remove", row=FIRST_DATA_ROW)], STALE_MTIME)

    assert subject_path.read_bytes() == before
