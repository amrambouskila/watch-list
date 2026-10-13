"""The first ingest: every workbook in the library, one at a time, and the record of what it did.

This is the run the owner makes once by hand after the providers are configured, and the run that gives
996 rows an identity they keep forever. Three properties make it safe to point at nineteen irreplaceable
files:

* **One workbook at a time.** No fan-out, no gather. Each pass takes that workbook's own `lock_for`
  (inside `Catalog`, where the read and the write both already take it) and its own session, so a
  failure anywhere touches one file and one transaction (master plan section 9.3: a bounded ingest).
* **A refusal is a result.** Excel holding a file, a sheet that changed mid-pass, a workbook that will
  not open, an `--only` slug nothing answers to: each is recorded on that workbook's outcome and the
  run carries on. The exit code is what carries them to the shell.
* **`--dry-run` writes to neither store.** The write-back is answered by a catalog that declines to
  write, and the session is a savepoint inside a transaction this module always rolls back, so a
  planning run reports the same counts a real one would and leaves nothing behind.

One structured record per workbook and one per run, zeros included: a pass that changed nothing has to
say so, because no output is indistinguishable from not having run (CLAUDE.md section 9.2). The free
text of a refusal is always the last field of its record, so a reason carrying spaces can never be read
as another key.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Final

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tv_watchlist.config import get_settings
from tv_watchlist.constants import (
    BOOTSTRAP_EXIT_FAILED,
    BOOTSTRAP_EXIT_OK,
    BOOTSTRAP_EXIT_REFUSED,
    BOOTSTRAP_JOB,
)
from tv_watchlist.data.session import build_engine, build_session_factory
from tv_watchlist.ingest.reconcile_outcome import ReconcileOutcome
from tv_watchlist.ingest.runtime import IngestRuntime
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook import discovery
from tv_watchlist.workbook.errors import WorkbookError
from tv_watchlist.workbook.naming import category_id

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

#: How this module opens the one session a single workbook's pass runs in. `async_sessionmaker`
#: satisfies it as-is; `--dry-run` substitutes one whose transaction is always rolled back.
type SessionOpener = Callable[[], AbstractAsyncContextManager[AsyncSession]]

# The `refused=` token of a per-workbook record: a closed vocabulary, exactly as `reconciler.py` keeps
# one, so a log reader never has to tell a reason from a boolean. The reason itself rides in `reason=`.
_NOT_REFUSED: Final[str] = "none"
_REFUSED: Final[str] = "refused"
_NO_REASON: Final[str] = "-"
_REFUSAL_REASON: Final[str] = "{error}: {detail}"

_START_RECORD: Final[str] = "bootstrap_start job=%s dry_run=%s workbooks=%d"
_WORKBOOK_RECORD: Final[str] = (
    "bootstrap_workbook job=%s category=%s dry_run=%s skipped=%s matched=%d adopted=%d minted=%d"
    " reminted=%d removed=%d reresolved=%d refreshed=%d written=%s refused=%s elapsed_ms=%d reason=%s"
)
_END_RECORD: Final[str] = (
    "bootstrap_end job=%s dry_run=%s workbooks=%d ingested=%d skipped=%d refused=%d rows=%d minted=%d"
    " written=%d elapsed_ms=%d"
)
# The run itself broke, so there is no `bootstrap_end` to carry it. The exception's class is the whole
# payload: see the comment in `main`.
_FAILED: Final[str] = "failed"
_FAILED_RECORD: Final[str] = "bootstrap_failed job=%s dry_run=%s outcome=%s error=%s"
_FAILED_NOTICE: Final[str] = "bootstrap did not finish: {error}. No workbook was reported; see the log above."
# A refusal reason is free text that reached us from a filename, an Excel cell or a provider, so a
# newline in it would forge a second log record out of one (CLAUDE.md section 10.3, header/log injection).
_LINE_BREAKS: Final[tuple[str, ...]] = ("\r\n", "\r", "\n")
_LINE_BREAK_REPLACEMENT: Final[str] = " "

_HEADLINE: Final[str] = "bootstrap"
_DRY_RUN_HEADLINE: Final[str] = "bootstrap (dry run - nothing was written to either store)"
_SUMMARY_HEADLINE: Final[str] = (
    "{headline}: {workbooks} workbooks, {ingested} ingested, {skipped} skipped, {refused} refused"
)
_SUMMARY_TOTALS: Final[str] = "{rows} rows projected, {minted} identities minted, {written} workbooks written"
_REFUSAL_LINE: Final[str] = "  refused: {slug} - {reason}"

_PROGRAM: Final[str] = "python -m tv_watchlist.ingest.bootstrap"
_DESCRIPTION: Final[str] = (
    "Project every workbook in the library into Postgres, one at a time, minting the hidden Row ID "
    "column each sheet needs and taking one backup snapshot per workbook written."
)
_ONLY_HELP: Final[str] = "run only these category ids; a slug no workbook answers to is refused, not skipped"
_DRY_RUN_HELP: Final[str] = (
    "plan the run and report the counts a real one would, without writing to either store: no workbook "
    "is opened for writing, no backup snapshot is taken, no mtime moves, and the database work is done "
    "for real inside a transaction that is always rolled back. It is not free, and it is not offline. "
    "It still reads every workbook under that workbook's own lock, so a pass blocks the app's writes to "
    "that file for as long as it lasts; it still needs a reachable database, and holds that connection's "
    "row locks until the rollback; and with provider tokens configured it still spends TMDB and TheTVDB "
    "quota and still downloads artwork to the heroes directory, which is an on-disk cache and neither of "
    "the two stores. Run it with the tokens unset for a preview that reaches no network."
)
_LOG_FORMAT: Final[str] = "%(asctime)s %(levelname)s %(name)s %(message)s"


@dataclass(frozen=True, slots=True)
class BootstrapArguments:
    """What the command line asked for, read off `argparse` once so nothing downstream sees a Namespace."""

    slugs: tuple[str, ...] | None
    dry_run: bool


@dataclass(frozen=True, slots=True)
class BootstrapTotals:
    """A whole run's arithmetic, computed once and read by both the summary line and the end record."""

    workbooks: int
    ingested: int
    skipped: int
    refused: int
    #: Every row the run accounted for, however it accounted for it: matched, adopted or newly minted.
    rows: int
    minted: int
    written: int

    @classmethod
    def of(cls, outcomes: Sequence[ReconcileOutcome]) -> BootstrapTotals:
        refused = [outcome for outcome in outcomes if outcome.refused is not None]
        skipped = [outcome for outcome in outcomes if outcome.refused is None and outcome.skipped]
        return cls(
            workbooks=len(outcomes),
            ingested=len(outcomes) - len(refused) - len(skipped),
            skipped=len(skipped),
            refused=len(refused),
            rows=sum(outcome.matched + outcome.adopted + outcome.minted for outcome in outcomes),
            minted=sum(outcome.minted for outcome in outcomes),
            written=sum(1 for outcome in outcomes if outcome.workbook_written),
        )


