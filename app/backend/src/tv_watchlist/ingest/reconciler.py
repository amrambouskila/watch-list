"""Excel into Postgres: the pass that keeps the projection honest about the workbook.

The algorithm is master plan section 6.5 verbatim. The shape of it, and why each step is where it is:

- **Skip on digest; the stamp is recorded.** Excel rewrites a file whenever it closes one, so `st_mtime`
  alone would re-ingest nineteen workbooks after a look - and ANDing the stamp in would make the digest
  dead weight, because an equal stamp already implies equal bytes. A skip still records the moved stamp,
  so the next pass and the write-back guards agree with the file. The Row ID column sits outside that
  digest by design, so the identities are the half of the change test compared separately
  (section 6.5, rule 1; Ruling 49).
- **Identity is the UUID in the sheet, never the row number.** A reorder is a new `position` on existing
  rows, and `uq(category_id, position)` is deferrable so the whole category renumbers inside the
  transaction without tripping over itself (rule 4, ADR-007).
- **Adoption before minting.** A user who cleared the Row ID column has not thrown their watch history
  away; a row that still matches on title, unit and roughly where it sat gets its own UUID back (rule 3).
- **Refuse rather than misattribute.** A Row ID cell holding something that is not a canonical UUID, and a
  previously-ingested sheet whose rows have mostly stopped matching, both mean a human did something
  structural. Neither is re-keyed: the pass rolls back, `category.last_ingest_error` says why, and the
  workbook is not touched (section 6.3).
- **Nothing is deleted.** A row that left the sheet is `removed_at`, and `watch_event.curated_entry_id` is
  `ON DELETE RESTRICT` so the database would refuse anything else (rule 7).
- **One write-back.** Every minted identity and every mirror cell of the pass go through a single
  `Catalog._write`: one snapshot, one temp file, one `os.replace`, one new mtime - which is the mtime that
  gets stored, so the next pass does not read our own write as a change (rule 6, CLAUDE.md section 3.4).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clock import utcnow
from tv_watchlist.constants import ADOPTION_POSITION_WINDOW, MISMATCH_REFUSAL_RATIO
from tv_watchlist.data.enums import ExternalSource, MediaType, ResolutionState, SyncResourceType, UnitKind
from tv_watchlist.data.models import Category, CuratedEntry, Title
from tv_watchlist.ingest.errors import IngestRefusedError
from tv_watchlist.ingest.expansion import rebuild_items
from tv_watchlist.ingest.ingest_outcome import IngestOutcome
from tv_watchlist.ingest.reconcile_outcome import ReconcileOutcome
from tv_watchlist.ingest.sync_cursor import PostgresResponseCache

# `_fitted` / `_required` are T19's clip-to-the-declared-width helpers, imported rather than reimplemented:
# a second clip would be a second place for `String(255)` to be remembered wrongly (CLAUDE.md section 7).
from tv_watchlist.ingest.tmdb_ingest import TmdbIngest, _fitted, _required
from tv_watchlist.ingest.workbook_digest import digest_grid
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.models.watch_row import WatchRow
from tv_watchlist.resolver.match_key import match_key, release_year
from tv_watchlist.resolver.resolution_request import ResolutionRequest
from tv_watchlist.resolver.span import SpanParse, parse_unit
from tv_watchlist.resolver.title_resolution import TitleResolution, TitleResolver
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.watch_mirror import (
    entry_watch_states,
    human_edit_events,
    pending_mirror_cells,
    record_mirrored,
    writable_mirror_cells,
)
from tv_watchlist.workbook.curated_columns import CuratedColumns, curated_columns, raw_type_cell
from tv_watchlist.workbook.errors import StaleWorkbookError, WorkbookError, WorkbookLockedError
from tv_watchlist.workbook.reader import WorkbookProjection
from tv_watchlist.workbook.schema import watch_column

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_JOB: Final[str] = "reconcile"
_SOURCE: Final[str] = ExternalSource.TMDB.value

MALFORMED_IDENTITY_TEMPLATE: Final[str] = (
    "rows {rows} carry a Row ID that is not a UUID; the column was edited by hand, so nothing was ingested"
)
NEAR_TOTAL_MISMATCH_TEMPLATE: Final[str] = (
    "{unmatched} of {total} rows match no entry this category already holds; the sheet looks replaced "
    "rather than edited, so nothing was ingested"
)
NOT_CONFIGURED_NOTE: Final[str] = "TMDB not configured"
NO_TITLE_NOTE_TEMPLATE: Final[str] = "TMDB {media_type} {tmdb_id} could not be read into a title row"

_RESOURCE_FOR_MEDIA: Final[dict[MediaType, SyncResourceType]] = {
    MediaType.MOVIE: SyncResourceType.TMDB_MOVIE,
    MediaType.TV: SyncResourceType.TMDB_TV,
}
_PROVIDER_MOVIE: Final[str] = "movie"

# The `refused=` token of a `reconcile_end` record: one closed vocabulary, so a log reader never has to
# tell a reason from a boolean.
_NOT_REFUSED: Final[str] = "none"
_REFUSED: Final[str] = "refused"
_LOCKED: Final[str] = "locked"
_STALE: Final[str] = "stale"
_WORKBOOK_REFUSED: Final[str] = "workbook"
_REFUSAL_LABELS: Final[dict[type[WorkbookError], str]] = {
    WorkbookLockedError: _LOCKED,
    StaleWorkbookError: _STALE,
}


#: T24's `expansion.rebuild_items` as this module calls it: one category, every live entry. Injectable
#: so a test may watch the seam; never so a test may stand something in for the database behind it.
type ItemRebuild = Callable[[AsyncSession, uuid.UUID], Awaitable[int]]


class OrderIngest(Protocol):
    """T20's `EpisodeOrderIngest`, as this module uses it.

    Structural rather than imported, so the reconciler depends on the two calls it makes rather than on a
    class: the collaborator is optional - TheTVDB unconfigured is a disabled feature, not a failure - and
    it is reached only for a series whose title row was actually written. `ingest_tvdb_orders` answers a
    result per ordering the service offers today, because that list is read at runtime and is not closed.
    """

    async def rank_aired(self, title: Title) -> IngestOutcome: ...

    async def ingest_tvdb_orders(self, title: Title) -> dict[str, IngestOutcome]: ...


# ---------------------------------------------------------------------------------------------------
# Pure decisions. Everything down to the class is a function of its arguments and needs no database.
# ---------------------------------------------------------------------------------------------------


def parsed_identity(text: str) -> uuid.UUID | None:
    """A Row ID cell as a UUID, or `None` when it is blank or is not the canonical 36-character form.

    Strict on purpose (Ruling 20): `uuid.UUID` accepts braces, URNs and bare hex, and a cell in any of
    those shapes was typed by a human rather than written by this app. Round-tripping the parse is what
    tells the two apart.
    """
    stripped = text.strip()
    if not stripped:
        return None
    try:
        parsed = uuid.UUID(stripped)
    except ValueError:
        return None
    return parsed if str(parsed) == stripped.lower() else None


def malformed_identity_rows(rows: Sequence[WatchRow], row_ids: Mapping[int, str]) -> list[int]:
    """Sheet rows whose Row ID cell is neither blank nor a canonical UUID.

    Any of these refuses the whole workbook. Minting over such a cell would destroy whatever the owner
    put there, and treating it as blank would adopt or mint against a row that is already claiming an
    identity of its own (Ruling 20).
    """
    return [
        row.row
        for row in rows
        if row_ids.get(row.row, "").strip() and parsed_identity(row_ids.get(row.row, "")) is None
    ]


def adoption_match(
    candidates: Sequence[CuratedEntry],
    *,
    position: int,
    match_key: str | None,
    raw_unit: str,
    window: int = ADOPTION_POSITION_WINDOW,
) -> CuratedEntry | None:
    """The one entry a row with no identity may take back, or `None` when the answer is not obvious.

    Three agreements are demanded at once - the same normalised title, the same `Unit` cell verbatim, and
    a position within `window` - and the match has to be unique. A season-per-row workbook names the same
    show a dozen times over, so title alone would attach watch history to the wrong season; `Unit` is what
    separates them, and the window is what stops a row adopting an entry from the other end of the sheet.
    """
    found = [
        entry
        for entry in candidates
        if entry.match_key == match_key and entry.raw_unit == raw_unit and abs(entry.position - position) <= window
    ]
    return found[0] if len(found) == 1 else None


def is_near_total_mismatch(total: int, unmatched: int, *, previously_ingested: bool) -> bool:
    """Whether this looks like a replaced file rather than an edited one.

    Only ever true for a workbook that has been ingested before: a first pass matches nothing by
    definition, and refusing that would refuse the bootstrap. A sort over a range that excluded the last
    column detaches every id at once, and that is exactly what this catches (master plan section 6.3).
    """
    if not previously_ingested or total == 0:
        return False
    return unmatched / total >= MISMATCH_REFUSAL_RATIO


def needs_resolution(state: ResolutionState, *, is_new: bool, raws_changed: bool) -> bool:
    """Whether this entry is worth spending a TMDB search on this pass.

    Exactly master plan section 6.5's loop: new, raw-changed, or still unresolved. A `confirmed` entry
    whose cells did not move is never re-resolved - a human decision is not overwritten by a heuristic
    (rule 5) - and a `rejected` one is left alone for the same reason.

    The six-month caching ceiling is deliberately NOT a reason to search again. What that clause caps is
    the cached provider payload, not the match; a row whose cells have not moved means the same work it
    meant yesterday. Refreshing the payload is `_refreshed`, which spends no search and cannot lose a
    title to a provider that happens to be down this evening.
    """
    if state is ResolutionState.CONFIRMED and not raws_changed:
        return False
    return is_new or raws_changed or state is ResolutionState.UNRESOLVED


def span_values(
    span: SpanParse, *, season_number: int | None = None, episode_number: int | None = None
) -> tuple[str | None, int | None, int | None, int | None]:
    """`(order_type, span_start, span_end, season_number)` for one entry.

    The bounds are read through `SpanParse.episode_span` / `season_span` rather than off `span_start`
    (Ruling 29), so a parse that named a kind without bounds cannot leak half a span. `order_type` is
    passed through exactly as the parse left it, `None` included: an episode range whose numbering is
    unknown stays unknown, and is never quietly read as aired order (Ruling 30).
    """
    if episode_number is not None:
        # A second-pass match found this row inside a series, by name. Its own season and episode are
        # what the row means; the unit cell never named them.
        return span.order_type, episode_number, episode_number, season_number
    if season_number is not None:
        return span.order_type, None, None, season_number
    bounds = span.episode_span if span.unit_kind is UnitKind.EPISODES else span.season_span
    start, end = bounds if bounds is not None else (None, None)
    return span.order_type, start, end, span.season_number


def renumbered(live: Sequence[uuid.UUID], retired: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Dense 1-based positions: the sheet's own order first, then everything soft-deleted behind it.

    `uq(category_id, position)` has no partial predicate, so a retired entry still occupies its position
    and would collide with the live row renumbering onto it. Parking them after the live block keeps the
    constraint satisfiable and costs nothing: `position` means nothing for a row that left the sheet.
    """
    positions = {entry_id: index for index, entry_id in enumerate(live, start=1)}
    positions.update({entry_id: index for index, entry_id in enumerate(retired, start=len(live) + 1)})
    return positions


