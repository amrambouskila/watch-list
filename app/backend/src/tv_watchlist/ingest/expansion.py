"""The flattened queue: every playable unit of a category, in the order its workbook put them.

Four rules shape this module.

**Every playable unit has a row, films included.** An entry contributes one row per episode of its
resolved span and, when the row is a film, exactly one row of its own (ADR-010). The queue as first
designed held episodes only, so "what plays next" would have jumped from the episode before a film
straight to the episode after it - the wrong answer to the one requirement the queue exists for
(master plan section 6.9).

**A span is a range over a numbering, never a list of episodes.** `episode_order.sequence` is a dense
rank inside one numbering, so One Piece's `E19-53` is one range scan and stays one after TMDB inserts a
recap (CLAUDE.md section 11.2, rule 10). What the entry names is what is scanned: an entry naming an
ordering its title does not carry expands to nothing and says so, and never quietly falls back to the
aired rank, because a confidently wrong span is the one failure shape that looks right on screen.

**A season number off a sheet is a TMDB season number.** So a lookup by `(season, episode)` reads the
two numberings this app computes itself - the aired rank and the specials bucket the aired walk excludes
- which together hold every episode TMDB listed, exactly once, under TMDB's own pair. A provider
ordering renumbers into its own seasons, so its `order_season_number` cannot answer that question.

**The queue is a cache and says so.** It is rebuilt delete-then-insert inside the ingest transaction and
never hand-edited, and `absolute_position` is renumbered for the whole category in one statement that
the deferred unique on `(category_id, absolute_position)` lets pass through its transient duplicates.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.constants import SPECIALS_ORDER_LABEL
from tv_watchlist.data.enums import MediaType, ResolutionState, UnitKind
from tv_watchlist.data.models import CuratedEntry, CuratedEntryItem, EpisodeOrder, Title
from tv_watchlist.ingest.episode_orders import AIRED_ORDER_TYPE, NO_LABEL, SPECIALS_ORDER_TYPE

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_JOB: Final[str] = "expansion"

#: 1-based, both of them: `position_in_entry` and `absolute_position` each carry a `CHECK >= 1`.
FIRST_POSITION: Final[int] = 1

#: The two numberings this app derives itself. Together they hold every episode TMDB listed exactly
#: once, keyed by TMDB's own `(season, episode)` pair, which is what a sheet's season number means.
OWN_ORDERINGS: Final[tuple[tuple[str, str], ...]] = (
    (AIRED_ORDER_TYPE, NO_LABEL),
    (SPECIALS_ORDER_TYPE, SPECIALS_ORDER_LABEL),
)

#: `(season, episode, episode_id)`: one own-ordering slot with both halves of its pair present, so a
#: lookup by pair never has to ask again whether either number is there.
type OwnSlot = tuple[int, int, uuid.UUID]

#: Kinds that name no span of their own and may turn out to be a film once the title is known: a `Short`
#: or an `OVA` cell states a shape without stating a length, and an unparsed cell states nothing at all.
#: Sixty-nine of the library's rows are one of these - twenty-two in One Piece alone - and a title that
#: resolved to a TMDB movie makes every one of them a single slot rather than an episode that is missing.
FILM_SHAPED_KINDS: Final[frozenset[UnitKind]] = frozenset({UnitKind.SPECIAL, UnitKind.UNKNOWN})

#: States that expand to nothing. Their rows already carry the reason the review queue shows, so the
#: queue adds no second one: an entry that never resolved has nothing to expand and knows why.
UNEXPANDABLE_STATES: Final[frozenset[ResolutionState]] = frozenset(
    {ResolutionState.UNRESOLVED, ResolutionState.REJECTED}
)

# Reason codes: a closed vocabulary, so "why did forty rows contribute nothing" is a count in the log
# rather than a grep. The sentence a human reads goes on the row, never into a log line - an
# `order_type` is a provider's own string and a log record is not somewhere a crafted one may reach
# (CLAUDE.md section 10.3, header/log injection).
NO_TITLE: Final[str] = "no_title"
NOT_RESOLVED: Final[str] = "not_resolved"
NO_SPAN: Final[str] = "no_span"
NO_SEASON: Final[str] = "no_season"
MISSING_ORDER: Final[str] = "missing_order"
EMPTY_RANGE: Final[str] = "empty_range"
SHORT_COVER: Final[str] = "short_cover"
SEASON_NOT_COVERED: Final[str] = "season_not_covered"
UNSUPPORTED_KIND: Final[str] = "unsupported_kind"

# The sentences those codes put on the row. None of them names the aired rank: a refusal that mentioned
# it would read as the fallback this module refuses to make.
MISSING_ORDER_NOTE: Final[str] = "this title carries no {order} ordering, so the queue holds none of this row"
EMPTY_RANGE_NOTE: Final[str] = "the {order} ordering holds nothing between {start} and {end}"
SHORT_COVER_NOTE: Final[str] = "the {order} ordering holds {found} of the {asked} episodes this row names"
SEASON_NOT_COVERED_NOTE: Final[str] = (
    "the numbering is unknown and season {season} holds no run from {start} to {end}, so the queue holds "
    "none of this row"
)
NO_SEASON_NOTE: Final[str] = "the numbering is unknown and no season scopes it, so the queue holds none of this row"
NO_EPISODE_SPAN_NOTE: Final[str] = "no episode span is stored for this row, so the queue holds none of it"
NO_SEASON_NAMED_NOTE: Final[str] = "this row names no season, so the queue holds none of it"
# Deliberately not a sentence about a missing span: this row is an OVA, a special or a short, and those
# name no span in the first place. What it is missing is the second-pass match that would place it at one
# episode inside its title - and if the title had been a film, it would have taken the film branch.
UNMATCHED_SPECIAL_NOTE: Final[str] = (
    "this row was never matched to an episode inside its title, so the queue holds none of it"
)
NO_SEASONS_FOUND_NOTE: Final[str] = "this title carries no episode of season {seasons}"
UNSUPPORTED_KIND_NOTE: Final[str] = "a {kind} row names no playable unit"

#: How a queue clause is told apart from the resolver's own note, so a rebuild replaces its own clause
#: rather than stacking one per pass onto a row nothing else touched.
QUEUE_NOTE_PREFIX: Final[str] = "queue: "
NOTE_JOIN: Final[str] = " | "

_LABELLED_ORDER: Final[str] = "{order_type} ({label})"


@dataclass(frozen=True, slots=True)
class ExpansionItem:
    """One playable unit before it is a row: an episode of a span, or a film entry's single slot."""

    episode_id: uuid.UUID | None
    movie_title_id: uuid.UUID | None
    position_in_entry: int


