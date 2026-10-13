"""The four-value status projection: derived state onto the sheet, and the hand edits read back off it.

The projection is one dict and no branching, because the view has already collapsed a roll-up into one
of five kinds and those five map onto four cell values, with `started` and `progressed` sharing one. It
is **one-directional and lossy by construction**: the cell cannot say "9 of 35 episodes done", "42
minutes into episode 12", or "1-8 completed and 9-12 skipped". All of that lives in `watch_event`, and
writing the cell deletes none of it (CLAUDE.md section 5.16, section 11.2 rule 13).

Two columns contain the loss, and neither is redundant:

- `observed_watch_cell` is what the app last READ from the sheet.
- `mirrored_watch_cell` is what the app last WROTE into it.

A cell that differs from `mirrored_watch_cell` is a human edit, and becomes one coarse entry-level
`excel_mirror` event that sits on top of the episode history rather than erasing it. A cell that equals
it is our own echo, and is ignored. Without that stored last-written value every mirror write would look
like a hand edit on the next pass, append an event, re-derive the same status and rewrite the same cell
- a stable but ever-growing loop. Note the corollary: it is the WRITE that closes the loop, so a status
typed into Excel costs exactly one confirming rewrite before it settles. `mirrored_watch_cell` means the
value this app wrote, and recording a write that never happened would be the cheaper lie.

**The status cell is never read as truth.** It is read only to notice that a human moved it.

Every write goes through `Catalog._write` - one freshness guard, one `.backups` snapshot, one Excel-lock
check, one temp file, one `os.replace`. Of the two writers that can race, the mirror is the one that must
lose: the first attempt is guarded by the stamp the last ingest stored, and each retry re-reads the sheet
and gives up unless every row it planned to write still carries that entry's own id and still holds the
value the app last put there (master plan section 6.3).

**Two callers, one of them not yet built.** The reconciler uses the pure half - `human_edit_events`,
`pending_mirror_cells`, `writable_mirror_cells`, `record_mirrored`, `entry_watch_states` - and carries
the cells in its own single `apply_ingest_writeback`, with its own one retry. `mirror_entry`,
`mirror_category`, `write_mirror_cells`, `_still_ours` and `MIRROR_RETRY_ATTEMPTS` are the **standalone
mirror seam**, for a progress write that did not come from a workbook read: `POST /api/watch-events` in
Phase 3 (master plan section 6.6). They have no Phase 1 production caller by design - that is not dead
code, and deleting it would take the Phase 3 write path with it.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Final

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clock import utcnow
from tv_watchlist.constants import (
    IN_PROGRESS,
    MAX_MIRROR_NOTE_LITERAL,
    MIRROR_NOTE_TEMPLATE,
    MIRROR_RETRY_ATTEMPTS,
    SKIPPED,
    UNWATCHED,
    WATCHED,
)
from tv_watchlist.data.enums import WatchEventKind, WatchEventSource, WatchSubjectKind
from tv_watchlist.data.models import Category, CuratedEntry, WatchEvent
from tv_watchlist.models.cell_text import sanitize
from tv_watchlist.models.column_spec import ColumnKind, ColumnSpec
from tv_watchlist.models.row_change import RowChange, RowChangeKind
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.mirror_outcome import DEFERRED, UNCHANGED, WRITTEN, MirrorOutcome
from tv_watchlist.workbook.errors import StaleWorkbookError, WorkbookLockedError
from tv_watchlist.workbook.reader import WorkbookProjection
from tv_watchlist.workbook.schema import watch_column

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_JOB: Final[str] = "mirror"

# CLAUDE.md section 5.16 verbatim. Every value is imported from constants.py; none is re-declared.
_CELL_FOR_KIND: dict[WatchEventKind, str] = {
    WatchEventKind.COMPLETED: WATCHED,
    WatchEventKind.SKIPPED: SKIPPED,
    WatchEventKind.STARTED: IN_PROGRESS,
    WatchEventKind.PROGRESSED: IN_PROGRESS,
    WatchEventKind.UNSET: UNWATCHED,
}
# The inverse, for a cell a human typed. `started` rather than `progressed` for the in-progress value:
# `progressed_has_position` is a database CHECK and a status cell carries no position.
_KIND_FOR_CELL: dict[str, WatchEventKind] = {
    WATCHED: WatchEventKind.COMPLETED,
    SKIPPED: WatchEventKind.SKIPPED,
    IN_PROGRESS: WatchEventKind.STARTED,
    UNWATCHED: WatchEventKind.UNSET,
}

_REVISE: Final[RowChangeKind] = "revise"
_CHOICE: Final[ColumnKind] = "choice"
_INVALID_CHOICE: Final[str] = "invalid_choice"
_LOCKED: Final[str] = "locked"
_STALE: Final[str] = "stale"
_MOVED: Final[str] = "moved"
_NOT_INGESTED: Final[str] = "not_ingested"

# The derived status of every entry in one category, straight off the view revision 0001 raised. A
# constant string with one bound parameter - never a query assembled from anything (section 10.3, B13).
_ENTRY_STATES: Final[str] = (
    "SELECT curated_entry_id, kind FROM curated_entry_watch_state WHERE category_id = :category_id"
)


def watch_cell(kind: WatchEventKind) -> str:
    """The four-value `Watched?` value this derived state projects onto."""
    return _CELL_FOR_KIND[kind]


def kind_for_cell(cell: str) -> WatchEventKind | None:
    """What a human typing that cell meant, or `None` for text the sheet's own dropdown never offered."""
    return _KIND_FOR_CELL.get(cell.strip())


