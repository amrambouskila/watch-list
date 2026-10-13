"""The two-writer race, proved rather than assumed: the mirror loses, retries, and defers.

Of the two writers that can reach one workbook the mirror is the one that must lose, and the master
plan (section 6.3) says that ordering is "implemented deliberately rather than left to chance". A
sentence is not an implementation, so every refusal below is a real one: a second writer performs an
actual `Catalog.update_row` or `Catalog.delete_row` against the same throwaway copy of one of the
owner's own workbooks, and the production `guard_fresh` refuses the mirror's write because the stamp in
its hand has genuinely moved on.

Nothing here stands in for the workbook layer (CLAUDE.md section 16.4). `_ASecondWriterInFront` holds a
real `Catalog`, subclasses nothing and fakes nothing: `detail`, `projection`, `apply_changes` and
`apply_ingest_writeback` are forwarded to the production methods with the arguments the caller passed,
and all this adds is the other writer, in front of the forwarded write, which is exactly where the
owner's own save lands. A hand-written `raise StaleWorkbookError` would prove the mirror handles an
exception; this proves it loses the race, and a regression in `guard_fresh` itself fails these tests
rather than sailing past a manufactured one.

Postgres is needed only by the last two sections - the session-bound `mirror_entry` seam and the
reconciler's own write-back, which are where the race happens in production. Everything the workbook
half can prove is proved against `write_mirror_cells`, which needs no database at all.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Final

import pytest
from httpx import ASGITransport, AsyncClient
from mirror_support import (
    Projected,
    SecondWriter,
    a_save_that_changed_nothing,
    category_row,
    entries_for,
    row_of,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backup_support import restore_points
from snapshot import fingerprint
from tv_watchlist.api.dependencies import get_catalog
from tv_watchlist.config import Settings
from tv_watchlist.constants import (
    FIRST_DATA_ROW,
    MIRROR_RETRY_ATTEMPTS,
    UNWATCHED,
    WATCHED,
)
from tv_watchlist.data.enums import WatchEventKind, WatchEventSource, WatchSubjectKind
from tv_watchlist.data.models import Category, CuratedEntry, WatchEvent
from tv_watchlist.ingest.reconciler import Reconciler
from tv_watchlist.main import create_app
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.models.row_change import RowChange
from tv_watchlist.models.row_write import RowWrite
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.mirror_outcome import DEFERRED, WRITTEN, MirrorOutcome
from tv_watchlist.services.watch_mirror import mirror_entry, write_mirror_cells
from tv_watchlist.workbook.errors import StaleWorkbookError, WorkbookError
from tv_watchlist.workbook.identity import ensure_identity_column, write_row_ids
from tv_watchlist.workbook.locking import lock_for
from tv_watchlist.workbook.reader import WorkbookProjection, read_category
from workbook_facts import WorkbookFacts

NOW: Final[datetime] = datetime(2026, 9, 20, 16, 0, tzinfo=UTC)
TWO_ROWS: Final[int] = 2
# The mirror's plan names one row; a second writer saving once is the ordinary race.
ONE_SAVE: Final[int] = 1
ONE_ATTEMPT: Final[int] = 1
# One refused write and one that lands: the shape the acceptance line calls "retries on Stale".
ATTEMPTS_WITH_ONE_RETRY: Final[int] = 2
# The owner's edit snapshots, and so does the mirror's retry; the refused attempt does not, because
# `guard_fresh` runs before `_snapshot` in `Catalog._mutate`.
RESTORE_POINTS_FOR_TWO_LANDED_WRITES: Final[int] = 2
ONE_RESTORE_POINT: Final[int] = 1
A_HAND_EDIT: Final[str] = "the owner typed this, save {save}"
A_DELETED_ROW: Final[str] = "row {row} deleted"
A_UI_EDIT_THAT_RACED_AHEAD: Final[str] = "typed while the mirror was writing"
# Long enough that a task blocked only by the lock has certainly reached it, short enough that the
# suite does not notice. The assertion is that it is still parked, so a slow machine cannot flake it.
PARKED_SECONDS: Final[float] = 0.25
CONFLICT: Final[int] = 409


# -- the second writer, in front of a real catalog ---------------------------------------------------


@dataclass(frozen=True)
class _Target:
    """The one workbook a second writer saves over, and the single cell it is allowed to touch."""

    slug: str
    path: Path
    row: int
    key: str


Contest = Callable[[_Target], SecondWriter]


def _a_cell_edit(target: _Target) -> SecondWriter:
    """The owner revising a cell the mirror's plan says nothing about, through the app's own write path.

    Numbered, so a test that lets it save several times can prove which of its writes is the one
    standing in the sheet at the end - and therefore that every refusal in between was a real one.
    """
    saves = count(1)

    async def edit(catalog: Catalog) -> str:
        value = A_HAND_EDIT.format(save=next(saves))
        detail = await catalog.detail(target.slug)
        await catalog.update_row(
            target.slug, target.row, RowWrite(cells={target.key: value}, expected_mtime=detail.mtime)
        )
        return value

    return edit


def _a_deleted_row(target: _Target) -> SecondWriter:
    """The owner removing the very row the mirror was about to write, which lifts every row below it."""

    async def delete(catalog: Catalog) -> str:
        detail = await catalog.detail(target.slug)
        await catalog.delete_row(target.slug, target.row, detail.mtime)
        return A_DELETED_ROW.format(row=target.row)

    return delete


class _ASecondWriterInFront:
    """A real `Catalog` with somebody else saving the file just before each write is forwarded.

    Wrapped rather than subclassed, and nothing about the catalog it holds is altered: every method
    below hands the caller's own arguments to the production one and returns what it returns. What this
    adds is the second writer - a genuine `update_row`, `delete_row` or re-save against the same file -
    run before the write goes through, which is where the owner's save lands in production and is what
    makes the race deterministic without faking any part of it.

    What it records is what a reader needs to tell a loss from a win: the stamp each forwarded write was
    guarded on, the refusal each one met, and what the second writer actually put in the sheet.
    """

    def __init__(self, catalog: Catalog, second_writer: SecondWriter, *, saves: int = ONE_SAVE) -> None:
        self._catalog = catalog
        self._second_writer = second_writer
        self._saves = saves
        self.forwarded: list[float] = []
        self.refused: list[str] = []
        self.saved: list[str] = []

    @property
    def attempts(self) -> int:
        """How many times the mirror reached the real `Catalog._write`."""
        return len(self.forwarded)

    async def detail(self, wanted_id: str) -> CategoryDetail:
        return await self._catalog.detail(wanted_id)

    async def projection(self, wanted_id: str) -> WorkbookProjection:
        return await self._catalog.projection(wanted_id)

    async def apply_changes(self, wanted_id: str, changes: list[RowChange], expected_mtime: float) -> CategoryDetail:
        return await self._forwarded(
            expected_mtime, lambda: self._catalog.apply_changes(wanted_id, changes, expected_mtime)
        )

    async def apply_ingest_writeback(
        self,
        wanted_id: str,
        ids_by_row: Mapping[int, str],
        cells_by_row: Mapping[int, Mapping[str, str]],
        expected_mtime: float,
    ) -> CategoryDetail:
        return await self._forwarded(
            expected_mtime,
            lambda: self._catalog.apply_ingest_writeback(wanted_id, ids_by_row, cells_by_row, expected_mtime),
        )

    async def _forwarded(self, expected_mtime: float, write: Callable[[], Awaitable[CategoryDetail]]) -> CategoryDetail:
        if len(self.saved) < self._saves:
            self.saved.append(await self._second_writer(self._catalog))
        self.forwarded.append(expected_mtime)
        try:
            return await write()
        except WorkbookError as refusal:
            self.refused.append(type(refusal).__name__)
            raise


# -- one workbook as a first ingest leaves it --------------------------------------------------------


def _minted_into(path: Path, entries: list[CuratedEntry]) -> None:
    ensure_identity_column(path)
    write_row_ids(path, {row_of(entry): str(entry.id) for entry in entries})


@pytest.fixture
def projected(subject_path: Path, subject: WorkbookFacts) -> Projected:
    """The detached shape: real workbook, real identities, ORM rows no session has seen."""
    category_id = uuid.uuid4()
    entries = entries_for(category_id, TWO_ROWS, path=subject_path)
    _minted_into(subject_path, entries)
    return Projected(subject_path, category_row(read_category(subject_path), category_id), entries, subject.watch_key)


@pytest.fixture
async def client(catalog: Catalog) -> AsyncIterator[AsyncClient]:
    """The real app over the same `Catalog` the mirror writes through, so both see one library."""
    app = create_app()
    app.dependency_overrides[get_catalog] = lambda: catalog
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client


def _target(projected: Projected, subject: WorkbookFacts) -> _Target:
    """The owner's next save: this workbook, the row the mirror is about to write, a column it is not."""
    return _Target(
        slug=projected.category.slug, path=projected.path, row=row_of(projected.entries[0]), key=subject.free_text_key
    )