@dataclass(frozen=True, slots=True)
class Expansion:
    """What one entry contributes and, when that is less than its cell asked for, why.

    `note` is the sentence the review queue shows on the row; `reason` is the closed code the log
    counts. Both are empty when the row expanded exactly as it was written.
    """

    items: tuple[ExpansionItem, ...] = ()
    note: str = ""
    reason: str = ""


def noted(existing: str, queue_note: str) -> str:
    """One note carrying at most one queue clause: the resolver's own parts kept, ours replaced."""
    kept = [part for part in existing.split(NOTE_JOIN) if part and not part.startswith(QUEUE_NOTE_PREFIX)]
    if queue_note:
        kept.append(f"{QUEUE_NOTE_PREFIX}{queue_note}")
    return NOTE_JOIN.join(kept)


# ---------------------------------------------------------------------------------------------------
# Pure. Everything above the database half is a function of its arguments and needs no session.
# ---------------------------------------------------------------------------------------------------


def numberings_for(entry: CuratedEntry) -> tuple[tuple[str, str], ...]:
    """The numbering(s) this entry's queue rows were, or would be, expanded under.

    One statement of the dispatch `expand_entry` performs below, public because a second reader needs the
    same answer: `services/episode_match.py` joins those rows to the owner's files, and a join addressing a
    numbering the queue was NOT built over looks under the wrong `(season, episode)` pair - finding nothing
    where the file is really there, or, where the other numbering happens to carry a row, naming the wrong
    file as a match. Deciding it twice is how those two drift, so it is decided here once (Ruling 97).

    Per kind, mirroring each branch exactly:

    * `EPISODES` - the ordering the row names (`_from_a_span` -> `_within_an_ordering`), or the two this app
      derives when it names none, which is what `_within_a_season` resolves its pair against.
    * `SERIES` - the ordering the row names, or **the aired rank alone** when it names none. That is
      `_from_a_whole_title` verbatim: "the whole show" is the aired walk, and the specials bucket beside it
      is not part of it. Returning both would be benign only by the accident that the two are disjoint.
    * `SEASON` and `SPECIAL` - always the two own orderings. Neither `_from_seasons` nor
      `_from_one_matched_episode` reads `order_type` at all: both resolve by TMDB's own `(season, episode)`
      pair, so an `order_type` left on such a row by a correction (`services/resolution_review._corrected`
      sets it without touching `unit_kind`) names a numbering the queue never used, and is ignored here too.
    * `MOVIE`, and any kind that expands to nothing - the own orderings, so every caller has a usable
      predicate rather than an empty one. A film contributes one movie slot carrying no episode, so nothing
      selects under them; the episode join filters those slots out before it asks (ADR-010).
    """
    if entry.unit_kind is UnitKind.EPISODES:
        if entry.order_type is None:
            return OWN_ORDERINGS
        return ((entry.order_type, entry.order_label),)
    if entry.unit_kind is UnitKind.SERIES:
        if entry.order_type is None:
            return ((AIRED_ORDER_TYPE, NO_LABEL),)
        return ((entry.order_type, entry.order_label),)
    return OWN_ORDERINGS


