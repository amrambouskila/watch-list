"""Which file in the owner's Jellyfin answers each episode a curated row names.

**ORDER FIRST, JOIN SECOND** (CLAUDE.md section 20.2, item 3). The entry's span was already resolved in its
stored `order_type` when T24 built its queue, so this reads `curated_entry_item`, takes each slot's place in
*that* numbering from `episode_order`, and matches the pair against what Jellyfin reported. Nothing here
infers an ordering at read time, and nothing falls back to the aired rank.

The trap this module exists to avoid, stated once: TMDB numbers anime absolute-continuously inside season
buckets - One Piece's season 2 runs 62-77 - while a file on disk is named for the ordering the curator
watched in. A join taken straight off `episode.(season_number, episode_number)` is therefore right for
Western TV and silently wrong for anime, which is the worst failure shape available here. What the join uses
is `episode_order.order_season_number` / `order_episode_number` - the pair the UI prints - and never
`sequence`, which is the rank the app computes with (CLAUDE.md section 11.2, rules 9 and 11).

Three further rules govern every line:

1. **Series are located by provider id, never by name.** An anime carries a romaji name, an English name and
   a handful of synonyms, and a fuzzy match on any of them is a wrong file that plays silently. A title with
   no `tmdb_id`, or a library row with none, joins to nothing - which is an honest "not in library".
2. **`IndexNumberEnd` means one file covers a range**, so one `jellyfin_item` legitimately answers several
   `curated_entry_item` rows. That many-to-one is recorded on every row it touches, never collapsed to the
   first one.
3. **Three states, never two.** More than one live file answering one episode is `AMBIGUOUS`, and this join
   picks neither: settling that is the owner's, through `title.jellyfin_item_id` (T56). The pick is read here
   and never written - including when it has gone: a pick whose row was soft-deleted is *dangling*, and while
   any live candidate remains the entry is `AMBIGUOUS` again rather than silently transferring the match to
   the file the owner turned down (Ruling 98).

Two statements per page, whatever its length: one for the titles' library candidates, one for the join
itself. A lateral per slot is the exact cost `curated_entry_item` exists to avoid.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import groupby

from sqlalchemy import Row, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.data.enums import JellyfinItemKind
from tv_watchlist.data.models import CuratedEntry, CuratedEntryItem, EpisodeOrder, JellyfinItem
from tv_watchlist.ingest.episode_orders import NO_LABEL
from tv_watchlist.ingest.expansion import numberings_for
from tv_watchlist.services.episode_lookup import within_numberings
from tv_watchlist.services.library_selection import LibrarySelection
from tv_watchlist.services.library_selections import library_selections_for

#: One joined row: the slot, its place in the numbering that answered, and the file that did - or nulls
#: where either was absent, which is what the two outer joins exist to keep.
type SlotRow = Row[
    tuple[uuid.UUID, uuid.UUID, str | None, str | None, uuid.UUID | None, int | None, int | None, uuid.UUID]
]


class MatchState(StrEnum):
    """Three states, because two would have to lie about one of them.

    `AMBIGUOUS` is the library's real shape - an absolute-numbered rip beside an official one, a remux beside
    an encode - and folding it into `NOT_IN_LIBRARY` would hide a file the owner has, while folding it into
    `MATCHED` would pick one on their behalf. T51 maps these onto the availability the UI shows.
    """

    MATCHED = "matched"
    NOT_IN_LIBRARY = "not_in_library"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class EpisodeMatch:
    """One queue slot, the file that answers it, and the numbering the join used to say so.

    `order_type` leaves the service because the 10.3 acceptance line requires the order actually used to be
    visible in the UI. `jellyfin_item_id` is set only in `MATCHED`: in the other two states there is either
    no file or no single one, and a nullable id would not tell them apart.
    """

    item_id: uuid.UUID
    episode_id: uuid.UUID
    jellyfin_item_id: uuid.UUID | None
    state: MatchState
    covers_range: bool
    order_type: str | None
    order_label: str


async def episodes_for_entry(session: AsyncSession, entry: CuratedEntry) -> list[EpisodeMatch]:
    """Map each `curated_entry_item` episode slot of one entry to a `jellyfin_item` row, in queue order.

    A film's slot carries `movie_title_id` rather than an episode and is not this join's subject; T51 answers
    for those. An entry whose title, numbering or library rows are missing still reports one row per slot,
    because "this episode is not here" is a state the UI shows rather than an absence it has to infer.
    """
    return (await episodes_for_entries(session, [entry]))[entry.id]


async def episodes_for_entries(
    session: AsyncSession,
    entries: Sequence[CuratedEntry],
    *,
    selections: Mapping[uuid.UUID, LibrarySelection] | None = None,
) -> dict[uuid.UUID, list[EpisodeMatch]]:
    """Run the same numbering-aware join once for a page, optionally reusing its title lookup."""
    matches: dict[uuid.UUID, list[EpisodeMatch]] = {entry.id: [] for entry in entries}
    if not entries:
        return matches
    if selections is None:
        selections = await library_selections_for(session, {entry.title_id for entry in entries if entry.title_id})
    lookups = {entry.id: selections.get(entry.title_id, LibrarySelection()) for entry in entries}
    rows = await _slots_against_files(session, entries, lookups)
    for (_, item_id), group in groupby(rows, key=lambda row: (row.entry_id, row.item_id)):
        slot = tuple(group)
        lookup = lookups[slot[0].entry_id]
        settled = not (lookup.pick_dangling and lookup.series_ids)
        matches[slot[0].entry_id].append(_match(item_id, slot, settled=settled))
    return matches


async def _slots_against_files(
    session: AsyncSession, entries: Sequence[CuratedEntry], lookups: Mapping[uuid.UUID, LibrarySelection]
) -> Sequence[SlotRow]:
    """One row per slot, times the live files answering it - so a slot with none, and a slot with two, both show.

    Both joins are outer: a slot whose numbering has gone, and an episode the library does not hold, are
    states this service reports rather than rows it drops.
    """
    statement = (
        select(
            CuratedEntryItem.id.label("item_id"),
            CuratedEntryItem.episode_id.label("episode_id"),
            EpisodeOrder.order_type,
            EpisodeOrder.label,
            JellyfinItem.id.label("file_id"),
            JellyfinItem.index_number,
            JellyfinItem.index_number_end,
            CuratedEntryItem.curated_entry_id.label("entry_id"),
        )
        .select_from(CuratedEntryItem)
        .outerjoin(
            EpisodeOrder,
            and_(
                EpisodeOrder.episode_id == CuratedEntryItem.episode_id,
                or_(
                    *(
                        and_(
                            CuratedEntryItem.curated_entry_id == entry.id,
                            within_numberings(numberings_for(entry)),
                        )
                        for entry in entries
                    )
                ),
            ),
        )
        .outerjoin(
            JellyfinItem,
            and_(
                JellyfinItem.kind == JellyfinItemKind.EPISODE,
                or_(
                    *(
                        and_(
                            CuratedEntryItem.curated_entry_id == entry.id,
                            JellyfinItem.series_jellyfin_id.in_(lookups[entry.id].series_ids),
                        )
                        for entry in entries
                    )
                ),
                JellyfinItem.removed_at.is_(None),
                # The pair the ordering prints, against the numbers the file naming produced. A file
                # declaring `IndexNumberEnd` covers the whole run, so it answers for every episode in it.
                JellyfinItem.parent_index_number == EpisodeOrder.order_season_number,
                JellyfinItem.index_number <= EpisodeOrder.order_episode_number,
                func.coalesce(JellyfinItem.index_number_end, JellyfinItem.index_number)
                >= EpisodeOrder.order_episode_number,
            ),
        )
        .where(
            CuratedEntryItem.curated_entry_id.in_([entry.id for entry in entries]),
            CuratedEntryItem.episode_id.is_not(None),
        )
        .order_by(CuratedEntryItem.curated_entry_id, CuratedEntryItem.position_in_entry, JellyfinItem.id)
    )
    return (await session.execute(statement)).all()


def _match(item_id: uuid.UUID, group: Sequence[SlotRow], *, settled: bool) -> EpisodeMatch:
    """One slot's verdict, read off the files that answered it. Two answers is a state, not a choice.

    `settled` is false for every slot of an entry whose pick has gone while candidates remain: the owner
    turned one of those files down and this join will not quietly pick another for them (Ruling 98).
    """
    first = group[0]
    files = [row for row in group if row.file_id is not None]
    order_label = NO_LABEL if first.label is None else first.label
    if not settled:
        return EpisodeMatch(item_id, first.episode_id, None, MatchState.AMBIGUOUS, False, first.order_type, order_label)
    if len(files) != 1:
        state = MatchState.NOT_IN_LIBRARY if not files else MatchState.AMBIGUOUS
        return EpisodeMatch(item_id, first.episode_id, None, state, False, first.order_type, order_label)
    found = files[0]
    return EpisodeMatch(
        item_id,
        first.episode_id,
        found.file_id,
        MatchState.MATCHED,
        _covers_range(found.index_number, found.index_number_end),
        first.order_type,
        order_label,
    )


def _covers_range(index_number: int | None, index_number_end: int | None) -> bool:
    """Whether this one file holds several episodes, which is what `IndexNumberEnd` says when it is there."""
    return index_number is not None and index_number_end is not None and index_number_end > index_number