def _unchanged(category: Category, digest: str) -> bool:
    """The change test is the digest alone: identical bytes are identical whatever the stamp says.

    ANDing the stamp in would make the digest dead weight - an equal stamp already implies equal bytes,
    and Excel moves the stamp every time it closes a file it changed nothing in (Ruling 49).
    """
    return category.workbook_digest is not None and category.workbook_digest == digest


def identities_intact(entries: Sequence[CuratedEntry], row_ids: Mapping[int, str]) -> bool:
    """The sheet's identity cells are exactly the ones this category's live rows were given.

    The digest leaves the Row ID column out deliberately - that exclusion is what lets a first ingest
    write 996 identities into nineteen sheets and still have the next pass see nineteen unchanged files
    (`workbook_digest`). So a cleared column, a blanked cell, a hand-typed one or a duplicated id moves
    no digest at all, and a skip decided on the digest alone would mean adoption, refusal and re-minting
    never ran again. This is the half of the change test the digest cannot see.
    """
    return dict(row_ids) == {
        entry.sheet_row: str(entry.id) for entry in entries if entry.removed_at is None and entry.sheet_row is not None
    }


@dataclass(slots=True)
class _RowPlan:
    """One sheet row and the entry it turned out to be, carried between the pass's steps."""

    row: WatchRow
    position: int
    entry: CuratedEntry
    is_new: bool
    raws_changed: bool
    # The identity this row's cell has to be made to say, or `None` when it already says it.
    identity_to_write: str | None