def expand_entry(entry: CuratedEntry, orders: Sequence[EpisodeOrder], media_type: MediaType | None = None) -> Expansion:
    """What one entry puts in the queue, read off the title's stored numberings.

    `orders` is every `episode_order` row of this entry's title; which of them apply is this function's
    decision, and it is made from what the entry itself names rather than from what happens to be there.

    `media_type` is that title's own kind, and it settles exactly one question: a cell reading `OVA`,
    `Short` or nothing at all says what shape a row is without saying how long it is, and a title that
    resolved to a TMDB movie makes it a film. `None` leaves that question open and the row takes the
    episode path, which is what an unknown media type honestly means rather than a guess at one.
    """
    if entry.title_id is None:
        return Expansion(reason=NO_TITLE)
    if entry.resolution_state in UNEXPANDABLE_STATES:
        return Expansion(reason=NOT_RESOLVED)
    if _is_a_film(entry, media_type):
        return Expansion(items=(ExpansionItem(None, entry.title_id, FIRST_POSITION),))
    if entry.unit_kind is UnitKind.EPISODES:
        return _from_a_span(entry, orders)
    if entry.unit_kind is UnitKind.SEASON:
        return _from_seasons(entry, orders)
    if entry.unit_kind is UnitKind.SERIES:
        return _from_a_whole_title(entry, orders)
    if entry.unit_kind is UnitKind.SPECIAL:
        return _from_one_matched_episode(entry, orders)
    return Expansion(note=UNSUPPORTED_KIND_NOTE.format(kind=entry.unit_kind.value), reason=UNSUPPORTED_KIND)


def _is_a_film(entry: CuratedEntry, media_type: MediaType | None) -> bool:
    """One slot, because the row says film - or because it says nothing and the title it found is one."""
    if entry.unit_kind is UnitKind.MOVIE:
        return True
    return media_type is MediaType.MOVIE and entry.unit_kind in FILM_SHAPED_KINDS


def _from_a_span(entry: CuratedEntry, orders: Sequence[EpisodeOrder]) -> Expansion:
    """An episode range: scanned over the numbering it names, or scoped by its season when it names none."""
    if entry.span_start is None or entry.span_end is None:
        return Expansion(note=NO_EPISODE_SPAN_NOTE, reason=NO_SPAN)
    if entry.order_type is None:
        # Ruling 30: a season-scoped range leaves the numbering unknown, so the season is the only thing
        # that can say which episodes it meant. Nothing else is guessed from it.
        return _within_a_season(entry, orders, entry.span_start, entry.span_end)
    return _within_an_ordering(entry, orders, entry.order_type, entry.span_start, entry.span_end)


def _within_an_ordering(
    entry: CuratedEntry, orders: Sequence[EpisodeOrder], order_type: str, start: int, end: int
) -> Expansion:
    ordering = _ordering(orders, order_type, entry.order_label)
    named = _named(order_type, entry.order_label)
    if not ordering:
        return Expansion(note=MISSING_ORDER_NOTE.format(order=named), reason=MISSING_ORDER)
    chosen = tuple(slot.episode_id for slot in ordering if start <= slot.sequence <= end)
    if not chosen:
        return Expansion(note=EMPTY_RANGE_NOTE.format(order=named, start=start, end=end), reason=EMPTY_RANGE)
    asked = end - start + 1
    if len(chosen) < asked:
        # The detectable half of rule 10's caveat: an ordering shorter than the span the curator counted.
        # The episodes it does hold are real, so they are kept - and the shortfall is said out loud.
        note = SHORT_COVER_NOTE.format(order=named, found=len(chosen), asked=asked)
        return Expansion(items=_items(chosen), note=note, reason=SHORT_COVER)
    return Expansion(items=_items(chosen))