async def _mirror(
    catalog: Catalog | _ASecondWriterInFront, projected: Projected, pending: dict[uuid.UUID, str]
) -> MirrorOutcome:
    return await write_mirror_cells(catalog, projected.category, projected.entries, pending, now=NOW)


# -- losing, and retrying (the workbook half - no database) -------------------------------------------


async def test_the_mirror_loses_to_a_user_edit_made_after_it_read_the_mtime(
    catalog: Catalog, projected: Projected, subject: WorkbookFacts
) -> None:
    """The first attempt is guarded on the stamp the last ingest stored, and the owner moved it.

    The refusal is not arranged: between the mirror deciding what to write and `Catalog._write` opening
    the file, a real `update_row` lands on another cell of the same row, and the production
    `guard_fresh` compares two real stamps and says no.
    """
    entry = projected.entries[0]
    target = _target(projected, subject)
    stamped = projected.category.workbook_mtime
    contested = _ASecondWriterInFront(catalog, _a_cell_edit(target))

    await _mirror(contested, projected, {entry.id: WATCHED})

    assert contested.refused == [StaleWorkbookError.__name__]
    assert contested.forwarded[0] == stamped
    # The user's cell survives: the mirror lost, and losing costs the owner nothing.
    assert projected.cell(entry, target.key) == contested.saved[0]