def library_slugs(library_dir: Path) -> list[str]:
    """Every id the library answers to, in the order `discovery.resolve` would answer them.

    Derived from the filenames rather than from `Catalog.listing()`, because a workbook that will not
    open still claims its id: dropping it here would make the run silently eighteen workbooks long
    instead of nineteen with one refusal on the record. A namesake that slugifies onto an id another
    file already answers to is unreachable, so it is run once, not twice (CLAUDE.md section 5.5).
    """
    return list(dict.fromkeys(category_id(path) for path in discovery.workbook_paths(library_dir)))


async def bootstrap(
    runtime: IngestRuntime, *, slugs: Sequence[str] | None = None, dry_run: bool = False
) -> list[ReconcileOutcome]:
    """Reconcile the whole library, one workbook at a time, and hand back what each pass did."""
    wanted = list(slugs) if slugs is not None else library_slugs(runtime.catalog.library_dir)
    started = time.monotonic()
    _LOGGER.info(_START_RECORD, BOOTSTRAP_JOB, dry_run, len(wanted))
    outcomes: list[ReconcileOutcome] = []
    if wanted:
        passing = _planning(runtime) if dry_run else runtime
        open_session = await _session_opener(passing, dry_run=dry_run)
        for slug in wanted:
            outcomes.append(await _one_workbook(passing, open_session, slug, dry_run=dry_run))
    _log_run(outcomes, started, dry_run=dry_run)
    return outcomes