def human_edit_events(
    entries: Sequence[CuratedEntry], observed: Mapping[uuid.UUID, str], *, now: datetime
) -> list[WatchEvent]:
    """One coarse entry-level `excel_mirror` event per status cell a human moved, and none for our echo.

    `observed` is what the sheet was just read as saying, passed in rather than taken off the entry so
    that the comparison does not depend on the order in which a caller happened to refresh it. An entry
    the mapping says nothing about is skipped: a workbook with no status column reports no cell at all,
    and that is not an edit. Nothing here touches an episode event - the precedence rule in the
    `curated_entry_watch_state` view is what lets this coarse fact sit on top of the fine-grained history.
    """
    events = [event for entry in entries if (event := _edit_event(entry, observed, now)) is not None]
    _LOGGER.info("mirror_human_edits job=%s entries=%d events=%d", _JOB, len(entries), len(events))
    return events


def pending_mirror_cells(
    entries: Sequence[CuratedEntry], states: Mapping[uuid.UUID, WatchEventKind]
) -> dict[uuid.UUID, str]:
    """The entries whose derived state no longer matches the cell this app last wrote there.

    The throttle the master plan calls idempotence: an entry is written back only when the projection
    actually differs from the last value written, so a pass that changed nothing opens no workbook at
    all. A soft-deleted entry and one whose row left the sheet are both skipped - neither has a cell.
    """
    pending: dict[uuid.UUID, str] = {}
    for entry in entries:
        if entry.removed_at is not None or entry.sheet_row is None:
            continue
        state = states.get(entry.id)
        if state is not None and (cell := watch_cell(state)) != _mirrored(entry):
            pending[entry.id] = cell
    return pending


def writable_mirror_cells(
    pending: Mapping[uuid.UUID, str], column: ColumnSpec, *, category: str
) -> dict[uuid.UUID, str]:
    """The diff minus anything that column's own dropdown would refuse (Ruling 41).

    The status column is the owner's, not the app's. A sheet dropped into the library may offer
    `Yes,No` where the nineteen offer the four values, and `writer._validate` refuses the whole write on
    the first value it does not recognise - which on the ingest path rolls the entire pass back, so one
    odd dropdown would make that workbook permanently un-ingestable. The sheet's vocabulary wins: the
    cells it does not offer are dropped and logged, the rest still go in, and the entries behind the
    dropped ones keep their old `mirrored_watch_cell`, so nothing claims a write that never happened.

    A text column has no vocabulary to contradict, so nothing is dropped for one.
    """
    if column.kind != _CHOICE:
        return dict(pending)
    offered = set(column.choices)
    writable = {entry_id: cell for entry_id, cell in pending.items() if cell in offered}
    for entry_id in (found for found in pending if found not in writable):
        _LOGGER.info(
            "mirror_skipped_cell job=%s category=%s entry=%s skipped=%s", _JOB, category, entry_id, _INVALID_CHOICE
        )
    return writable


def record_mirrored(entries: Sequence[CuratedEntry], pending: Mapping[uuid.UUID, str]) -> None:
    """Remember what was just written. Called only after the write landed, and in its transaction."""
    for entry in entries:
        cell = pending.get(entry.id)
        if cell is not None:
            entry.mirrored_watch_cell = cell


