"""Shared scaffolding for the three mirror suites - one projected shape, one entry-and-category
builder, one way to say "somebody else saved this file" without changing what it says.

`test_mirror_race.py`, `test_watch_mirror_database.py` and `test_watch_mirror_writeback.py` each grew
their own copy of the same handful of helpers, and the copies drifted (CLAUDE.md section 7: "search
before writing"). `Projected` is the union of every surface a suite reached for (`cell`, `observed`,
`statuses`); `entries_for` and `category_row` take the most general shape and let each caller pass
what it has, through a keyword-only `path` rather than a second function.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Final

from tv_watchlist.constants import FIRST_DATA_ROW, UNWATCHED
from tv_watchlist.data.models import Category, CuratedEntry
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.reader import read_category

# Far enough ahead that the 1e-6 tolerance `guard_fresh` allows cannot absorb it.
A_STAMP_AHEAD: Final[float] = 10.0
AN_UNCHANGED_SAVE: Final[str] = "saved without editing anything"

SecondWriter = Callable[[Catalog], Awaitable[str]]


def row_of(entry: CuratedEntry) -> int:
    """The sheet row an already-minted entry lives on. Every entry built here has one."""
    row = entry.sheet_row
    assert row is not None
    return row


class Projected:
    """A category already ingested once: its rows carry Row IDs, and the entries know their own.

    `cell` reads any column of one entry's row, the watch column unless told otherwise; `observed` is
    every entry's watch cell keyed by entry id, the shape `human_edit_events` wants; `statuses` is
    every status cell in the sheet, for a test that wants to say a value is nowhere in it. All three
    read the sheet fresh on every call, so a test can write through the app and then ask what changed.
    """

    def __init__(self, path: Path, category: Category, entries: Sequence[CuratedEntry], watch_key: str) -> None:
        self.path = path
        self.category = category
        self.entries = list(entries)
        self.watch_key = watch_key

    def _cells(self) -> dict[int, dict[str, str]]:
        return {row.row: dict(row.cells) for row in read_category(self.path).rows}

    def cell(self, entry: CuratedEntry, key: str | None = None) -> str:
        """One of that entry's cells as the sheet now reads it; the status column unless asked otherwise."""
        return self._cells().get(row_of(entry), {}).get(key or self.watch_key, UNWATCHED).strip()

    def observed(self) -> dict[uuid.UUID, str]:
        """Every entry's status cell, keyed by entry id - what the next ingest would read off the sheet."""
        cells = self._cells()
        return {entry.id: cells.get(row_of(entry), {}).get(self.watch_key, UNWATCHED).strip() for entry in self.entries}

    def statuses(self) -> list[str]:
        """Every status cell in the sheet, so a test can say the mirror's value is nowhere in it."""
        return [cells.get(self.watch_key, UNWATCHED).strip() for cells in self._cells().values()]


def category_row(detail: CategoryDetail, category_id: uuid.UUID) -> Category:
    """A `Category` row shaped the way a first ingest would have stored it, from an already-read detail.

    Takes a `CategoryDetail` rather than a `Path` because a caller that minted identities into the
    sheet first needs its own `read_category` call anyway, to see the post-mint state; handing that
    same read in here means the mtime this row carries is never one call behind the caller's own.
    """
    return Category(
        id=category_id,
        slug=detail.id,
        file_name=detail.file_name,
        sheet_title=detail.sheet_title,
        accent=detail.accent,
        workbook_mtime=detail.mtime,
    )


def entries_for(category_id: uuid.UUID, rows: int, *, path: Path | None = None) -> list[CuratedEntry]:
    """The rows a first ingest would have made.

    With `path`, cells are read verbatim off that sheet and set into `raw_cells` alongside
    `observed_watch_cell` - required wherever these entries are flushed into a real session, since
    `raw_cells` has no column default to fall back on at flush time. Without `path` the entries are
    for the pure detached half, which never flushes and never reads either field, so only
    `mirrored_watch_cell` - the one field every caller compares against directly, flushed or not - is
    set on them.
    """
    positions = range(FIRST_DATA_ROW, FIRST_DATA_ROW + rows)
    made: list[CuratedEntry]
    if path is not None:
        cells_by_row = {row.row: dict(row.cells) for row in read_category(path).rows}
        made = [
            CuratedEntry(
                id=uuid.uuid4(),
                category_id=category_id,
                position=position,
                sheet_row=row,
                raw_cells=cells_by_row[row],
                observed_watch_cell=UNWATCHED,
            )
            for position, row in enumerate(positions, start=1)
        ]
    else:
        made = [
            CuratedEntry(id=uuid.uuid4(), category_id=category_id, position=position, sheet_row=row)
            for position, row in enumerate(positions, start=1)
        ]
    for entry in made:
        entry.mirrored_watch_cell = UNWATCHED
    return made


def moved_on(path: Path) -> None:
    """Somebody saved the file since the stamp in hand was taken."""
    stamp = path.stat().st_mtime + A_STAMP_AHEAD
    os.utime(path, (stamp, stamp))


def a_save_that_changed_nothing(path: Path) -> SecondWriter:
    """Excel closing a file it did not edit: a new stamp over a grid that still says the same thing.

    Not a contrivance - it is the reason `workbook_digest` exists at all. Shaped as a `SecondWriter` so
    `test_mirror_race.py`'s contest apparatus can run it in front of a forwarded write exactly like a
    real edit.
    """

    async def saved(_: Catalog) -> str:
        moved_on(path)
        return AN_UNCHANGED_SAVE

    return saved
