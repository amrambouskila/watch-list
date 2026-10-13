"""A combined player snapshot uses the existing guarded, backed-up Catalog write path."""

from __future__ import annotations

from pathlib import Path

import pytest

from backup_support import restore_points
from tv_watchlist.config import Settings
from tv_watchlist.constants import FIRST_DATA_ROW, WATCHED
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.errors import StaleWorkbookError
from tv_watchlist.workbook.reader import read_projection
from workbook_facts import WorkbookFacts

FIRST_POSITION_SECONDS = 60
SECOND_POSITION_SECONDS = 120


async def test_each_snapshot_has_one_unthrottled_restore_point(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    before = subject_path.read_bytes()
    detail = await catalog.detail(subject.category_id)
    first = await catalog.apply_position_writeback(
        subject.category_id, {FIRST_DATA_ROW: FIRST_POSITION_SECONDS}, {}, detail.mtime
    )
    intermediate = subject_path.read_bytes()
    second = await catalog.apply_position_writeback(
        subject.category_id,
        {FIRST_DATA_ROW: SECOND_POSITION_SECONDS},
        {FIRST_DATA_ROW: {subject.watch_key: WATCHED}},
        first.mtime,
    )
    assert restore_points(settings, subject) == [before, intermediate]
    assert second.rows[0].cells[subject.watch_key] == WATCHED
    assert read_projection(subject_path).position_values[FIRST_DATA_ROW] == str(SECOND_POSITION_SECONDS)
    assert (await catalog.detail(subject.category_id)).mtime == pytest.approx(second.mtime)


async def test_stale_snapshot_refuses_before_backup_or_mutation(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    before = subject_path.read_bytes()
    with pytest.raises(StaleWorkbookError):
        await catalog.apply_position_writeback(subject.category_id, {FIRST_DATA_ROW: FIRST_POSITION_SECONDS}, {}, 0.0)
    assert subject_path.read_bytes() == before
    assert restore_points(settings, subject) == []