def _within_a_season(entry: CuratedEntry, orders: Sequence[EpisodeOrder], start: int, end: int) -> Expansion:
    if entry.season_number is None:
        return Expansion(note=NO_SEASON_NOTE, reason=NO_SEASON)
    found = _season_run(orders, entry.season_number, start, end)
    if len(found) != end - start + 1:
        # Partial is refused rather than kept: a range whose numbering is unknown is either the
        # within-season reading or it is not, and half of it is a guess with a row number on it.
        note = SEASON_NOT_COVERED_NOTE.format(season=entry.season_number, start=start, end=end)
        return Expansion(note=note, reason=SEASON_NOT_COVERED)
    return Expansion(items=_items(found))


def _from_seasons(entry: CuratedEntry, orders: Sequence[EpisodeOrder]) -> Expansion:
    """A bare season, or a `Seasons A-B` range whose span holds SEASON numbers (Ruling 29)."""
    seasons = _season_numbers(entry)
    if not seasons:
        return Expansion(note=NO_SEASON_NAMED_NOTE, reason=NO_SPAN)
    found = _seasons_run(orders, seasons)
    if not found:
        named = ", ".join(str(season) for season in seasons)
        return Expansion(note=NO_SEASONS_FOUND_NOTE.format(seasons=named), reason=EMPTY_RANGE)
    return Expansion(items=_items(found))


def _from_a_whole_title(entry: CuratedEntry, orders: Sequence[EpisodeOrder]) -> Expansion:
    """A whole show in one row: every slot of the numbering it names, or of the aired rank when it
    names none. That is not the fallback the span rules refuse - a series row names no ordering at
    all, so there is nothing to fall back *from*, and the aired rank is what "the whole show" means."""
    order_type = AIRED_ORDER_TYPE if entry.order_type is None else entry.order_type
    label = NO_LABEL if entry.order_type is None else entry.order_label
    ordering = _ordering(orders, order_type, label)
    if not ordering:
        return Expansion(note=MISSING_ORDER_NOTE.format(order=_named(order_type, label)), reason=MISSING_ORDER)
    return Expansion(items=_items(tuple(slot.episode_id for slot in ordering)))


def _from_one_matched_episode(entry: CuratedEntry, orders: Sequence[EpisodeOrder]) -> Expansion:
    """An OVA or a TV special that a second pass matched inside its parent, at one `(season, episode)`.

    Its span is that one episode, written by `span_values` as `start == end == episode_number`. It is
    looked up by pair rather than by rank because a special usually lives in season 0, which the aired
    walk excludes and the specials bucket holds.
    """
    if entry.season_number is None or entry.span_start is None or entry.span_end is None:
        return Expansion(note=UNMATCHED_SPECIAL_NOTE, reason=NO_SPAN)
    return _within_a_season(entry, orders, entry.span_start, entry.span_end)


def _season_numbers(entry: CuratedEntry) -> tuple[int, ...]:
    """The seasons a season row names. A range first: `Seasons 1-25` carries no single season number."""
    if entry.span_start is not None and entry.span_end is not None:
        return tuple(range(entry.span_start, entry.span_end + 1))
    return () if entry.season_number is None else (entry.season_number,)


def _ordering(orders: Sequence[EpisodeOrder], order_type: str, label: str) -> tuple[EpisodeOrder, ...]:
    """One numbering's slots in its own rank order, whatever order the rows arrived in."""
    named = [slot for slot in orders if slot.order_type == order_type and slot.label == label]
    return tuple(sorted(named, key=lambda slot: slot.sequence))