async def test_the_mirror_retries_on_the_fresh_mtime_and_writes_only_its_own_cell(
    catalog: Catalog, settings: Settings, projected: Projected, subject: WorkbookFacts
) -> None:
    """Having lost, the mirror re-reads and writes against the sheet as the owner left it.

    Both edits end up in the row, in different columns, because a `revise` touches only the cells it
    names - which is what makes losing a race and then retrying safe rather than a second clobber.
    """
    entry = projected.entries[0]
    target = _target(projected, subject)
    before = fingerprint(projected.path)
    contested = _ASecondWriterInFront(catalog, _a_cell_edit(target))

    outcome = await _mirror(contested, projected, {entry.id: WATCHED})

    assert outcome == WRITTEN
    assert contested.attempts == ATTEMPTS_WITH_ONE_RETRY
    # The retry was guarded on the sheet as it now stands, not on the stamp that was just refused.
    assert contested.forwarded[1] != contested.forwarded[0]
    assert projected.cell(entry) == WATCHED
    assert projected.cell(entry, target.key) == contested.saved[0]
    assert entry.mirrored_watch_cell == WATCHED
    assert projected.category.workbook_mtime == projected.path.stat().st_mtime
    assert projected.category.last_mirrored_at == NOW
    # The refused attempt cost nothing at all: `guard_fresh` runs before the snapshot in `_mutate`.
    assert len(restore_points(settings, subject)) == RESTORE_POINTS_FOR_TWO_LANDED_WRITES
    assert fingerprint(projected.path) == before


async def test_the_mirror_gives_up_after_the_retry_budget_and_reports_deferred(
    catalog: Catalog, projected: Projected, subject: WorkbookFacts
) -> None:
    """A library somebody keeps saving over: every attempt meets a stamp that has genuinely moved.

    Three real refusals rather than three arranged ones - the wrapper writes the sheet before each
    forwarded attempt - so the last value the owner typed is still standing at the end, which is the
    proof that the mirror never got in.
    """
    entry = projected.entries[0]
    target = _target(projected, subject)
    stamped = projected.category.workbook_mtime
    before = fingerprint(projected.path)
    contested = _ASecondWriterInFront(catalog, _a_cell_edit(target), saves=MIRROR_RETRY_ATTEMPTS)

    outcome = await _mirror(contested, projected, {entry.id: WATCHED})

    assert outcome == DEFERRED
    assert contested.attempts == MIRROR_RETRY_ATTEMPTS
    assert contested.refused == [StaleWorkbookError.__name__] * MIRROR_RETRY_ATTEMPTS
    # Neither store moved, so the identical diff replays on the next pass.
    assert projected.cell(entry) == UNWATCHED
    assert entry.mirrored_watch_cell == UNWATCHED
    assert projected.category.workbook_mtime == stamped
    assert projected.category.last_mirrored_at is None
    # Every refusal was the owner's own write landing first, and the last of them is still in the sheet.
    assert len(contested.saved) == MIRROR_RETRY_ATTEMPTS
    assert projected.cell(entry, target.key) == contested.saved[-1]
    assert fingerprint(projected.path) == before