async def entry_watch_states(session: AsyncSession, category_id: uuid.UUID) -> dict[uuid.UUID, WatchEventKind]:
    """Each entry's current status, derived by the view rather than stored anywhere.

    Flushed first, deliberately: a state that ignored the events this transaction has already staged
    would mirror a cell the same transaction is about to contradict.
    """
    await session.flush()
    rows = await session.execute(text(_ENTRY_STATES), {"category_id": category_id})
    return {row.curated_entry_id: WatchEventKind(row.kind) for row in rows}


async def mirror_entry(
    session: AsyncSession,
    catalog: Catalog,
    entry_id: uuid.UUID,
    *,
    clock: Callable[[], datetime] = utcnow,
) -> MirrorOutcome:
    """Project one entry's derived status onto its own row, and nothing else in that workbook."""
    await session.flush()
    found = (
        await session.execute(
            select(CuratedEntry, Category)
            .join(Category, Category.id == CuratedEntry.category_id)
            .where(CuratedEntry.id == entry_id)
        )
    ).first()
    if found is None:
        _LOGGER.warning("mirror_unknown_entry job=%s entry=%s", _JOB, entry_id)
        return UNCHANGED
    entry, category = found
    return await _mirrored_through(session, catalog, category, [entry], clock=clock)


async def mirror_category(
    session: AsyncSession,
    catalog: Catalog,
    category_id: uuid.UUID,
    *,
    clock: Callable[[], datetime] = utcnow,
) -> MirrorOutcome:
    """Project every live entry's derived status onto one workbook, in a single write."""
    await session.flush()
    category = await session.get(Category, category_id)
    if category is None:
        _LOGGER.warning("mirror_unknown_category job=%s category=%s", _JOB, category_id)
        return UNCHANGED
    entries = list(
        await session.scalars(
            select(CuratedEntry)
            .where(CuratedEntry.category_id == category_id, CuratedEntry.removed_at.is_(None))
            .order_by(CuratedEntry.position)
        )
    )
    return await _mirrored_through(session, catalog, category, entries, clock=clock)


async def write_mirror_cells(
    catalog: Catalog,
    category: Category,
    entries: Sequence[CuratedEntry],
    pending: Mapping[uuid.UUID, str],
    *,
    now: datetime,
) -> MirrorOutcome:
    """The workbook half: one `Catalog._write` for the whole diff, and both stores moved together.

    Takes the diff rather than computing it, so the session-bound half above and the reconciler's own
    pass share one write path. On success `mirrored_watch_cell`, `workbook_mtime` and `last_mirrored_at`
    are set on the caller's own objects, in the caller's transaction; if the write raises, none of the
    three moves and the identical diff replays on the next pass.
    """
    if not pending:
        _LOGGER.info("mirror_unchanged job=%s category=%s", _JOB, category.slug)
        return UNCHANGED
    if category.workbook_mtime is None:
        # Never ingested, so there is no stamp to guard the write with, and an unguarded write to the
        # owner's file is the one thing this app does not do.
        return _deferred(category, pending, _NOT_INGESTED)
    detail = await catalog.detail(category.slug)
    column = watch_column(detail.columns)
    if column is None:
        _LOGGER.info("mirror_no_watch_column job=%s category=%s", _JOB, category.slug)
        return UNCHANGED
    writable = writable_mirror_cells(pending, column, category=category.slug)
    if not writable:
        # Every value this pass wanted to write is one the sheet's own dropdown refuses, so there is
        # nothing left to say - and saying it would refuse the whole write rather than one cell.
        _LOGGER.info("mirror_unchanged job=%s category=%s", _JOB, category.slug)
        return UNCHANGED
    changes = [
        RowChange(kind=_REVISE, row=entry.sheet_row, cells={column.key: writable[entry.id]})
        for entry in entries
        if entry.id in writable
    ]

    expected: float | None = category.workbook_mtime
    for attempt in range(MIRROR_RETRY_ATTEMPTS):
        if expected is None:
            return _deferred(category, writable, _MOVED)
        try:
            written = await catalog.apply_changes(category.slug, changes, expected)
        except WorkbookLockedError:
            # Excel holds the file, or the swap itself was refused. Either way nothing was written.
            return _deferred(category, writable, _LOCKED)
        except StaleWorkbookError:
            _LOGGER.info(
                "mirror_retry job=%s category=%s attempt=%d cells=%d", _JOB, category.slug, attempt + 1, len(changes)
            )
            expected = await _still_ours(catalog, category.slug, entries, writable, column.key)
            continue
        record_mirrored(entries, writable)
        category.workbook_mtime = written.mtime
        category.last_mirrored_at = now
        _LOGGER.info(
            "mirror_written job=%s category=%s cells=%d attempts=%d", _JOB, category.slug, len(changes), attempt + 1
        )
        return WRITTEN
    return _deferred(category, writable, _STALE)