class Reconciler:
    """One category's workbook projected into Postgres, over one session's transaction.

    The session is the caller's. This class is the only thing in the project that commits it: an ingest
    that wrote half a category and then recorded the workbook's stamp would make the rest of that sheet
    invisible until a human touched the file again.
    """

    def __init__(
        self,
        session: AsyncSession,
        catalog: Catalog,
        *,
        resolver: TitleResolver | None,
        tmdb_ingest: TmdbIngest | None,
        order_ingest: OrderIngest | None,
        expand: ItemRebuild = rebuild_items,
        clock: Callable[[], datetime] = utcnow,
        adoption_window: int = ADOPTION_POSITION_WINDOW,
    ) -> None:
        self._session = session
        self._catalog = catalog
        self._resolver = resolver
        self._tmdb = tmdb_ingest
        self._orders = order_ingest
        self._expand = expand
        self._clock = clock
        self._window = adoption_window
        # The same cursor table the provider clients write through, read here so the backoff a failure
        # recorded actually stops the next pass spending a search on it (CLAUDE.md section 9.2).
        self._cursors = PostgresResponseCache(session, clock=clock)

    async def reconcile(self, category_slug: str) -> ReconcileOutcome:
        """Bring one category's projection level with its workbook, and say what that took."""
        started = time.monotonic()
        _LOGGER.info("reconcile_start job=%s category=%s", _JOB, category_slug)
        projection = await self._catalog.projection(category_slug)
        try:
            outcome = await self._reconciled(category_slug, projection)
        except IngestRefusedError as refusal:
            outcome = await self._refusal_recorded(category_slug, projection, str(refusal))
        except WorkbookError as refusal:
            # Excel holds the file, or the owner saved over it mid-pass. The pass is abandoned whole so
            # the next one replays the identical diff rather than half of it (master plan section 6.5),
            # and it says so before it goes: a `reconcile_start` with no `reconcile_end` after it reads
            # as a crash rather than as the workbook declining to be written.
            await self._session.rollback()
            self._logged(ReconcileOutcome(slug=category_slug), started, refused=_refusal_label(refusal))
            raise
        return self._logged(outcome, started)

    # -- the pass -----------------------------------------------------------------------------------

    async def _reconciled(self, slug: str, projection: WorkbookProjection) -> ReconcileOutcome:
        detail = projection.detail
        digest = digest_grid(detail.columns, detail.rows)
        category = await self._category(slug)
        if category is not None and _unchanged(category, digest):
            # `_unchanged` answers for the owner's own grid, and only for that: the Row ID column is
            # outside the digest on purpose, so the identities are compared here or a cleared column
            # would skip for good. One SELECT, on the cheapest path the pass has.
            if identities_intact(await self._entries(category.id), projection.row_ids):
                # Nothing is re-ingested, but an Excel resave moved the stamp and every write-back guard
                # is compared against it, so recording it is the whole of a skip's work. Setting the same
                # float twice is not a change SQLAlchemy emits an UPDATE for: an untouched file stays so.
                category.workbook_mtime = detail.mtime
                await self._session.commit()
                return ReconcileOutcome(slug=slug, skipped=True)

        malformed = malformed_identity_rows(detail.rows, projection.row_ids)
        if malformed:
            raise IngestRefusedError(MALFORMED_IDENTITY_TEMPLATE.format(rows=", ".join(str(row) for row in malformed)))

        previously_ingested = category is not None and category.last_ingested_at is not None
        if category is None:
            category = self._fresh_category(slug, projection)
            self._session.add(category)
        self._described(category, projection)

        entries = await self._entries(category.id)
        plans, reminted = await self._planned(category, projection, entries)
        minted = sum(1 for plan in plans if plan.is_new)
        if is_near_total_mismatch(len(detail.rows), minted, previously_ingested=previously_ingested):
            raise IngestRefusedError(NEAR_TOTAL_MISMATCH_TEMPLATE.format(unmatched=minted, total=len(detail.rows)))

        removed = self._retired(entries, plans)
        self._repositioned(entries, plans)
        reresolved, refreshed = await self._resolved(slug, detail.name, projection, plans)
        await self._expanded(category.id)
        self._human_edit_events(projection, plans)

        written = await self._written_back(slug, projection, digest, plans)
        self._stamped(category, written if written is not None else detail)
        await self._session.commit()
        return ReconcileOutcome(
            slug=slug,
            matched=sum(1 for plan in plans if not plan.is_new and plan.identity_to_write is None),
            adopted=sum(1 for plan in plans if not plan.is_new and plan.identity_to_write is not None),
            minted=minted,
            reminted=reminted,
            removed=removed,
            reresolved=reresolved,
            refreshed=refreshed,
            workbook_written=written is not None,
        )

    async def _planned(
        self, category: Category, projection: WorkbookProjection, entries: Sequence[CuratedEntry]
    ) -> tuple[list[_RowPlan], int]:
        """Every sheet row matched, adopted or minted, in sheet order."""
        detail = projection.detail
        columns = curated_columns(detail.columns)
        own = {entry.id: entry for entry in entries}
        elsewhere = await self._claimed_elsewhere(category.id, projection.row_ids)

        plans: list[_RowPlan] = []
        deferred: list[tuple[WatchRow, int]] = []
        claimed: set[uuid.UUID] = set()
        reminted = 0
        for position, row in enumerate(detail.rows, start=1):
            parsed = parsed_identity(projection.row_ids.get(row.row, ""))
            if parsed is None:
                deferred.append((row, position))
                continue
            if parsed in claimed or parsed in elsewhere:
                # Section 12, R2: a duplicated id is a guess either way, so the lowest-positioned row
                # keeps it and the rest are re-minted. An id another category already holds was copied
                # between workbooks, and taking it would move that category's history.
                reminted += 1
                _LOGGER.info(
                    "reconcile_reminted job=%s category=%s row=%d reason=%s",
                    _JOB,
                    category.slug,
                    row.row,
                    "duplicate" if parsed in claimed else "claimed_elsewhere",
                )
                deferred.append((row, position))
                continue
            claimed.add(parsed)
            standing = own.get(parsed)
            if standing is None:
                # The sheet names an id nothing holds - a projection rebuilt from scratch under a workbook
                # that kept its column. The id is free, so the entry is minted under it and the cell is
                # left exactly as the owner's file already has it.
                plans.append(self._minted(category, row, position, columns, projection.watch_key, keep=parsed))
            else:
                plans.append(self._matched(standing, row, position, columns, projection.watch_key))

        candidates = [entry for entry in entries if entry.id not in claimed and entry.removed_at is None]
        for row, position in deferred:
            plans.append(self._adopted_or_minted(category, row, position, columns, projection.watch_key, candidates))
        plans.sort(key=lambda plan: plan.position)
        return plans, reminted

    def _matched(
        self,
        entry: CuratedEntry,
        row: WatchRow,
        position: int,
        columns: CuratedColumns,
        watch_key: str | None,
        *,
        identity_to_write: str | None = None,
    ) -> _RowPlan:
        changed = self._applied(entry, row, position, columns, watch_key)
        entry.removed_at = None
        return _RowPlan(
            row=row,
            position=position,
            entry=entry,
            is_new=False,
            raws_changed=changed,
            identity_to_write=identity_to_write,
        )

    def _minted(
        self,
        category: Category,
        row: WatchRow,
        position: int,
        columns: CuratedColumns,
        watch_key: str | None,
        *,
        keep: uuid.UUID | None = None,
    ) -> _RowPlan:
        """A brand-new entry. `keep` reuses the id the sheet already carries, so no cell needs rewriting."""
        entry = CuratedEntry(id=keep if keep is not None else uuid.uuid4(), category_id=category.id, position=position)
        self._applied(entry, row, position, columns, watch_key)
        self._session.add(entry)
        return _RowPlan(
            row=row,
            position=position,
            entry=entry,
            is_new=True,
            raws_changed=True,
            identity_to_write=None if keep is not None else str(entry.id),
        )

    def _adopted_or_minted(
        self,
        category: Category,
        row: WatchRow,
        position: int,
        columns: CuratedColumns,
        watch_key: str | None,
        candidates: list[CuratedEntry],
    ) -> _RowPlan:
        found = adoption_match(
            candidates,
            position=position,
            match_key=_entry_match_key(columns.raw_title(row), columns.raw_release(row)),
            raw_unit=columns.raw_unit(row),
            window=self._window,
        )
        if found is None:
            return self._minted(category, row, position, columns, watch_key)
        candidates.remove(found)
        return self._matched(found, row, position, columns, watch_key, identity_to_write=str(found.id))

    def _applied(
        self, entry: CuratedEntry, row: WatchRow, position: int, columns: CuratedColumns, watch_key: str | None
    ) -> bool:
        """Copy the sheet's own truth onto the entry, and report whether the resolver's inputs moved."""
        raw_title, raw_unit = columns.raw_title(row), columns.raw_unit(row)
        raw_release = columns.raw_release(row)
        key = _entry_match_key(raw_title, raw_release)
        changed = (entry.raw_title, entry.raw_unit, entry.raw_release, entry.match_key) != (
            raw_title,
            raw_unit,
            raw_release,
            key,
        )
        entry.position = position
        entry.sheet_row = row.row
        entry.raw_cells = dict(row.cells)
        entry.raw_title, entry.raw_unit, entry.raw_release, entry.match_key = raw_title, raw_unit, raw_release, key
        # Read, never trusted: the cell is only ever consulted to notice that a human moved it, and T25
        # is what turns that difference into an `excel_mirror` event (CLAUDE.md section 5.16).
        entry.observed_watch_cell = _required(
            "" if watch_key is None else row.cells.get(watch_key, "").strip(), CuratedEntry, "observed_watch_cell"
        )
        entry.last_seen_at = self._clock()
        return changed

    def _retired(self, entries: Sequence[CuratedEntry], plans: Sequence[_RowPlan]) -> int:
        """Soft-delete what the sheet stopped carrying. Nothing in the curated chain is ever removed."""
        kept = {plan.entry.id for plan in plans}
        now = self._clock()
        retired = [entry for entry in entries if entry.id not in kept and entry.removed_at is None]
        for entry in retired:
            entry.removed_at = now
            # There is no such row any more, so the stored number would point at whatever took its place.
            entry.sheet_row = None
        return len(retired)

    def _repositioned(self, entries: Sequence[CuratedEntry], plans: Sequence[_RowPlan]) -> None:
        """Renumber the whole category at once; the deferrable unique is what makes that legal."""
        live = [plan.entry.id for plan in plans]
        kept = set(live)
        retired = sorted(
            (entry for entry in entries if entry.id not in kept), key=lambda entry: (entry.position, str(entry.id))
        )
        positions = renumbered(live, [entry.id for entry in retired])
        for entry in (*(plan.entry for plan in plans), *retired):
            if entry.position != positions[entry.id]:
                entry.position = positions[entry.id]

    # -- the resolution leg -------------------------------------------------------------------------

    async def _resolved(
        self, slug: str, name: str, projection: WorkbookProjection, plans: Sequence[_RowPlan]
    ) -> tuple[int, int]:
        """Search and store a span for the entries that earned one; refresh the payloads that aged out."""
        columns = curated_columns(projection.detail.columns)
        selected: list[_RowPlan] = []
        quiet: list[_RowPlan] = []
        for plan in plans:
            (selected if _wanted(plan) else quiet).append(plan)
        if self._resolver is None or self._tmdb is None:
            for plan in selected:
                _note_unconfigured(plan.entry)
            return 0, 0
        for plan in selected:
            await self._resolve_one(slug, name, columns, plan)
        return len(selected), await self._refreshed(quiet)

    async def _refreshed(self, plans: Sequence[_RowPlan]) -> int:
        """Re-ingest the titles whose cached payload has reached TMDB's six-month cap. No search is spent.

        Both cursor reads are here rather than in the selection: `past_ceiling` is the clause that says a
        payload may no longer be cached, and `is_due` is the backoff a failure wrote, read rather than
        merely stored (CLAUDE.md section 9.2). Neither may change which work a row means - only how fresh
        this projection's copy of that work is - so nothing here can lose a title to an upstream that is
        down this evening.
        """
        if self._tmdb is None:  # pragma: no cover - guarded by the caller
            return 0
        titles = await self._titles({plan.entry.title_id for plan in plans if plan.entry.title_id is not None})
        refreshed = 0
        for title in titles.values():
            if title.tmdb_id is None:
                continue
            resource, key = _RESOURCE_FOR_MEDIA[title.media_type].value, str(title.tmdb_id)
            if not await self._cursors.past_ceiling(_SOURCE, resource, key):
                continue
            if not await self._cursors.is_due(_SOURCE, resource, key):
                continue
            await self._ingested(title.media_type, title.tmdb_id)
            refreshed += 1
        return refreshed

    async def _resolve_one(self, slug: str, name: str, columns: CuratedColumns, plan: _RowPlan) -> None:
        row = plan.row
        span = parse_unit(columns.raw_unit(row), raw_type=columns.raw_type(row))
        await self._answered(
            ResolutionRequest(
                category_slug=slug,
                category_name=name,
                raw_title=columns.raw_title(row),
                raw_unit=columns.raw_unit(row),
                raw_release=columns.raw_release(row),
                raw_type=columns.raw_type(row),
                span=span,
            ),
            plan.entry,
            span,
        )

    async def resolve_stored_entry(self, slug: str, name: str, entry: CuratedEntry) -> None:
        """Re-resolve ONE already-projected entry from its own stored cells - the review queue's retry (R71).

        The same leg `_resolve_one` runs for a sheet row, asking `curated_entry` for the row instead of the
        workbook: a retry is pressed from a queue whose rows are already here, and re-reading the file would
        make the control fail because Excel happens to be holding it. The Type cell comes back out of
        `raw_cells` rather than out of a `ColumnSpec`, which is the one thing the stored row does not keep.
        """
        raw_type = raw_type_cell(entry.raw_cells)
        span = parse_unit(entry.raw_unit, raw_type=raw_type)
        await self._answered(
            ResolutionRequest(
                category_slug=slug,
                category_name=name,
                raw_title=entry.raw_title,
                raw_unit=entry.raw_unit,
                raw_release=entry.raw_release,
                raw_type=raw_type,
                span=span,
            ),
            entry,
            span,
        )

    async def _answered(self, request: ResolutionRequest, entry: CuratedEntry, span: SpanParse) -> None:
        """Search for one row's title and store what came back, whichever store the row's cells came from."""
        if self._resolver is None or self._tmdb is None:  # pragma: no cover - guarded by both callers
            return
        resolution = await self._resolver.resolve(request)
        chosen = resolution.chosen
        if chosen is None or resolution.title_tmdb_id is None:
            # Ruling 35 among others: a tie comes back with no candidate at all, and is stored as any
            # other unresolved row - the note, the confidence as given, and no title_id to guess with.
            _store_resolution(entry, resolution, None, span)
            return
        media_type = MediaType.MOVIE if chosen.media_type == _PROVIDER_MOVIE else MediaType.TV
        title = await self._ingested(media_type, resolution.title_tmdb_id)
        if title is None:
            _leave_unresolved(
                entry,
                NO_TITLE_NOTE_TEMPLATE.format(media_type=media_type.value, tmdb_id=resolution.title_tmdb_id),
            )
            return
        _store_resolution(entry, resolution, title, span, chosen.season_number, chosen.episode_number)

    async def _ingested(self, media_type: MediaType, tmdb_id: int) -> Title | None:
        """The stored title, with its seasons, episodes, artwork and - for a series - its orderings."""
        if self._tmdb is None:  # pragma: no cover - guarded by the caller
            return None
        title = await self._tmdb.ensure_title(media_type, tmdb_id)
        if title is None:
            return None
        if media_type is MediaType.MOVIE:
            await self._tmdb.ingest_movie(tmdb_id)
            return title
        await self._tmdb.ingest_tv(tmdb_id)
        if self._orders is not None:
            await self._orders.rank_aired(title)
            await self._orders.ingest_tvdb_orders(title)
        return title

    # -- the flattened queue (T24) -------------------------------------------------------------------

    async def _expanded(self, category_id: uuid.UUID) -> int:
        """Rebuild `curated_entry_item` for the whole category, inside this same transaction.

        Placed after the entries are matched, retired, repositioned and resolved, and before the
        write-back: the queue is a function of all four, and a pass the workbook then refuses rolls the
        queue back with everything else rather than leaving a projection of a write that never landed.

        Flushed first, deliberately. The rebuild reads `curated_entry` with a SELECT, and a session with
        autoflush off - the reconciler's own tests bind one - would otherwise hide the entries this pass
        has just minted from the queue that is meant to hold them.

        Every live entry, not only the ones that moved: a single reposition reorders the whole category's
        `absolute_position` anyway, and a scoped rebuild would save one SELECT over at most a few hundred
        rows at the cost of having to be right about which entries an ingest touched.
        """
        await self._session.flush()
        return await self._expand(self._session, category_id)

    # -- the mirror's two seams (T25) ---------------------------------------------------------------

    def _human_edit_events(self, projection: WorkbookProjection, plans: Sequence[_RowPlan]) -> None:
        """One coarse `excel_mirror` event per cell a human moved in Excel since the last pass.

        The comparison it needs is already made: `_applied` has just stored `observed_watch_cell`, and
        `mirrored_watch_cell` still holds whatever this app last wrote there. A difference between the two
        is a human edit; equality is our own echo, and the whole defence against the mirror loop
        (CLAUDE.md section 5.16). Appended before the write-back below, so the view the mirror then reads
        already carries what the owner typed.

        A workbook with no status column reports no cell at all rather than an empty one. The difference
        matters for the one sheet that HAD a status column and no longer does: its entries still carry
        whatever was last mirrored into them, so an empty reading would look like a hand edit clearing
        every row, and would look like one again on every pass after that.
        """
        entries = [plan.entry for plan in plans]
        observed = {} if projection.watch_key is None else {entry.id: entry.observed_watch_cell for entry in entries}
        self._session.add_all(human_edit_events(entries, observed, now=self._clock()))

    async def _pending_mirror_cells(
        self, projection: WorkbookProjection, plans: Sequence[_RowPlan]
    ) -> dict[uuid.UUID, str]:
        """The derived statuses this pass owes the sheet, keyed by entry.

        Empty when the workbook has no status column: there is nowhere to project onto, and a sheet the
        owner never gave one is not an error. Empty too when nothing moved, which is what keeps an
        unchanged pass from rewriting nineteen files to say what they already say.

        Filtered against the sheet's own dropdown last. The ingest never calls `write_mirror_cells`, so
        this is where Ruling 41 lands on this path: a value that column would refuse is dropped here
        rather than refusing - and rolling back - the whole pass at `writer._validate`.
        """
        column = watch_column(projection.detail.columns)
        if column is None or not plans:
            return {}
        entries = [plan.entry for plan in plans]
        states = await entry_watch_states(self._session, entries[0].category_id)
        return writable_mirror_cells(pending_mirror_cells(entries, states), column, category=projection.detail.id)

    # -- the workbook write -------------------------------------------------------------------------

    async def _written_back(
        self, slug: str, projection: WorkbookProjection, digest: str, plans: Sequence[_RowPlan]
    ) -> CategoryDetail | None:
        """The pass's whole diff in one `Catalog._write`, or `None` when it has nothing to say."""
        ids = {plan.row.row: plan.identity_to_write for plan in plans if plan.identity_to_write is not None}
        pending = await self._pending_mirror_cells(projection, plans)
        watch_key = projection.watch_key
        cells = (
            {plan.row.row: {watch_key: pending[plan.entry.id]} for plan in plans if plan.entry.id in pending}
            if watch_key is not None
            else {}
        )
        if not ids and not cells:
            return None
        try:
            written = await self._catalog.apply_ingest_writeback(slug, ids, cells, projection.detail.mtime)
        except StaleWorkbookError:
            written = await self._retried(slug, projection, digest, ids, cells)
        # Only once the write has landed, and in this same transaction: without the record of what was
        # written, the next pass reads our own cells as hand edits and the echo loop never closes. A
        # locked or stale refusal raises past this line, so neither store moves (section 5.16).
        record_mirrored([plan.entry for plan in plans], pending)
        return written

    async def _retried(
        self,
        slug: str,
        projection: WorkbookProjection,
        digest: str,
        ids: Mapping[int, str],
        cells: Mapping[int, Mapping[str, str]],
    ) -> CategoryDetail:
        """One retry, and only when nothing this pass reasoned about has moved.

        The mirror is the writer that must lose a race with the owner (master plan section 6.3): if the
        grid or the identities changed under us, the plan in hand was computed against a sheet that no
        longer exists, so the refusal stands and the whole pass rolls back to be replayed identically.
        """
        fresh = await self._catalog.projection(slug)
        if digest_grid(fresh.detail.columns, fresh.detail.rows) != digest or fresh.row_ids != projection.row_ids:
            raise StaleWorkbookError(projection.detail.file_name)
        return await self._catalog.apply_ingest_writeback(slug, ids, cells, fresh.detail.mtime)

    # -- the category row ---------------------------------------------------------------------------

    def _fresh_category(self, slug: str, projection: WorkbookProjection) -> Category:
        """A category row for a workbook the projection has never seen. The id is minted here rather than
        at flush, because every entry this pass creates needs `category_id` before anything is written."""
        return Category(
            id=uuid.uuid4(),
            slug=slug,
            file_name=projection.detail.file_name,
            sheet_title=projection.detail.sheet_title,
            accent=projection.detail.accent,
        )

    async def _category(self, slug: str) -> Category | None:
        return await self._session.scalar(
            select(Category).where(Category.slug == slug).with_for_update().execution_options(populate_existing=True)
        )

    async def _entries(self, category_id: uuid.UUID) -> list[CuratedEntry]:
        """Every entry this category has ever had, soft-deleted ones included: a row can come back."""
        rows = await self._session.scalars(
            select(CuratedEntry)
            .where(CuratedEntry.category_id == category_id)
            .order_by(CuratedEntry.position)
            .execution_options(populate_existing=True)
        )
        return list(rows)

    async def _claimed_elsewhere(self, category_id: uuid.UUID, row_ids: Mapping[int, str]) -> set[uuid.UUID]:
        """Ids in this sheet that belong to some other category - a row copied between workbooks."""
        parsed = {found for text in row_ids.values() if (found := parsed_identity(text)) is not None}
        if not parsed:
            return set()
        rows = await self._session.execute(
            select(CuratedEntry.id).where(CuratedEntry.id.in_(parsed), CuratedEntry.category_id != category_id)
        )
        return {row.id for row in rows}

    async def _titles(self, title_ids: set[uuid.UUID]) -> dict[uuid.UUID, Title]:
        if not title_ids:
            return {}
        rows = await self._session.scalars(select(Title).where(Title.id.in_(title_ids)))
        return {title.id: title for title in rows}

    def _described(self, category: Category, projection: WorkbookProjection) -> None:
        """The workbook's own identity, refreshed every pass: a rename changes all of it at once."""
        detail = projection.detail
        category.file_name = detail.file_name
        category.sheet_title = detail.sheet_title
        category.accent = detail.accent
        category.identity_column_key = projection.identity_key

    def _stamped(self, category: Category, detail: CategoryDetail) -> None:
        """The stamp and digest of the file AS IT NOW STANDS, so the next pass skips our own write."""
        category.workbook_mtime = detail.mtime
        category.workbook_digest = digest_grid(detail.columns, detail.rows)
        category.last_ingested_at = self._clock()
        category.last_ingest_error = None

    async def _refusal_recorded(self, slug: str, projection: WorkbookProjection, reason: str) -> ReconcileOutcome:
        """Roll the pass back, then record why - visibly, and without a stamp that would skip the retry."""
        await self._session.rollback()
        category = await self._category(slug)
        if category is None:
            category = self._fresh_category(slug, projection)
            self._session.add(category)
        self._described(category, projection)
        category.last_ingest_error = reason
        await self._session.commit()
        return ReconcileOutcome(slug=slug, refused=reason)

    # -- logging ------------------------------------------------------------------------------------

    def _logged(self, outcome: ReconcileOutcome, started: float, *, refused: str | None = None) -> ReconcileOutcome:
        """The end record every pass writes, zeros included: a run that changed nothing must say so.

        `refused` names why the workbook was left alone when the reason is not on the outcome - a write
        the workbook itself declined never becomes one, because it is re-raised rather than returned.
        """
        _LOGGER.info(
            "reconcile_end job=%s category=%s skipped=%s matched=%d adopted=%d minted=%d reminted=%d"
            " removed=%d reresolved=%d refreshed=%d written=%s refused=%s elapsed_ms=%d",
            _JOB,
            outcome.slug,
            outcome.skipped,
            outcome.matched,
            outcome.adopted,
            outcome.minted,
            outcome.reminted,
            outcome.removed,
            outcome.reresolved,
            outcome.refreshed,
            outcome.workbook_written,
            refused if refused is not None else (_REFUSED if outcome.refused is not None else _NOT_REFUSED),
            int((time.monotonic() - started) * 1000),
        )
        return outcome