@pytest.mark.parametrize(
    ("contest", "outcome", "attempts", "landed"),
    [
        (_a_cell_edit, WRITTEN, ATTEMPTS_WITH_ONE_RETRY, True),
        (lambda target: a_save_that_changed_nothing(target.path), WRITTEN, ATTEMPTS_WITH_ONE_RETRY, True),
        (_a_deleted_row, DEFERRED, ONE_ATTEMPT, False),
    ],
    ids=["a column the plan says nothing about", "a save that changed nothing", "the very row the plan names"],
)
async def test_whether_the_mirror_wins_turns_on_what_the_second_writer_touched(
    catalog: Catalog,
    settings: Settings,
    projected: Projected,
    subject: WorkbookFacts,
    contest: Contest,
    outcome: MirrorOutcome,
    attempts: int,
    landed: bool,
) -> None:
    """`_still_ours` is the whole ordering, and it is a per-row question, not a per-file one.

    A stamp that moved for a reason the plan does not care about is retried onto; the row the plan
    names being taken over - here deleted, which lifts a different entry's identity into that row
    number - stops the retry dead, because a row number means nothing except against the grid it was
    resolved on.
    """
    entry = projected.entries[0]
    contested = _ASecondWriterInFront(catalog, contest(_target(projected, subject)))

    assert await _mirror(contested, projected, {entry.id: WATCHED}) == outcome

    assert contested.attempts == attempts
    assert (WATCHED in projected.statuses()) is landed
    assert (entry.mirrored_watch_cell == WATCHED) is landed
    if not landed:
        # The refused attempt never reached the snapshot, so the only restore point is the owner's own.
        assert len(restore_points(settings, subject)) == ONE_RESTORE_POINT
        # Pinned directly rather than inferred from `attempts`: the row-takeover case stands down after
        # exactly one forwarded write, and that write is refused as stale, not merely uncounted.
        assert contested.refused == [StaleWorkbookError.__name__]


# -- the lock: serialised, not lost ------------------------------------------------------------------


async def test_a_ui_write_waiting_on_the_lock_is_serialised_not_lost(
    catalog: Catalog, projected: Projected, subject: WorkbookFacts
) -> None:
    """`lock_for` means the two writers take turns rather than interleaving.

    The mirror is started while the workbook's lock is held elsewhere and is shown to make no progress
    at all until it is released - it cannot even read. The UI write then takes its `expected_mtime` from
    a read made after the mirror was done, so it is not racing anything and does not 409.
    """
    entry = projected.entries[0]
    slug = projected.category.slug

    async with lock_for(projected.path):
        mirror = asyncio.create_task(_mirror(catalog, projected, {entry.id: WATCHED}))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(mirror), PARKED_SECONDS)

    outcome = await mirror
    detail = await catalog.detail(slug)
    written = await catalog.update_row(
        slug,
        row_of(entry),
        RowWrite(cells={subject.free_text_key: A_UI_EDIT_THAT_RACED_AHEAD}, expected_mtime=detail.mtime),
    )

    assert outcome == WRITTEN
    assert projected.cell(entry) == WATCHED
    assert projected.cell(entry, subject.free_text_key) == A_UI_EDIT_THAT_RACED_AHEAD
    assert written.mtime == projected.path.stat().st_mtime


async def test_a_ui_write_that_raced_ahead_gets_the_standard_409_and_a_fresh_detail(
    client: AsyncClient, catalog: Catalog, projected: Projected, subject: WorkbookFacts
) -> None:
    """The mirror's presence changes nothing about the contract a user's own stale write already has.

    `StaleWorkbookError` -> 409 -> the client re-reads and sees what the other writer put there. Here
    the other writer happens to be the mirror; the refusal, the envelope and the fresh detail are the
    ones `test_api.py` already pins for two users racing each other.
    """
    entry = projected.entries[0]
    slug = projected.category.slug
    stale = (await client.get(f"/api/categories/{slug}")).json()

    assert await _mirror(catalog, projected, {entry.id: WATCHED}) == WRITTEN

    response = await client.patch(
        f"/api/categories/{slug}/rows/{row_of(entry)}",
        json={"cells": {subject.free_text_key: A_UI_EDIT_THAT_RACED_AHEAD}, "expected_mtime": stale["mtime"]},
    )

    assert response.status_code == CONFLICT
    assert response.json()["error"] == StaleWorkbookError.__name__
    fresh = (await client.get(f"/api/categories/{slug}")).json()
    assert fresh["mtime"] != stale["mtime"]
    assert _cell_in(fresh, row_of(entry), subject.watch_key) == WATCHED
    # The refused write left nothing of itself behind, so the re-read is safe to paint over the edit.
    assert _cell_in(fresh, row_of(entry), subject.free_text_key) != A_UI_EDIT_THAT_RACED_AHEAD