def summarise(outcomes: Sequence[ReconcileOutcome], *, dry_run: bool) -> str:
    """The block the owner reads when the run ends, refusals named one per line underneath it."""
    totals = BootstrapTotals.of(outcomes)
    lines = [
        _SUMMARY_HEADLINE.format(
            headline=_DRY_RUN_HEADLINE if dry_run else _HEADLINE,
            workbooks=totals.workbooks,
            ingested=totals.ingested,
            skipped=totals.skipped,
            refused=totals.refused,
        ),
        _SUMMARY_TOTALS.format(rows=totals.rows, minted=totals.minted, written=totals.written),
    ]
    lines.extend(
        _REFUSAL_LINE.format(slug=outcome.slug, reason=outcome.refused)
        for outcome in outcomes
        if outcome.refused is not None
    )
    return "\n".join(lines)


def exit_code(outcomes: Sequence[ReconcileOutcome]) -> int:
    """Zero when every workbook was reconciled or deliberately skipped; one when any was refused."""
    return BOOTSTRAP_EXIT_REFUSED if any(outcome.refused is not None for outcome in outcomes) else BOOTSTRAP_EXIT_OK


def parse_arguments(argv: Sequence[str] | None) -> BootstrapArguments:
    """The command line, read into a shape with no `Namespace` and no untyped attribute on it."""
    parser = argparse.ArgumentParser(prog=_PROGRAM, description=_DESCRIPTION)
    parser.add_argument("--only", nargs="+", metavar="SLUG", default=None, help=_ONLY_HELP)
    parser.add_argument("--dry-run", action="store_true", help=_DRY_RUN_HELP)
    parsed = parser.parse_args(argv)
    only: list[str] | None = parsed.only
    return BootstrapArguments(slugs=None if only is None else tuple(only), dry_run=bool(parsed.dry_run))


def main(argv: Sequence[str] | None = None) -> int:
    """The runnable: zero when nothing was refused, one when something was, two when the run itself broke.

    The three codes are three different things to do about them, which is the whole reason the last one
    exists. A refusal is a workbook declining to be written and the next pass replays it; a failure is an
    unreachable database, a schema behind head, a credential the provider rejected - the run produced no
    outcomes at all, and a shell that read that as "nothing was refused" would report success for a pass
    that never happened. `Exception` only: a Ctrl-C is a `BaseException` and still ends the process.
    """
    arguments = parse_arguments(argv)
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    try:
        outcomes = asyncio.run(_run(arguments))
    except Exception as failure:
        # The exception's class and nothing else. A connection or provider error carries the thing it
        # failed to reach, and that string is where a DSN - password and all - or an Authorization
        # header would surface, in a log line and on the owner's terminal (CLAUDE.md section 10.4).
        _LOGGER.error(_FAILED_RECORD, BOOTSTRAP_JOB, arguments.dry_run, _FAILED, type(failure).__name__)
        print(_FAILED_NOTICE.format(error=type(failure).__name__))
        return BOOTSTRAP_EXIT_FAILED
    print(summarise(outcomes, dry_run=arguments.dry_run))
    return exit_code(outcomes)


# -- one workbook, one session ----------------------------------------------------------------------


async def _one_workbook(
    runtime: IngestRuntime, open_session: SessionOpener, slug: str, *, dry_run: bool
) -> ReconcileOutcome:
    """One pass, in its own session, with every refusal the workbook layer can raise caught here.

    `reconcile` converts the two refusals it owns into an outcome itself and re-raises the ones the
    *workbook* declined - locked, stale - after rolling back. A workbook that will not open, or an id
    nothing answers to, never reaches that try at all: `Catalog.projection` raises before it. All of
    them end here, because one bad file may not end a nineteen-workbook run.
    """
    started = time.monotonic()
    async with open_session() as session:
        try:
            outcome = await runtime.reconciler(session).reconcile(slug)
        except WorkbookError as refusal:
            outcome = ReconcileOutcome(
                slug=slug, refused=_REFUSAL_REASON.format(error=type(refusal).__name__, detail=refusal)
            )
    if dry_run:
        # `workbook_written` is past tense. The planning catalog answered the write, so the pass counted
        # one; nothing reached the file, and a report that said otherwise would be the one lie a dry run
        # cannot afford.
        outcome = replace(outcome, workbook_written=False)
    _log_workbook(outcome, started, dry_run=dry_run)
    return outcome


def _planning(runtime: IngestRuntime) -> IngestRuntime:
    """The same runtime, its catalog swapped for one that declines to write. Both pools are shared."""
    return replace(runtime, catalog=_PlanningCatalog(runtime.settings))