def _note_unconfigured(entry: CuratedEntry) -> None:
    """Record that no provider was reachable, without spending a resolution the pass never made.

    A row that has never resolved is left `unresolved` with the reason on it, which is what makes the
    next configured pass pick it up again. A row that HAS resolved keeps its title, its state and its
    confidence: a human's `confirmed` must not be undone because a token was absent, and that is true
    even when the row's own cells moved - what moved is a reason to re-resolve, not a reason to forget
    the standing answer before anything has been asked.
    """
    if entry.title_id is None:
        _leave_unresolved(entry, NOT_CONFIGURED_NOTE)
        return
    entry.resolution_note = NOT_CONFIGURED_NOTE


def _refusal_label(refusal: WorkbookError) -> str:
    """The one-word reason a log record carries. Looked up by exact type, as `api/errors.py` does."""
    return _REFUSAL_LABELS.get(type(refusal), _WORKBOOK_REFUSED)


def _wanted(plan: _RowPlan) -> bool:
    """`needs_resolution` for one plan, so the three facts it reads are spelled out in exactly one place."""
    return needs_resolution(plan.entry.resolution_state, is_new=plan.is_new, raws_changed=plan.raws_changed)


def _entry_match_key(raw_title: str, raw_release: str) -> str | None:
    """The stored key, clipped to the column's own declared width by T19's helper."""
    return _fitted(match_key(raw_title, year=release_year(raw_release)), CuratedEntry, "match_key")


def _leave_unresolved(entry: CuratedEntry, note: str) -> None:
    """No title, and the reason on the row where the review queue will read it."""
    entry.title_id = None
    entry.resolution_state = ResolutionState.UNRESOLVED
    entry.resolution_note = note


def _store_resolution(
    entry: CuratedEntry,
    resolution: TitleResolution,
    title: Title | None,
    span: SpanParse,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> None:
    """One row's answer, stored faithfully - the confidence included, because T30/T57 key on it."""
    entry.title_id = None if title is None else title.id
    entry.unit_kind = resolution.unit_kind
    entry.resolution_state = resolution.state
    entry.resolution_confidence = resolution.confidence
    entry.resolution_note = resolution.note
    order_type, start, end, season = span_values(span, season_number=season_number, episode_number=episode_number)
    entry.order_type = order_type
    entry.span_start, entry.span_end, entry.season_number = start, end, season