async def _mirrored_through(
    session: AsyncSession,
    catalog: Catalog,
    category: Category,
    entries: Sequence[CuratedEntry],
    *,
    clock: Callable[[], datetime],
) -> MirrorOutcome:
    states = await entry_watch_states(session, category.id)
    pending = pending_mirror_cells(entries, states)
    return await write_mirror_cells(catalog, category, entries, pending, now=clock())


async def _still_ours(
    catalog: Catalog,
    slug: str,
    entries: Sequence[CuratedEntry],
    pending: Mapping[uuid.UUID, str],
    watch_key: str,
) -> float | None:
    """The stamp to retry against, or `None` when the plan in hand no longer describes the sheet.

    Two things have to still hold for a retry to be safe, and both are checked per row: the row still
    carries that entry's own id, because a row number means nothing except against the grid it was
    resolved on; and the cell still holds what this app last wrote there, because anything else is a
    human edit the mirror must lose to rather than overwrite. A workbook carrying no identities at all
    fails the first check for every row, which is the honest answer - the mirror cannot prove which row
    it would be writing.
    """
    projection = await catalog.projection(slug)
    cells = {row.row: row.cells.get(watch_key, UNWATCHED).strip() for row in projection.detail.rows}
    # Every planned row is checked, not just up to the first failure: a refusal is the mirror losing a
    # race, and the log is the only place a reader learns how much of the plan the owner had taken over.
    contested = [entry for entry in entries if entry.id in pending and not _row_unmoved(projection, cells, entry)]
    if contested:
        _LOGGER.info("mirror_contested job=%s category=%s rows=%d of=%d", _JOB, slug, len(contested), len(pending))
        return None
    return projection.detail.mtime


def _row_unmoved(projection: WorkbookProjection, cells: Mapping[int, str], entry: CuratedEntry) -> bool:
    row = entry.sheet_row
    # `None`, never the empty cell: a row the sheet no longer carries an id for has no id, which is a
    # different thing from carrying an empty one.
    if row is None or projection.row_ids.get(row) != str(entry.id):
        _LOGGER.info("mirror_row_moved job=%s entry=%s row=%s", _JOB, entry.id, row)
        return False
    if cells.get(row, UNWATCHED) != _mirrored(entry):
        _LOGGER.info("mirror_cell_taken job=%s entry=%s row=%d", _JOB, entry.id, row)
        return False
    return True


def _edit_event(entry: CuratedEntry, observed: Mapping[uuid.UUID, str], now: datetime) -> WatchEvent | None:
    raw = observed.get(entry.id)
    if raw is None:
        return None
    # Stripped once, here, so the comparison and the reading agree: `kind_for_cell` strips before it
    # looks a value up, and a cell padded by hand would otherwise read as an edit and then as a value.
    cell = raw.strip()
    if cell == _mirrored(entry):
        return None
    kind = kind_for_cell(cell)
    if kind is None:
        # Text this app never wrote and cannot read. It is recorded rather than guessed at, and the cell
        # itself is left exactly as the owner typed it.
        _LOGGER.info("mirror_unknown_cell job=%s entry=%s cell=%s", _JOB, entry.id, _echoed(cell))
        return None
    return WatchEvent(
        occurred_at=now,
        subject_kind=WatchSubjectKind.CURATED_ENTRY,
        kind=kind,
        source=WatchEventSource.EXCEL_MIRROR,
        curated_entry_id=entry.id,
        category_id=entry.category_id,
        note=MIRROR_NOTE_TEMPLATE.format(literal=_echoed(cell)),
    )


def _deferred(category: Category, pending: Mapping[uuid.UUID, str], reason: str) -> MirrorOutcome:
    _LOGGER.info("mirror_deferred job=%s category=%s cells=%d reason=%s", _JOB, category.slug, len(pending), reason)
    return DEFERRED


def _mirrored(entry: CuratedEntry) -> str:
    """What this app last wrote into that cell. Unset until a row has been flushed once, and a row minted
    this pass has never been written to, so both read as the empty cell."""
    return entry.mirrored_watch_cell or UNWATCHED


def _echoed(literal: str) -> str:
    """Cell text as a note and a log record may carry it.

    Whitespace is collapsed first so no newline can forge a log line (section 10.3, header/log
    injection), then the project's one cell-text normaliser strips the control characters Excel itself
    refuses and clips the result.
    """
    return sanitize(" ".join(literal.split()), MAX_MIRROR_NOTE_LITERAL)