def _own_slots(orders: Sequence[EpisodeOrder]) -> tuple[OwnSlot, ...]:
    """The slots keyed by TMDB's own `(season, episode)` pair - this app's aired rank and its specials.

    Narrowed to triples of real ints here, once, so nothing downstream carries a fallback for a half of a
    pair that this filter has already excluded.
    """
    return tuple(
        (slot.order_season_number, slot.order_episode_number, slot.episode_id)
        for slot in orders
        if (slot.order_type, slot.label) in OWN_ORDERINGS
        and slot.order_season_number is not None
        and slot.order_episode_number is not None
    )


def _season_run(orders: Sequence[EpisodeOrder], season_number: int, start: int, end: int) -> tuple[uuid.UUID, ...]:
    """Episodes `start..end` of one season, in episode-number order. At most one slot answers each pair."""
    found = {
        number: episode_id
        for season, number, episode_id in _own_slots(orders)
        if season == season_number and start <= number <= end
    }
    return tuple(found[number] for number in sorted(found))


def _seasons_run(orders: Sequence[EpisodeOrder], seasons: Sequence[int]) -> tuple[uuid.UUID, ...]:
    """Every episode of the named seasons, in `(season, episode)` order."""
    wanted = set(seasons)
    chosen = sorted((slot for slot in _own_slots(orders) if slot[0] in wanted), key=lambda slot: slot[:2])
    return tuple(episode_id for _, _, episode_id in chosen)


def _named(order_type: str, label: str) -> str:
    """How a refusal spells the ordering the row asked for, label included when it carries one."""
    return order_type if not label else _LABELLED_ORDER.format(order_type=order_type, label=label)


def _items(episode_ids: Iterable[uuid.UUID]) -> tuple[ExpansionItem, ...]:
    return tuple(
        ExpansionItem(episode_id=episode_id, movie_title_id=None, position_in_entry=position)
        for position, episode_id in enumerate(episode_ids, start=FIRST_POSITION)
    )


# ---------------------------------------------------------------------------------------------------
# The database half: delete, insert, renumber - all three inside the caller's transaction.
# ---------------------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Rebuild:
    """What one pass wrote, and the reasons the rows that wrote nothing gave."""

    rows: list[dict[str, object]] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)


async def rebuild_items(
    session: AsyncSession, category_id: uuid.UUID, entry_ids: Sequence[uuid.UUID] | None = None
) -> int:
    """Rebuild the queue for one category's live entries, delete-then-insert, and renumber the whole lot.

    `entry_ids` scopes the rebuild to the entries a pass actually moved; `None` rebuilds every live one.
    A scoped rebuild still clears the rows of anything soft-deleted, because a retired entry's items must
    leave the queue whether or not the caller listed it. Returns the number of rows written.
    """
    started = time.monotonic()
    entries = await _live_entries(session, category_id, entry_ids)
    title_ids = {entry.title_id for entry in entries if entry.title_id is not None}
    orders = await _orders_by_title(session, title_ids)
    kinds = await _media_types_by_title(session, title_ids)
    await _cleared(session, category_id, entry_ids)

    rebuild = _Rebuild()
    for entry in entries:
        expansion = expand_entry(entry, orders.get(entry.title_id, ()), kinds.get(entry.title_id))
        entry.resolution_note = noted(entry.resolution_note, expansion.note)
        if not expansion.items:
            rebuild.skipped[expansion.reason] += 1
        for item in expansion.items:
            rebuild.rows.append(_row(category_id, entry.id, item, len(rebuild.rows) + FIRST_POSITION))
    if rebuild.rows:
        await session.execute(insert(CuratedEntryItem), rebuild.rows)
    await renumber_absolute_positions(session, category_id)

    _LOGGER.info(
        "expansion_rebuilt job=%s category=%s scoped=%s entries=%d items=%d skipped=%d reasons=%s elapsed_ms=%d",
        _JOB,
        category_id,
        entry_ids is not None,
        len(entries),
        len(rebuild.rows),
        sum(rebuild.skipped.values()),
        _reasons(rebuild.skipped),
        int((time.monotonic() - started) * 1000),
    )
    return len(rebuild.rows)