def _cell_in(detail: dict[str, object], row: int, key: str) -> str:
    rows = detail["rows"]
    assert isinstance(rows, list)
    return next(str(found["cells"].get(key, "")) for found in rows if found["row"] == row)


# -- the same race through the session-bound seam (a real Postgres, or a loud skip) -------------------


async def _projected_in_postgres(session: AsyncSession, path: Path, subject: WorkbookFacts) -> Projected:
    """The same shape as `projected`, with the rows in the database the derived-status view reads."""
    category_id = uuid.uuid4()
    category = category_row(read_category(path), category_id)
    session.add(category)
    # The category has to exist before the entries that name it, and the entries have to have their
    # ids before those ids can be minted into the sheet - so the stamp is taken last, after the write
    # that minting is, which is exactly the order a first ingest stores it in.
    await session.flush()
    entries = entries_for(category_id, TWO_ROWS, path=path)
    session.add_all(entries)
    await session.flush()
    _minted_into(path, entries)
    category.workbook_mtime = read_category(path).mtime
    return Projected(path, category, entries, subject.watch_key)


@pytest.fixture
async def projected_in_postgres(db_session: AsyncSession, subject_path: Path, subject: WorkbookFacts) -> Projected:
    return await _projected_in_postgres(db_session, subject_path, subject)


async def _watched(session: AsyncSession, entry: CuratedEntry) -> None:
    """One real watch fact, so the view derives `completed` and the mirror genuinely wants to write."""
    session.add(
        WatchEvent(
            occurred_at=NOW,
            subject_kind=WatchSubjectKind.CURATED_ENTRY,
            kind=WatchEventKind.COMPLETED,
            source=WatchEventSource.UI,
            curated_entry_id=entry.id,
            category_id=entry.category_id,
        )
    )
    await session.flush()


async def test_mirror_entry_loses_the_first_attempt_and_retries_onto_the_fresh_stamp(
    db_session: AsyncSession, catalog: Catalog, projected_in_postgres: Projected, subject: WorkbookFacts
) -> None:
    """The whole standalone seam, end to end: the view derives the status and the owner takes the file."""
    projected = projected_in_postgres
    entry = projected.entries[0]
    target = _target(projected, subject)
    await _watched(db_session, entry)
    contested = _ASecondWriterInFront(catalog, _a_cell_edit(target))

    outcome = await mirror_entry(db_session, contested, entry.id, clock=lambda: NOW)

    assert outcome == WRITTEN
    assert contested.refused == [StaleWorkbookError.__name__]
    assert contested.attempts == ATTEMPTS_WITH_ONE_RETRY
    assert projected.cell(entry) == WATCHED
    assert projected.cell(entry, target.key) == contested.saved[0]
    assert entry.mirrored_watch_cell == WATCHED


async def test_mirror_entry_gives_up_after_the_retry_budget_and_moves_neither_store(
    db_session: AsyncSession, catalog: Catalog, projected_in_postgres: Projected, subject: WorkbookFacts
) -> None:
    """A deferral is not a failure: both stores are left exactly as they were, owing the same diff."""
    projected = projected_in_postgres
    entry = projected.entries[0]
    target = _target(projected, subject)
    stamped = projected.category.workbook_mtime
    await _watched(db_session, entry)
    contested = _ASecondWriterInFront(catalog, _a_cell_edit(target), saves=MIRROR_RETRY_ATTEMPTS)

    outcome = await mirror_entry(db_session, contested, entry.id, clock=lambda: NOW)

    assert outcome == DEFERRED
    assert contested.attempts == MIRROR_RETRY_ATTEMPTS
    assert projected.cell(entry) == UNWATCHED
    assert entry.mirrored_watch_cell == UNWATCHED
    assert projected.category.workbook_mtime == stamped
    assert projected.category.last_mirrored_at is None
    assert projected.cell(entry, target.key) == contested.saved[-1]


# -- the same race on the reconciler's own write-back (a real Postgres, or a loud skip) ---------------