class _PlanningCatalog(Catalog):
    """Reads like the real catalog and declines to write, so a dry run cannot touch a workbook.

    The reconciler reaches the sheet through exactly one method, so overriding that one is how
    `--dry-run` skips the write-back: no second write path, and nothing in `reconciler.py` changed
    (CLAUDE.md section 3.4). It answers with the sheet as it stands rather than raising, because the
    pass has to run to the end - a dry run that stopped at the write would report half the counts a
    real one does.
    """

    async def apply_ingest_writeback(
        self,
        wanted_id: str,
        ids_by_row: Mapping[int, str],
        cells_by_row: Mapping[int, Mapping[str, str]],
        expected_mtime: float,
    ) -> CategoryDetail:
        return await self.detail(wanted_id)


async def _session_opener(runtime: IngestRuntime, *, dry_run: bool) -> SessionOpener:
    """The factory a real run uses, or the rolled-back one a dry run needs."""
    if not dry_run:
        return runtime.session_factory
    return partial(_rolled_back_session, await _engine_behind(runtime.session_factory))


async def _engine_behind(open_session: SessionOpener) -> AsyncEngine:
    """The engine a factory's sessions are bound to, asked for through a session's own connection.

    Through the session rather than off the factory's internals, so anything shaped like a session
    opener answers - which is what lets the suite hand in one joined to the test's own transaction.
    """
    # One probe session, opened and closed for its engine alone, deliberately: `async_sessionmaker.kw`
    # would answer without it but only for a real sessionmaker, and this runs once per dry run.
    async with open_session() as session:
        return (await session.connection()).engine


@asynccontextmanager
async def _rolled_back_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session that may commit and still leaves nothing behind.

    The reconciler commits - it is the only thing in the project that does - and a dry run may not.
    Binding the session to a connection whose transaction this function owns turns each of those
    commits into a released SAVEPOINT, and the one transaction that matters is rolled back here.

    This is the `db_session` fixture's recipe (`tests/conftest.py`), in production code: same external
    connection, same `join_transaction_mode="create_savepoint"`, same always-rolled-back outer
    transaction. They are one mechanism and they change together - if that fixture's shape ever moves,
    this moves with it, because a dry run that leaked rows would be the failure it exists to prevent.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection, expire_on_commit=False, autoflush=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


async def _run(arguments: BootstrapArguments) -> list[ReconcileOutcome]:
    """One process, one engine, one runtime: both provider pools and the engine close with the run.

    Deliberately not the API's `lru_cache` singletons: this is a command, not the app, and a CLI that
    left an engine open would hold a connection for as long as the shell did.
    """
    settings = get_settings()
    engine = build_engine(settings.database_url)
    runtime = IngestRuntime.from_settings(settings, Catalog(settings), build_session_factory(engine))
    try:
        return await bootstrap(runtime, slugs=arguments.slugs, dry_run=arguments.dry_run)
    finally:
        await runtime.aclose()
        await engine.dispose()


# -- the records ------------------------------------------------------------------------------------


def _log_workbook(outcome: ReconcileOutcome, started: float, *, dry_run: bool) -> None:
    _LOGGER.info(
        _WORKBOOK_RECORD,
        BOOTSTRAP_JOB,
        outcome.slug,
        dry_run,
        outcome.skipped,
        outcome.matched,
        outcome.adopted,
        outcome.minted,
        outcome.reminted,
        outcome.removed,
        outcome.reresolved,
        outcome.refreshed,
        outcome.workbook_written,
        _REFUSED if outcome.refused is not None else _NOT_REFUSED,
        _elapsed_ms(started),
        _one_line(outcome.refused) if outcome.refused is not None else _NO_REASON,
    )


def _one_line(reason: str) -> str:
    """A refusal reason flattened onto the single line its record occupies."""
    for line_break in _LINE_BREAKS:
        reason = reason.replace(line_break, _LINE_BREAK_REPLACEMENT)
    return reason


def _log_run(outcomes: Sequence[ReconcileOutcome], started: float, *, dry_run: bool) -> None:
    totals = BootstrapTotals.of(outcomes)
    _LOGGER.info(
        _END_RECORD,
        BOOTSTRAP_JOB,
        dry_run,
        totals.workbooks,
        totals.ingested,
        totals.skipped,
        totals.refused,
        totals.rows,
        totals.minted,
        totals.written,
        _elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