async def renumber_absolute_positions(session: AsyncSession, category_id: uuid.UUID) -> None:
    """One UPDATE: `absolute_position` is the rank over `(entry.position, position_in_entry)`.

    Every row of the category is ranked, not only the ones a scoped rebuild rewrote, because a row left
    holding its old number is exactly what would collide with a row renumbering onto it. The deferred
    unique on `(category_id, absolute_position)` is what lets those duplicates exist mid-statement;
    `IS DISTINCT FROM` keeps the write to the rows whose rank actually moved.

    Liveness is not read here and must not be: `_cleared` has already dropped every row belonging to a
    soft-deleted entry, so what remains is the live queue. That is also why the rank is not filtered by
    `curated_entry.position` in any way - a retired entry is renumbered *behind* the live block rather
    than kept where it was, so its position is no more history than its row is.
    """
    ranked = (
        select(
            CuratedEntryItem.id.label("id"),
            func.row_number().over(order_by=(CuratedEntry.position, CuratedEntryItem.position_in_entry)).label("rank"),
        )
        .join(CuratedEntry, CuratedEntry.id == CuratedEntryItem.curated_entry_id)
        .where(CuratedEntryItem.category_id == category_id)
        .subquery()
    )
    await session.execute(
        update(CuratedEntryItem)
        .where(CuratedEntryItem.id == ranked.c.id, CuratedEntryItem.absolute_position.is_distinct_from(ranked.c.rank))
        .values(absolute_position=ranked.c.rank)
        .execution_options(synchronize_session=False)
    )


async def _live_entries(
    session: AsyncSession, category_id: uuid.UUID, entry_ids: Sequence[uuid.UUID] | None
) -> list[CuratedEntry]:
    statement = (
        select(CuratedEntry)
        .where(CuratedEntry.category_id == category_id, CuratedEntry.removed_at.is_(None))
        .order_by(CuratedEntry.position)
    )
    if entry_ids is not None:
        statement = statement.where(CuratedEntry.id.in_(entry_ids))
    return list(await session.scalars(statement))


async def _orders_by_title(
    session: AsyncSession, title_ids: set[uuid.UUID]
) -> Mapping[uuid.UUID, tuple[EpisodeOrder, ...]]:
    """Every numbering of every title these entries resolved to, read once rather than per row."""
    if not title_ids:
        return {}
    rows = await session.scalars(select(EpisodeOrder).where(EpisodeOrder.title_id.in_(title_ids)))
    grouped: dict[uuid.UUID, list[EpisodeOrder]] = {title_id: [] for title_id in title_ids}
    for row in rows:
        grouped[row.title_id].append(row)
    return {title_id: tuple(slots) for title_id, slots in grouped.items()}


async def _media_types_by_title(session: AsyncSession, title_ids: set[uuid.UUID]) -> Mapping[uuid.UUID, MediaType]:
    """Whether each resolved title is a film or a show - the one fact a span-less row needs to expand.

    Read here rather than through `CuratedEntry.title`, whose relationship is `lazy="raise_on_sql"`: a
    projection that loaded one title per row would be the N+1 that `raise_on_sql` exists to refuse.
    """
    if not title_ids:
        return {}
    rows = await session.execute(select(Title.id, Title.media_type).where(Title.id.in_(title_ids)))
    return {title_id: media_type for title_id, media_type in rows}


async def _cleared(session: AsyncSession, category_id: uuid.UUID, entry_ids: Sequence[uuid.UUID] | None) -> None:
    """Drop the rows this pass is about to rewrite, plus anything a soft-deleted entry still holds."""
    condition = CuratedEntryItem.category_id == category_id
    if entry_ids is not None:
        retired = select(CuratedEntry.id).where(
            CuratedEntry.category_id == category_id, CuratedEntry.removed_at.is_not(None)
        )
        condition = and_(
            condition,
            or_(CuratedEntryItem.curated_entry_id.in_(entry_ids), CuratedEntryItem.curated_entry_id.in_(retired)),
        )
    await session.execute(delete(CuratedEntryItem).where(condition).execution_options(synchronize_session=False))


def _row(category_id: uuid.UUID, entry_id: uuid.UUID, item: ExpansionItem, absolute_position: int) -> dict[str, object]:
    """One insert payload. `absolute_position` is provisional: the renumber settles it before commit."""
    return {
        "category_id": category_id,
        "curated_entry_id": entry_id,
        "episode_id": item.episode_id,
        "movie_title_id": item.movie_title_id,
        "position_in_entry": item.position_in_entry,
        "absolute_position": absolute_position,
    }


def _reasons(skipped: Counter[str]) -> str:
    """The skip breakdown as one log field. Every key is a code from this module's closed vocabulary."""
    return ",".join(f"{reason}={count}" for reason, count in sorted(skipped.items())) or "-"