def _reconciler(session: AsyncSession, catalog: Catalog | _ASecondWriterInFront) -> Reconciler:
    """Providers absent: a missing token is a disabled feature, and this file is about the write."""
    return Reconciler(session, catalog, resolver=None, tmdb_ingest=None, order_ingest=None)


async def _entries_of(session: AsyncSession, slug: str) -> list[CuratedEntry]:
    rows = await session.scalars(
        select(CuratedEntry)
        .join(Category, Category.id == CuratedEntry.category_id)
        .where(Category.slug == slug)
        .order_by(CuratedEntry.position)
    )
    return list(rows)


async def _category_of(session: AsyncSession, slug: str) -> Category:
    found = await session.scalar(select(Category).where(Category.slug == slug))
    assert found is not None
    return found


async def _an_ingested_category_owing_one_mirror_cell(
    session: AsyncSession, catalog: Catalog, subject: WorkbookFacts
) -> None:
    """One full pass, one committed watch fact, and one hand edit - so the next pass has work to do.

    The edit matters as much as the event: an unchanged workbook is skipped on its digest before the
    write-back is ever reached, so without it the second pass never opens the file at all.
    """
    await _reconciler(session, catalog).reconcile(subject.category_id)
    await _watched(session, (await _entries_of(session, subject.category_id))[0])
    await session.commit()
    detail = await catalog.detail(subject.category_id)
    await catalog.update_row(
        subject.category_id,
        FIRST_DATA_ROW + 1,
        RowWrite(cells={subject.free_text_key: A_HAND_EDIT.format(save=0)}, expected_mtime=detail.mtime),
    )


async def test_a_save_between_the_reconcilers_read_and_its_write_back_is_retried_onto(
    db_session: AsyncSession, catalog: Catalog, subject: WorkbookFacts, subject_path: Path
) -> None:
    """Excel re-saving the file mid-pass moved the stamp but not the grid, so `_retried` re-reads and writes."""
    await _an_ingested_category_owing_one_mirror_cell(db_session, catalog, subject)
    contested = _ASecondWriterInFront(catalog, a_save_that_changed_nothing(subject_path))

    outcome = await _reconciler(db_session, contested).reconcile(subject.category_id)

    assert outcome.workbook_written is True
    assert contested.refused == [StaleWorkbookError.__name__]
    assert contested.attempts == ATTEMPTS_WITH_ONE_RETRY
    entries = await _entries_of(db_session, subject.category_id)
    assert entries[0].mirrored_watch_cell == WATCHED
    assert read_category(subject_path).rows[0].cells[subject.watch_key] == WATCHED


async def test_a_ui_edit_between_the_reconcilers_read_and_its_write_back_costs_the_pass_not_the_cell(
    db_session: AsyncSession, catalog: Catalog, subject: WorkbookFacts, subject_path: Path
) -> None:
    """The plan was computed against a sheet that no longer exists, so the whole pass stands down.

    `_retried` re-reads and finds the grid digest changed: this is the mirror losing on the ingest path,
    which is a rollback rather than a `deferred`, because the pass had already reasoned about rows the
    owner has since rewritten. Neither store moves, the owner's cell is untouched, and the identical
    diff replays - proved here by running the next pass and watching it land.
    """
    await _an_ingested_category_owing_one_mirror_cell(db_session, catalog, subject)
    stamped = (await _category_of(db_session, subject.category_id)).workbook_mtime
    target = _Target(subject.category_id, subject_path, FIRST_DATA_ROW, subject.free_text_key)
    contested = _ASecondWriterInFront(catalog, _a_cell_edit(target))

    with pytest.raises(StaleWorkbookError):
        await _reconciler(db_session, contested).reconcile(subject.category_id)

    await db_session.rollback()
    assert contested.attempts == ONE_ATTEMPT
    entries = await _entries_of(db_session, subject.category_id)
    assert entries[0].mirrored_watch_cell == UNWATCHED
    assert (await _category_of(db_session, subject.category_id)).workbook_mtime == stamped
    row = read_category(subject_path).rows[0].cells
    assert row[subject.watch_key] == UNWATCHED
    assert row[subject.free_text_key] == contested.saved[0]

    replayed = await _reconciler(db_session, catalog).reconcile(subject.category_id)

    assert replayed.workbook_written is True
    assert (await _entries_of(db_session, subject.category_id))[0].mirrored_watch_cell == WATCHED
    assert read_category(subject_path).rows[0].cells[subject.free_text_key] == contested.saved[0]
