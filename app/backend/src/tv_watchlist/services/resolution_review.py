"""The review queue: the rows a heuristic could not settle, and the three things a human may do to one.

`auto` is not trusted. The resolver's own confidence is a ranking, never a verdict, so an auto-resolved
entry sits in this queue beside an unresolved one until a person says otherwise - and the moment a person
does, the decision is `confirmed`, which no later pass may overwrite (master plan 6.5 rule 5, CLAUDE.md
18.2). `needs_resolution` in `ingest.reconciler` is the other half of that rule; everything written here
is chosen so that predicate answers `False` for a settled row whose cells have not moved.

Nothing in this module commits. The transaction boundary is the request, and `api/review.py` is where it
closes - the same split `ingest` uses, for the same reason: a half-applied decision that recorded itself
as applied is worse than one that failed.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import PurePath
from typing import Final

from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tv_watchlist.clients.jellyfin_client import JellyfinClient
from tv_watchlist.config import Settings
from tv_watchlist.constants import (
    CONFIRMED_RESOLUTION_CONFIDENCE,
    MAX_ENTRIES_PAGE_SIZE,
    MAX_REASON_LENGTH,
    REVIEW_NOTE_PREFIX,
)
from tv_watchlist.data.enums import ResolutionState
from tv_watchlist.data.errors import ResolutionConflictError
from tv_watchlist.data.models import Category, CuratedEntry, EpisodeOrder, Title
from tv_watchlist.ingest.episode_order_busy_error import EpisodeOrderBusyError
from tv_watchlist.ingest.expansion import NOTE_JOIN, rebuild_items
from tv_watchlist.ingest.runtime import IngestRuntime
from tv_watchlist.ingest.tmdb_ingest import TmdbIngest
from tv_watchlist.models.cell_text import sanitize
from tv_watchlist.models.curated_entry_read import CuratedEntryRead
from tv_watchlist.models.resolution_update import CONFIRM, CORRECT, ResolutionUpdate
from tv_watchlist.services.entries import read_entries
from tv_watchlist.services.locked_curated_entry import locked_curated_entry

#: The two states a person put a row into. Neither may be moved by a heuristic (master plan 6.5, rule 5),
#: which is what `needs_resolution` already says for a pass and what the retry route says for one row.
HUMAN_DECIDED: Final[frozenset[ResolutionState]] = frozenset({ResolutionState.CONFIRMED, ResolutionState.REJECTED})

#: What the queue holds when a caller names no states: everything a heuristic left behind. Exactly the
#: predicate of the partial index `ix_curated_entry_needs_review`, so the listing is an index scan.
DEFAULT_REVIEW_STATES: Final[tuple[ResolutionState, ...]] = (ResolutionState.UNRESOLVED, ResolutionState.AUTO)

#: The canonical ordering of a numbering, as `episode_order.label` spells it. A correct names a type and
#: never a label, so it means the title's own ordering of that type rather than some named alternate.
CANONICAL_ORDER_LABEL: Final[str] = ""

NOT_CONFIGURED: Final[str] = "TMDB is not configured, so this decision cannot be checked against it"
#: Rule 5 as a refusal: a retry is a heuristic, and a heuristic never overwrites a human decision. Both
#: `confirmed` and `rejected` are decisions - a rejected row was told there is no right match, and a
#: re-resolve that stored one would be the search overruling the person. `correct` is the way back from
#: either, because it is a person naming the title rather than a search guessing at one.
HUMAN_DECIDED_REFUSAL: Final[str] = (
    "{entry_id} is {state}, which a human decided; correct it instead of re-resolving it"
)
INCOHERENT_CORRECTION: Final[str] = "a correction names the title it corrects to: media_type and tmdb_id"
NO_SUCH_TITLE: Final[str] = "TMDB has nothing stored or fetchable under {media_type}:{tmdb_id}"
NO_SUCH_ORDER: Final[str] = "{name} carries no '{order_type}' numbering"


# ---------------------------------------------------------------------------------------------------
# Pure decisions. Everything in this block is a function of its arguments and needs no database - the
# same split `ingest.reconciler` draws, and for the same reason: the state machine is what rule 5 is
# about, so it is assertable without a server.
# ---------------------------------------------------------------------------------------------------


def confirmed(entry: CuratedEntry) -> None:
    """A human agrees with what is already on the row. Nothing about the match itself moves."""
    entry.resolution_state = ResolutionState.CONFIRMED
    entry.resolution_confidence = CONFIRMED_RESOLUTION_CONFIDENCE


def rejected(entry: CuratedEntry) -> None:
    """The match was wrong and there is no right one to offer. The sheet's own row is untouched.

    The confidence goes with the title: a number left behind would claim the app is half sure of a match
    it has just been told does not exist.
    """
    entry.title = None
    entry.resolution_state = ResolutionState.REJECTED
    entry.resolution_confidence = None
    entry.order_type = None
    entry.order_label = CANONICAL_ORDER_LABEL
    entry.span_start = None
    entry.span_end = None
    entry.season_number = None


def reviewed(existing: str, update: ResolutionUpdate) -> str:
    """One note carrying at most one review clause: the resolver's and the queue's parts kept, ours replaced.

    The same shape as `expansion.noted`, and deliberately not that function: it owns the `queue: ` clause
    and this owns the `review: ` one, so a rebuild and a review can each rewrite their own sentence.
    """
    kept = [part for part in existing.split(NOTE_JOIN) if part and not part.startswith(REVIEW_NOTE_PREFIX)]
    # The note is stored text rather than a log line, but a control character is still not something the
    # column can hold, and `sanitize` is this project's one normaliser for that (CLAUDE.md section 5.6).
    said = sanitize(update.note, MAX_REASON_LENGTH).strip()
    kept.append(f"{REVIEW_NOTE_PREFIX}{update.action}{f' - {said}' if said else ''}")
    return NOTE_JOIN.join(kept)


def review_queue_statement(
    states: Sequence[ResolutionState], category_slug: str | None, *, limit: int, offset: int
) -> Select[tuple[CuratedEntry]]:
    """The queue's one query, worst first.

    `resolution_confidence ASC NULLS FIRST` puts the rows nobody could resolve at all above the ones a
    heuristic was least sure of, then `category.slug` and `position` make the order of the rest total -
    without that last pair two rows of equal confidence could swap places between pages of one listing.

    The WHERE is the predicate of the partial index `ix_curated_entry_needs_review`, so the index is what
    narrows the rows; it does not serve the ORDER BY, which is by confidence and therefore sorts whatever
    comes back. `category.retired_at IS NULL` is the one predicate on top of it: a workbook that has been
    retired into `app/.backups/` keeps its `curated_entry` rows - the chain is soft-deleted, never purged
    (CLAUDE.md section 5.13) - and asking a human to review rows of a file they have put away is asking
    the wrong question. The join it reads is already here for the slug, and the sort is already forced.
    """
    statement = (
        select(CuratedEntry)
        .join(Category, Category.id == CuratedEntry.category_id)
        .where(
            CuratedEntry.removed_at.is_(None),
            CuratedEntry.resolution_state.in_(tuple(states)),
            Category.retired_at.is_(None),
        )
        .options(selectinload(CuratedEntry.title))
        .order_by(
            CuratedEntry.resolution_confidence.asc().nulls_first(),
            Category.slug,
            CuratedEntry.position,
        )
        .limit(limit)
        .offset(offset)
    )
    if category_slug is None:
        return statement
    return statement.where(Category.slug == category_slug)


# ---------------------------------------------------------------------------------------------------
# The database half.
# ---------------------------------------------------------------------------------------------------


async def list_for_review(
    session: AsyncSession,
    settings: Settings,
    *,
    states: Sequence[ResolutionState] = DEFAULT_REVIEW_STATES,
    category_slug: str | None = None,
    limit: int = MAX_ENTRIES_PAGE_SIZE,
    offset: int = 0,
    jellyfin: JellyfinClient | None = None,
) -> list[CuratedEntryRead]:
    """One page of the review queue, worst first. The order and the predicate are `review_queue_statement`."""
    statement = review_queue_statement(states, category_slug, limit=limit, offset=offset)
    entries = (await session.execute(statement)).scalars().all()
    return await read_entries(session, settings, entries, jellyfin=jellyfin)


async def apply_resolution(
    session: AsyncSession,
    settings: Settings,
    runtime: IngestRuntime,
    entry_id: uuid.UUID,
    update: ResolutionUpdate,
    *,
    jellyfin: JellyfinClient | None = None,
) -> CuratedEntryRead:
    """Apply one human decision, rebuild that entry's queue items, and answer with the row as it now is.

    Every action rebuilds, including `confirm`: `expand_entry` refuses to expand an `unresolved` or
    `rejected` entry, so a state change alone moves rows into or out of `curated_entry_item`, and a queue
    left un-rebuilt would disagree with the row the API just returned.
    """
    await locked_curated_entry(session, entry_id)
    entry = await _live_entry(session, entry_id)
    if update.action == CONFIRM:
        confirmed(entry)
    elif update.action == CORRECT:
        await _corrected(session, runtime, entry, update)
    else:
        rejected(entry)
    entry.resolution_note = reviewed(entry.resolution_note, update)
    await session.flush()
    await rebuild_items(session, entry.category_id, [entry.id])
    await session.flush()
    return (await read_entries(session, settings, [entry], jellyfin=jellyfin))[0]


async def retry_resolution(
    session: AsyncSession,
    settings: Settings,
    runtime: IngestRuntime,
    entry_id: uuid.UUID,
    *,
    jellyfin: JellyfinClient | None = None,
) -> CuratedEntryRead:
    """Re-resolve one entry against the provider and answer with the row as it now stands (R71).

    The control exists because an untouched workbook is skipped, so nothing re-resolves a row a provider
    outage left `unresolved` except the next real edit - and the queue is where a person is already
    looking at that row. It spends one search on one row, which is why it is here rather than a `--force`
    over 996 of them.

    Both refusals are checked before anything is asked of TMDB, so a refused retry changes nothing at all
    and spends nothing: a `confirmed` or `rejected` row is a human decision a heuristic may not take back
    (`HUMAN_DECIDED`), and an unconfigured provider cannot honour the request - silently leaving the row
    as it was would look exactly like a retry that tried and found nothing.
    """
    _, category = await locked_curated_entry(session, entry_id)
    entry = await _live_entry(session, entry_id)
    if entry.resolution_state in HUMAN_DECIDED:
        raise ResolutionConflictError(
            HUMAN_DECIDED_REFUSAL.format(entry_id=entry_id, state=entry.resolution_state.value)
        )
    if not runtime.tmdb_client(session).configured:
        raise ResolutionConflictError(NOT_CONFIGURED)
    try:
        await runtime.reconciler(session).resolve_stored_entry(category.slug, _workbook_name(category), entry)
    except EpisodeOrderBusyError as error:
        raise ResolutionConflictError(str(error)) from error
    await session.flush()
    # The same rebuild `apply_resolution` runs, for the same reason: a resolve moves rows into or out of
    # `curated_entry_item`, and a queue left un-rebuilt would disagree with the row just returned.
    await rebuild_items(session, entry.category_id, [entry.id])
    await session.flush()
    # Read again, refreshed. The store step writes `title_id`, the column, which is what a whole pass
    # wants; the `title` loaded beside it is then stale, and `lazy="raise_on_sql"` means that stale value
    # is what the response would carry. `apply_resolution` has no such step because `_corrected` assigns
    # the relationship itself, which it can - it is the one holding the `Title`.
    return (await read_entries(session, settings, [await _live_entry(session, entry_id)], jellyfin=jellyfin))[0]


def _workbook_name(category: Category) -> str:
    """The name the franchise templates expand against: the filename's stem, as the reader derives it.

    `Category` stores the file name rather than the name, and `reader.read_category` takes the name from
    `path.stem`, so the stem is the name - not a second spelling of it (CLAUDE.md section 3.2). `PurePath`
    rather than a suffix strip, for the same reason: the reader's own derivation, not a second one that
    would part company with it the day a workbook is named `.xlsm`.
    """
    return PurePath(category.file_name).stem


async def _live_entry(session: AsyncSession, entry_id: uuid.UUID) -> CuratedEntry:
    """Refresh the fenced live entry and its eager title, including identity-map state."""
    statement = (
        select(CuratedEntry)
        .where(CuratedEntry.id == entry_id, CuratedEntry.removed_at.is_(None))
        .options(selectinload(CuratedEntry.title))
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalar_one()


async def _corrected(
    session: AsyncSession, runtime: IngestRuntime, entry: CuratedEntry, update: ResolutionUpdate
) -> None:
    """A human names the title and the span this row really meant.

    The span fields are replaced wholesale by what the request carries, `None` included: a correction
    that merged into whatever was standing would mean different things depending on state the reviewer
    cannot see. `unit_kind` is the exception only because its column is NOT NULL - an omitted one keeps
    the value the row already had.
    """
    title = await _ensured_title(session, runtime, update)
    if update.order_type is not None and not await _carries_order(session, title, update.order_type):
        raise ResolutionConflictError(NO_SUCH_ORDER.format(name=title.name, order_type=update.order_type))
    # The relationship, not the column: `title_id` alone would leave the loaded `entry.title` stale, and
    # `lazy="raise_on_sql"` means the stale value is what the response would carry.
    entry.title = title
    if update.unit_kind is not None:
        entry.unit_kind = update.unit_kind
    entry.order_type = update.order_type
    entry.order_label = CANONICAL_ORDER_LABEL
    entry.span_start = update.span_start
    entry.span_end = update.span_end
    entry.season_number = update.season_number
    entry.resolution_state = ResolutionState.CONFIRMED
    entry.resolution_confidence = CONFIRMED_RESOLUTION_CONFIDENCE


async def _ensured_title(session: AsyncSession, runtime: IngestRuntime, update: ResolutionUpdate) -> Title:
    """The stored work for the TMDB id the reviewer named, fetched and upserted if it is not here yet."""
    if update.media_type is None or update.tmdb_id is None:  # pragma: no cover - the model already refused this
        # Unreachable: `ResolutionUpdate` refuses a `correct` without both. It says so in its own words
        # rather than borrowing NOT_CONFIGURED, because a message that blamed an absent token for a
        # malformed body would send the next reader to the wrong file.
        raise ResolutionConflictError(INCOHERENT_CORRECTION)
    client = runtime.tmdb_client(session)
    if not client.configured:
        # An absent token is a disabled feature, never a crash - but it cannot honour this decision, and
        # silently storing no title would look exactly like a correction that worked.
        raise ResolutionConflictError(NOT_CONFIGURED)
    title = await TmdbIngest(session, client, artwork=runtime.artwork).ensure_title(update.media_type, update.tmdb_id)
    if title is None:
        raise ResolutionConflictError(NO_SUCH_TITLE.format(media_type=update.media_type.value, tmdb_id=update.tmdb_id))
    return title


async def _carries_order(session: AsyncSession, title: Title, order_type: str) -> bool:
    """Whether this title has that numbering stored. Checked before the write, so a refusal changes nothing."""
    statement = select(
        exists().where(
            EpisodeOrder.title_id == title.id,
            EpisodeOrder.order_type == order_type,
            EpisodeOrder.label == CANONICAL_ORDER_LABEL,
        )
    )
    return bool(await session.scalar(statement))
