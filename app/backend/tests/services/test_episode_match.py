"""The episode join: which file in the owner's Jellyfin answers each episode a curated row names.

The test this file exists for is the first one. TMDB numbers anime absolute-continuously inside season
buckets - One Piece's season 2 runs 62-77 - while the file on disk is named for the ordering the curator
watched in, so a join taken straight off `episode.(season_number, episode_number)` is right for Western TV
and silently wrong for anime. That test seeds a decoy at TMDB's own pair and proves the naive join lands on
it while this one does not, so it cannot pass by accident.

The database is real, the provider bodies are recorded, and the Jellyfin rows are the hand-authored shapes
under `tests/fixtures/jellyfin/`. No socket is opened here (CLAUDE.md section 16.4).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from typing import Final

import pytest
from episode_join_support import (
    A_FIRST_SEASON,
    SPECIALS_SEASON,
    a_category,
    a_film,
    a_second_numbering,
    a_series_file,
    a_show,
    an_entry,
    an_episode_file,
    file_id,
    files_from_fixture,
    fixture_series_id,
    one_piece_with_its_orderings,
)
from ingest_support import ONE_PIECE, THEIR_ABSOLUTE
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from statement_support import counted_statements
from tv_watchlist.clock import utcnow
from tv_watchlist.constants import SPECIALS_ORDER_LABEL
from tv_watchlist.data.enums import ExternalSource, OrderType, ResolutionState, UnitKind
from tv_watchlist.data.models import Category, CuratedEntry, CuratedEntryItem, Episode, EpisodeOrder, JellyfinItem
from tv_watchlist.ingest.episode_orders import AIRED_ORDER_TYPE, NO_LABEL
from tv_watchlist.ingest.expansion import OWN_ORDERINGS, expand_entry, numberings_for, rebuild_items
from tv_watchlist.services.episode_match import EpisodeMatch, MatchState, episodes_for_entries, episodes_for_entry

#: One Piece's second episode span, the reference row this project measures everything against.
REFERENCE_SPAN: Final[tuple[int, int]] = (19, 53)
REFERENCE_SPAN_LENGTH: Final[int] = 35
#: A span inside TMDB's season 2, where the bucket numbering and the absolute numbering part company.
SEASON_TWO_SPAN: Final[tuple[int, int]] = (62, 64)
SEASON_TWO_SPAN_LENGTH: Final[int] = 3
#: What TheTVDB's absolute ordering calls the season those episodes sit in, which is not what TMDB calls it.
ABSOLUTE_SEASON: Final[int] = 1
TMDB_SEASON_TWO: Final[int] = 2
A_DECOY_ID: Final[str] = "dddddddddddddddddddddddddddddd01"
#: A provider ordering over the same episodes at a different printed pair - what a stray `order_type`
#: on a season row would send the join looking under, if anything let it (Ruling 97).
A_PROVIDER_ORDER: Final[str] = "dvd"
AN_ALTERNATE_SEASON: Final[int] = 5
AN_ALTERNATE_FIRST: Final[int] = 40
A_TITLE: Final[uuid.UUID] = uuid.UUID("11111111-1111-4111-8111-111111111111")

A_TMDB_ID: Final[int] = 4_242
ANOTHER_TMDB_ID: Final[int] = 4_243
A_SERIES_ID: Final[str] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01"
ANOTHER_SERIES_ID: Final[str] = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb02"
A_SECOND_FILE_ID: Final[str] = "cccccccccccccccccccccccccccccc03"

A_FEW_EPISODES: Final[int] = 3
A_FEW_SPECIALS: Final[int] = 2
#: The fixture's three files: `S01E01`, `S01E02`, and one covering `E03-E04`.
FIXTURE_EPISODES: Final[int] = 4
FIRST: Final[int] = 1
#: One series lookup, then one join over the whole entry - whatever the entry's length.
STATEMENTS_PER_ENTRY: Final[int] = 2
#: Nothing in this path may compare a name. These are the ways SQL says it.
NAME_MATCHING: Final[tuple[str, ...]] = ("ilike", "similarity", "like", "lower(", "jellyfin_item.name")


@pytest.fixture
def join_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    """Every statement the engine issues, so a join that grew a second query shows up as a number."""
    with counted_statements(engine) as seen:
        yield seen


async def _items_in_order(session: AsyncSession, entry: CuratedEntry) -> list[CuratedEntryItem]:
    rows = await session.scalars(
        select(CuratedEntryItem)
        .where(CuratedEntryItem.curated_entry_id == entry.id)
        .order_by(CuratedEntryItem.position_in_entry)
    )
    return list(rows)


async def _naive_join(session: AsyncSession, series_id: str, matches: Sequence[EpisodeMatch]) -> set[uuid.UUID]:
    """The join this task exists to refuse: TMDB's own `(season, episode)` pair against Jellyfin's numbers."""
    pairs = (
        await session.execute(
            select(Episode.season_number, Episode.episode_number).where(
                Episode.id.in_([match.episode_id for match in matches])
            )
        )
    ).all()
    found = await session.scalars(
        select(JellyfinItem.id).where(
            JellyfinItem.series_jellyfin_id == series_id,
            or_(
                *(
                    and_(JellyfinItem.parent_index_number == season, JellyfinItem.index_number == number)
                    for season, number in pairs
                )
            ),
        )
    )
    return set(found)


async def _a_show_in_the_library(
    session: AsyncSession, *, episodes: int = A_FEW_EPISODES, specials: int = 0
) -> tuple[Category, CuratedEntry]:
    """A synthetic show, its series row, and a season entry over it - the shape most of these tests want."""
    title = await a_show(session, "A Show", episodes=episodes, specials=specials, tmdb_id=A_TMDB_ID)
    await a_series_file(session, jellyfin_id=A_SERIES_ID, name="A Show", tmdb_id=A_TMDB_ID)
    category = await a_category(session)
    entry = await an_entry(
        session, category, title_id=title.id, unit_kind=UnitKind.SEASON, season_number=A_FIRST_SEASON
    )
    await rebuild_items(session, category.id)
    return category, entry


async def test_an_anime_span_joins_on_the_stored_order_not_on_tmdb_season_and_episode(
    db_session: AsyncSession,
) -> None:
    """ORDER FIRST, JOIN SECOND: the file is found under `absolute`, and TMDB's own pair finds the decoy."""
    title = await one_piece_with_its_orderings(db_session)
    category = await a_category(db_session, "one-piece")
    start, end = SEASON_TWO_SPAN
    entry = await an_entry(
        db_session,
        category,
        title_id=title.id,
        unit_kind=UnitKind.EPISODES,
        order_type=THEIR_ABSOLUTE,
        span_start=start,
        span_end=end,
    )
    await rebuild_items(db_session, category.id)
    series_id = fixture_series_id()
    await a_series_file(db_session, jellyfin_id=series_id, name="One Piece", tmdb_id=ONE_PIECE)
    numbered = [
        await an_episode_file(db_session, series_jellyfin_id=series_id, season=ABSOLUTE_SEASON, number=number)
        for number in range(start, end + 1)
    ]
    decoy = await an_episode_file(
        db_session, series_jellyfin_id=series_id, season=TMDB_SEASON_TWO, number=start, jellyfin_id=A_DECOY_ID
    )

    matches = await episodes_for_entry(db_session, entry)

    assert len(matches) == SEASON_TWO_SPAN_LENGTH
    assert [match.state for match in matches] == [MatchState.MATCHED] * SEASON_TWO_SPAN_LENGTH
    assert [match.jellyfin_item_id for match in matches] == [file.id for file in numbered]
    assert decoy.id not in {match.jellyfin_item_id for match in matches}
    # The order actually used is the entry's own, not the derived default - the 10.3 acceptance line, and
    # the case it is load-bearing in. A report of `aired` here would be a lie the UI would repeat.
    assert [(match.order_type, match.order_label) for match in matches] == [
        (THEIR_ABSOLUTE, NO_LABEL)
    ] * SEASON_TWO_SPAN_LENGTH
    # The same three episodes, joined the naive way, land somewhere else entirely.
    assert await _naive_join(db_session, series_id, matches) == {decoy.id}


async def test_every_slot_of_the_reference_span_matches_its_own_file(db_session: AsyncSession) -> None:
    """All 35 rows of One Piece's `E19-53`, against a library holding each episode as its own file."""
    title = await one_piece_with_its_orderings(db_session)
    category = await a_category(db_session, "one-piece")
    start, end = REFERENCE_SPAN
    entry = await an_entry(
        db_session,
        category,
        title_id=title.id,
        unit_kind=UnitKind.EPISODES,
        order_type=THEIR_ABSOLUTE,
        span_start=start,
        span_end=end,
    )
    await rebuild_items(db_session, category.id)
    series_id = fixture_series_id()
    await a_series_file(db_session, jellyfin_id=series_id, name="One Piece", tmdb_id=ONE_PIECE)
    files = {
        file.id: file.jellyfin_id
        for file in [
            await an_episode_file(db_session, series_jellyfin_id=series_id, season=ABSOLUTE_SEASON, number=number)
            for number in range(start, end + 1)
        ]
    }

    matches = await episodes_for_entry(db_session, entry)

    items = await _items_in_order(db_session, entry)
    assert len(matches) == REFERENCE_SPAN_LENGTH
    assert [(match.item_id, files[match.jellyfin_item_id]) for match in matches] == [
        (item.id, file_id(number)) for item, number in zip(items, range(start, end + 1), strict=True)
    ]
    assert not any(match.covers_range for match in matches)
    assert {(match.order_type, match.order_label) for match in matches} == {(THEIR_ABSOLUTE, NO_LABEL)}


async def test_the_order_actually_used_is_reported(db_session: AsyncSession) -> None:
    """The acceptance line: the numbering the join used leaves the service, because the UI has to show it."""
    _, entry = await _a_show_in_the_library(db_session)
    await an_episode_file(db_session, series_jellyfin_id=A_SERIES_ID, season=A_FIRST_SEASON, number=FIRST)

    matches = await episodes_for_entry(db_session, entry)

    assert [(match.order_type, match.order_label) for match in matches] == [
        (AIRED_ORDER_TYPE, NO_LABEL)
    ] * A_FEW_EPISODES


async def test_a_specials_entry_joins_under_the_specials_label_not_the_aired_walk(db_session: AsyncSession) -> None:
    """Season 0 is a numbering of its own, so its slots meet the `S00` files and never the aired walk's."""
    title = await a_show(db_session, "A Show", episodes=A_FEW_EPISODES, specials=A_FEW_SPECIALS, tmdb_id=A_TMDB_ID)
    await a_series_file(db_session, jellyfin_id=A_SERIES_ID, name="A Show", tmdb_id=A_TMDB_ID)
    category = await a_category(db_session)
    entry = await an_entry(
        db_session, category, title_id=title.id, unit_kind=UnitKind.SEASON, season_number=SPECIALS_SEASON
    )
    await rebuild_items(db_session, category.id)
    specials = [
        await an_episode_file(db_session, series_jellyfin_id=A_SERIES_ID, season=SPECIALS_SEASON, number=number)
        for number in range(1, A_FEW_SPECIALS + 1)
    ]
    regular = [
        await an_episode_file(
            db_session,
            series_jellyfin_id=A_SERIES_ID,
            season=A_FIRST_SEASON,
            number=number,
            jellyfin_id=f"{A_SECOND_FILE_ID[:-2]}{number:02d}",
        )
        for number in range(1, A_FEW_SPECIALS + 1)
    ]

    matches = await episodes_for_entry(db_session, entry)

    assert [match.jellyfin_item_id for match in matches] == [file.id for file in specials]
    assert not {match.jellyfin_item_id for match in matches} & {file.id for file in regular}
    assert {(match.order_type, match.order_label) for match in matches} == {
        (OrderType.ALTERNATE.value, SPECIALS_ORDER_LABEL)
    }


async def test_index_number_end_lets_one_file_answer_for_several_rows(db_session: AsyncSession) -> None:
    """A file named `S01E03-E04` holds two episodes, so it answers two queue rows - recorded, never collapsed."""
    title = await a_show(db_session, "One Piece", episodes=FIXTURE_EPISODES, tmdb_id=A_TMDB_ID)
    series_id = fixture_series_id()
    await a_series_file(db_session, jellyfin_id=series_id, name="One Piece", tmdb_id=A_TMDB_ID)
    files = await files_from_fixture(db_session, series_jellyfin_id=series_id)
    category = await a_category(db_session)
    entry = await an_entry(
        db_session, category, title_id=title.id, unit_kind=UnitKind.SEASON, season_number=A_FIRST_SEASON
    )
    await rebuild_items(db_session, category.id)

    matches = await episodes_for_entry(db_session, entry)

    covering = files[-1]
    assert [match.jellyfin_item_id for match in matches] == [files[0].id, files[1].id, covering.id, covering.id]
    assert [match.covers_range for match in matches] == [False, False, True, True]
    assert [match.state for match in matches] == [MatchState.MATCHED] * FIXTURE_EPISODES


async def test_an_episode_with_no_jellyfin_row_reports_none_rather_than_guessing(db_session: AsyncSession) -> None:
    """The middle episode is missing from the library, which is a state - not a nearby file."""
    _, entry = await _a_show_in_the_library(db_session)
    for number in (1, 3):
        await an_episode_file(db_session, series_jellyfin_id=A_SERIES_ID, season=A_FIRST_SEASON, number=number)

    matches = await episodes_for_entry(db_session, entry)

    assert [match.state for match in matches] == [MatchState.MATCHED, MatchState.NOT_IN_LIBRARY, MatchState.MATCHED]
    assert matches[1].jellyfin_item_id is None
    assert matches[1].covers_range is False


async def test_two_live_files_for_one_episode_report_ambiguous_and_pick_neither(db_session: AsyncSession) -> None:
    """A remux beside an encode is the library's real shape; choosing one of them is T56's, never this join's."""
    _, entry = await _a_show_in_the_library(db_session)
    await an_episode_file(db_session, series_jellyfin_id=A_SERIES_ID, season=A_FIRST_SEASON, number=FIRST)
    await an_episode_file(
        db_session, series_jellyfin_id=A_SERIES_ID, season=A_FIRST_SEASON, number=FIRST, jellyfin_id=A_SECOND_FILE_ID
    )

    matches = await episodes_for_entry(db_session, entry)

    assert matches[0].state is MatchState.AMBIGUOUS
    assert matches[0].jellyfin_item_id is None


async def test_a_file_that_has_left_the_library_does_not_match(db_session: AsyncSession) -> None:
    """`removed_at` is a mark, not a delete - and a marked row answers nothing."""
    _, entry = await _a_show_in_the_library(db_session)
    await an_episode_file(
        db_session, series_jellyfin_id=A_SERIES_ID, season=A_FIRST_SEASON, number=FIRST, removed_at=utcnow()
    )

    matches = await episodes_for_entry(db_session, entry)

    assert matches[0].state is MatchState.NOT_IN_LIBRARY
    assert matches[0].jellyfin_item_id is None


async def test_the_owners_pick_settles_which_series_the_files_come_from(db_session: AsyncSession) -> None:
    """Two library entries for one show is exactly what `title.jellyfin_item_id` exists to settle (T56)."""
    title = await a_show(db_session, "A Show", episodes=A_FEW_EPISODES, tmdb_id=A_TMDB_ID)
    await a_series_file(db_session, jellyfin_id=A_SERIES_ID, name="A Show", tmdb_id=A_TMDB_ID)
    picked = await a_series_file(db_session, jellyfin_id=ANOTHER_SERIES_ID, name="A Show (1080p)", tmdb_id=A_TMDB_ID)
    category = await a_category(db_session)
    entry = await an_entry(
        db_session, category, title_id=title.id, unit_kind=UnitKind.SEASON, season_number=A_FIRST_SEASON
    )
    await rebuild_items(db_session, category.id)
    await an_episode_file(db_session, series_jellyfin_id=A_SERIES_ID, season=A_FIRST_SEASON, number=FIRST)
    wanted = await an_episode_file(
        db_session,
        series_jellyfin_id=ANOTHER_SERIES_ID,
        season=A_FIRST_SEASON,
        number=FIRST,
        jellyfin_id=A_SECOND_FILE_ID,
    )

    undecided = await episodes_for_entry(db_session, entry)
    title.jellyfin_item_id = picked.id
    await db_session.flush()
    decided = await episodes_for_entry(db_session, entry)

    assert undecided[0].state is MatchState.AMBIGUOUS
    assert decided[0].state is MatchState.MATCHED
    assert decided[0].jellyfin_item_id == wanted.id


async def test_a_pick_naming_one_file_settles_that_files_whole_series(db_session: AsyncSession) -> None:
    """A pick may name an episode rather than a series; the series it belongs to is what it settles."""
    title = await a_show(db_session, "A Show", episodes=A_FEW_EPISODES, tmdb_id=A_TMDB_ID)
    await a_series_file(db_session, jellyfin_id=A_SERIES_ID, name="A Show", tmdb_id=A_TMDB_ID)
    await a_series_file(db_session, jellyfin_id=ANOTHER_SERIES_ID, name="A Show (1080p)", tmdb_id=A_TMDB_ID)
    category = await a_category(db_session)
    entry = await an_entry(
        db_session, category, title_id=title.id, unit_kind=UnitKind.SEASON, season_number=A_FIRST_SEASON
    )
    await rebuild_items(db_session, category.id)
    await an_episode_file(db_session, series_jellyfin_id=A_SERIES_ID, season=A_FIRST_SEASON, number=FIRST)
    wanted = await an_episode_file(
        db_session,
        series_jellyfin_id=ANOTHER_SERIES_ID,
        season=A_FIRST_SEASON,
        number=FIRST,
        jellyfin_id=A_SECOND_FILE_ID,
    )
    title.jellyfin_item_id = wanted.id
    await db_session.flush()

    matches = await episodes_for_entry(db_session, entry)

    assert matches[0].state is MatchState.MATCHED
    assert matches[0].jellyfin_item_id == wanted.id


async def test_a_series_carrying_the_same_name_but_no_tmdb_id_is_not_in_the_library(db_session: AsyncSession) -> None:
    """The negative proof of the 10.3 line: the name is identical and the join still answers nothing."""
    title = await a_show(db_session, "A Show", episodes=A_FEW_EPISODES, tmdb_id=A_TMDB_ID)
    await a_series_file(db_session, jellyfin_id=A_SERIES_ID, name=title.name, tmdb_id=None)
    await a_series_file(db_session, jellyfin_id=ANOTHER_SERIES_ID, name=title.name, tmdb_id=ANOTHER_TMDB_ID)
    category = await a_category(db_session)
    entry = await an_entry(
        db_session, category, title_id=title.id, unit_kind=UnitKind.SEASON, season_number=A_FIRST_SEASON
    )
    await rebuild_items(db_session, category.id)
    for series_id in (A_SERIES_ID, ANOTHER_SERIES_ID):
        await an_episode_file(
            db_session,
            series_jellyfin_id=series_id,
            season=A_FIRST_SEASON,
            number=FIRST,
            jellyfin_id=f"{series_id[:-2]}f1",
        )

    matches = await episodes_for_entry(db_session, entry)

    assert {match.state for match in matches} == {MatchState.NOT_IN_LIBRARY}
    assert {match.jellyfin_item_id for match in matches} == {None}


async def test_no_query_in_this_path_matches_a_series_by_name(
    db_session: AsyncSession, join_statements: list[str]
) -> None:
    """A statement tap, because "never fuzzy" is a property of the SQL rather than of one assertion."""
    _, entry = await _a_show_in_the_library(db_session)
    await an_episode_file(db_session, series_jellyfin_id=A_SERIES_ID, season=A_FIRST_SEASON, number=FIRST)
    join_statements.clear()

    await episodes_for_entry(db_session, entry)

    issued = " ".join(statement.lower() for statement in join_statements)
    assert join_statements
    assert not [fragment for fragment in NAME_MATCHING if fragment in issued]


async def test_a_movie_entrys_slot_is_not_an_episode_match(db_session: AsyncSession) -> None:
    """A film's queue row carries `movie_title_id`, not an episode; it belongs to T51, not to this join."""
    film = await a_film(db_session, "A Film", tmdb_id=A_TMDB_ID)
    category = await a_category(db_session)
    entry = await an_entry(db_session, category, title_id=film.id, unit_kind=UnitKind.MOVIE)
    await rebuild_items(db_session, category.id)

    matches = await episodes_for_entry(db_session, entry)

    assert await _items_in_order(db_session, entry) != []
    assert matches == []


async def test_a_slot_whose_numbering_has_gone_reports_no_order_and_no_file(db_session: AsyncSession) -> None:
    """The queue is a cache: a re-ingest can leave a row whose numbering is no longer there, and that is honest."""
    _, entry = await _a_show_in_the_library(db_session)
    await an_episode_file(db_session, series_jellyfin_id=A_SERIES_ID, season=A_FIRST_SEASON, number=FIRST)
    await db_session.execute(delete(EpisodeOrder).where(EpisodeOrder.title_id == entry.title_id))

    matches = await episodes_for_entry(db_session, entry)

    assert {match.state for match in matches} == {MatchState.NOT_IN_LIBRARY}
    assert {(match.order_type, match.order_label) for match in matches} == {(None, NO_LABEL)}


async def test_the_statement_count_does_not_grow_with_the_entry(
    db_session: AsyncSession, join_statements: list[str]
) -> None:
    """One slot and thirty-five cost the same two statements: a lateral per row is what the queue avoids."""
    category, short = await _a_show_in_the_library(db_session, episodes=FIRST)
    title = await a_show(db_session, "A Long Show", episodes=REFERENCE_SPAN_LENGTH, tmdb_id=ANOTHER_TMDB_ID)
    await a_series_file(db_session, jellyfin_id=ANOTHER_SERIES_ID, name="A Long Show", tmdb_id=ANOTHER_TMDB_ID)
    long = await an_entry(
        db_session,
        category,
        title_id=title.id,
        unit_kind=UnitKind.SEASON,
        season_number=A_FIRST_SEASON,
        position=2,
    )
    await rebuild_items(db_session, category.id)

    join_statements.clear()
    assert len(await episodes_for_entry(db_session, short)) == FIRST
    one_slot = len(join_statements)
    join_statements.clear()
    assert len(await episodes_for_entry(db_session, long)) == REFERENCE_SPAN_LENGTH

    assert (one_slot, len(join_statements)) == (STATEMENTS_PER_ENTRY, STATEMENTS_PER_ENTRY)


# -- Ruling 97: the numbering is decided once, in expansion, and the join reads that decision ---------


def _ordering_row(
    episode_id: uuid.UUID, order_type: str, label: str, sequence: int, season: int, number: int
) -> EpisodeOrder:
    """One `episode_order` row as `expand_entry` reads it: detached, never flushed."""
    return EpisodeOrder(
        id=uuid.uuid4(),
        title_id=A_TITLE,
        episode_id=episode_id,
        order_type=order_type,
        label=label,
        sequence=sequence,
        order_season_number=season,
        order_episode_number=number,
        source=ExternalSource.TMDB,
    )


def _every_numbering() -> tuple[EpisodeOrder, ...]:
    """A title carrying all three: the aired walk, the specials bucket, and a provider ordering that
    prints a different `(season, episode)` pair for the very same episodes."""
    regular = [uuid.uuid4() for _ in range(A_FEW_EPISODES)]
    specials = [uuid.uuid4() for _ in range(A_FEW_SPECIALS)]
    return (
        *(
            _ordering_row(episode_id, AIRED_ORDER_TYPE, NO_LABEL, rank, A_FIRST_SEASON, rank)
            for rank, episode_id in enumerate(regular, start=1)
        ),
        *(
            _ordering_row(episode_id, OrderType.ALTERNATE.value, SPECIALS_ORDER_LABEL, rank, SPECIALS_SEASON, rank)
            for rank, episode_id in enumerate(specials, start=1)
        ),
        *(
            _ordering_row(episode_id, A_PROVIDER_ORDER, NO_LABEL, rank, AN_ALTERNATE_SEASON, AN_ALTERNATE_FIRST + rank)
            for rank, episode_id in enumerate(regular, start=1)
        ),
    )


def _an_entry(unit_kind: UnitKind, **fields: object) -> CuratedEntry:
    """One entry as the reconciler leaves it, detached - every column default spelled out."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "category_id": uuid.uuid4(),
        "position": 1,
        "title_id": A_TITLE,
        "unit_kind": unit_kind,
        "order_type": None,
        "order_label": NO_LABEL,
        "span_start": None,
        "span_end": None,
        "season_number": None,
        "resolution_state": ResolutionState.AUTO,
        "raw_cells": {},
    }
    return CuratedEntry(**{**defaults, **fields})


#: One case per `UnitKind`: the entry, the numbering the shared function must name, and whether that kind
#: puts episodes in the queue at all. A stray `order_type` sits on the two kinds that must ignore it.
NUMBERING_CASES: Final[tuple[tuple[UnitKind, dict[str, object], tuple[tuple[str, str], ...], bool], ...]] = (
    (
        UnitKind.EPISODES,
        {"order_type": A_PROVIDER_ORDER, "span_start": 1, "span_end": 3},
        ((A_PROVIDER_ORDER, ""),),
        True,
    ),
    (UnitKind.EPISODES, {"season_number": A_FIRST_SEASON, "span_start": 1, "span_end": 3}, OWN_ORDERINGS, True),
    (UnitKind.SEASON, {"season_number": A_FIRST_SEASON, "order_type": A_PROVIDER_ORDER}, OWN_ORDERINGS, True),
    (
        UnitKind.SPECIAL,
        {"season_number": SPECIALS_SEASON, "span_start": 1, "span_end": 1, "order_type": A_PROVIDER_ORDER},
        OWN_ORDERINGS,
        True,
    ),
    (UnitKind.SERIES, {}, ((AIRED_ORDER_TYPE, NO_LABEL),), True),
    (UnitKind.SERIES, {"order_type": A_PROVIDER_ORDER}, ((A_PROVIDER_ORDER, ""),), True),
    (UnitKind.MOVIE, {}, OWN_ORDERINGS, False),
    (UnitKind.UNKNOWN, {}, OWN_ORDERINGS, False),
)


@pytest.mark.parametrize(("unit_kind", "fields", "expected", "expands_episodes"), NUMBERING_CASES)
def test_the_shared_numbering_agrees_with_what_expansion_actually_expanded(
    unit_kind: UnitKind, fields: dict[str, object], expected: tuple[tuple[str, str], ...], expands_episodes: bool
) -> None:
    """Ruling 97: one dispatch, read by both sides, so the join cannot address a numbering the queue was
    not built over. Every kind is walked, because the two that ignore `order_type` are exactly the two a
    second copy of the rule got wrong - and a stray `order_type` reaches them through a correction."""
    orders = _every_numbering()
    entry = _an_entry(unit_kind, **fields)

    numberings = numberings_for(entry)
    expansion = expand_entry(entry, orders)

    assert numberings == expected
    episodes = [item.episode_id for item in expansion.items if item.episode_id is not None]
    assert bool(episodes) is expands_episodes
    addressable = {order.episode_id for order in orders if (order.order_type, order.label) in numberings}
    # Every episode the queue really holds is reachable under the numbering the join will use.
    assert set(episodes) <= addressable


async def test_a_season_entry_ignores_a_stray_order_type_and_joins_where_the_queue_was_built(
    db_session: AsyncSession,
) -> None:
    """A correction may set `order_type` on a season row (`resolution_review._corrected` does, without
    touching `unit_kind`), but `_from_seasons` never reads it. The join must not either."""
    title = await a_show(db_session, "A Show", episodes=A_FEW_EPISODES, tmdb_id=A_TMDB_ID)
    await a_second_numbering(
        db_session,
        title,
        order_type=A_PROVIDER_ORDER,
        season_number=AN_ALTERNATE_SEASON,
        first_number=AN_ALTERNATE_FIRST,
    )
    await a_series_file(db_session, jellyfin_id=A_SERIES_ID, name="A Show", tmdb_id=A_TMDB_ID)
    category = await a_category(db_session)
    entry = await an_entry(
        db_session,
        category,
        title_id=title.id,
        unit_kind=UnitKind.SEASON,
        season_number=A_FIRST_SEASON,
        order_type=A_PROVIDER_ORDER,
    )
    await rebuild_items(db_session, category.id)
    native = [
        await an_episode_file(db_session, series_jellyfin_id=A_SERIES_ID, season=A_FIRST_SEASON, number=number)
        for number in range(1, A_FEW_EPISODES + 1)
    ]
    decoy = await an_episode_file(
        db_session,
        series_jellyfin_id=A_SERIES_ID,
        season=AN_ALTERNATE_SEASON,
        number=AN_ALTERNATE_FIRST + 1,
        jellyfin_id=A_DECOY_ID,
    )

    matches = await episodes_for_entry(db_session, entry)

    assert [match.state for match in matches] == [MatchState.MATCHED] * A_FEW_EPISODES
    assert [match.jellyfin_item_id for match in matches] == [file.id for file in native]
    assert decoy.id not in {match.jellyfin_item_id for match in matches}
    # The order reported is the one the join really used, which for a season row is never the stray.
    assert {(match.order_type, match.order_label) for match in matches} == {(AIRED_ORDER_TYPE, NO_LABEL)}


# -- Ruling 98: a pick that has gone is asked again, never transferred --------------------------------


async def _a_title_the_library_holds_twice(
    db_session: AsyncSession, *, candidates: int
) -> tuple[CuratedEntry, list[JellyfinItem], list[JellyfinItem]]:
    """One show, several library entries for it, one episode file in each - the shape T56 exists to settle."""
    title = await a_show(db_session, "A Show", episodes=FIRST, tmdb_id=A_TMDB_ID)
    series = [
        await a_series_file(db_session, jellyfin_id=f"{A_SERIES_ID[:-2]}{index:02d}", name="A Show", tmdb_id=A_TMDB_ID)
        for index in range(1, candidates + 1)
    ]
    category = await a_category(db_session)
    entry = await an_entry(
        db_session, category, title_id=title.id, unit_kind=UnitKind.SEASON, season_number=A_FIRST_SEASON
    )
    await rebuild_items(db_session, category.id)
    files = [
        await an_episode_file(
            db_session,
            series_jellyfin_id=row.jellyfin_id,
            season=A_FIRST_SEASON,
            number=FIRST,
            jellyfin_id=f"{A_SECOND_FILE_ID[:-2]}{index:02d}",
        )
        for index, row in enumerate(series, start=1)
    ]
    title.jellyfin_item_id = series[0].id
    await db_session.flush()
    return entry, series, files


@pytest.mark.parametrize("candidates", [2, 3])
async def test_a_dangling_pick_asks_again_rather_than_matching_the_file_the_owner_turned_down(
    db_session: AsyncSession, candidates: int
) -> None:
    """A soft delete is an UPDATE, so `ON DELETE SET NULL` never fires and the pick is left dangling.
    Pinned at two candidates - where the survivor used to be handed a MATCHED - and at three."""
    entry, series, files = await _a_title_the_library_holds_twice(db_session, candidates=candidates)

    decided = await episodes_for_entry(db_session, entry)
    series[0].removed_at = utcnow()
    files[0].removed_at = utcnow()
    await db_session.flush()
    dangling = await episodes_for_entry(db_session, entry)

    assert decided[0].state is MatchState.MATCHED
    assert decided[0].jellyfin_item_id == files[0].id
    assert dangling[0].state is MatchState.AMBIGUOUS
    assert dangling[0].jellyfin_item_id is None
    assert dangling[0].covers_range is False


async def test_a_dangling_pick_with_nothing_left_to_choose_between_reports_not_in_library(
    db_session: AsyncSession,
) -> None:
    """Ruling 98's other half: with no live candidate there is nothing to ask about, so the entry says
    what it honestly has - nothing - rather than asking for a pick among no files."""
    entry, series, files = await _a_title_the_library_holds_twice(db_session, candidates=FIRST)
    series[0].removed_at = utcnow()
    files[0].removed_at = utcnow()
    await db_session.flush()

    matches = await episodes_for_entry(db_session, entry)

    assert matches[0].state is MatchState.NOT_IN_LIBRARY
    assert matches[0].jellyfin_item_id is None


async def test_a_batched_page_keeps_each_titles_series_and_each_entrys_numbering_separate(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    category = await a_category(db_session)
    entries: list[CuratedEntry] = []
    expected: list[tuple[uuid.UUID, str]] = []
    for title_index in range(2):
        title = await a_show(db_session, f"Show {title_index}", episodes=1, tmdb_id=A_TMDB_ID + title_index)
        series = await a_series_file(
            db_session, jellyfin_id=file_id(100 + title_index), name=title.name, tmdb_id=title.tmdb_id
        )
        await a_second_numbering(
            db_session,
            title,
            order_type=A_PROVIDER_ORDER,
            season_number=AN_ALTERNATE_SEASON,
            first_number=AN_ALTERNATE_FIRST,
        )
        for order_index, order_type in enumerate((AIRED_ORDER_TYPE, A_PROVIDER_ORDER)):
            entry = await an_entry(
                db_session,
                category,
                title_id=title.id,
                unit_kind=UnitKind.EPISODES,
                order_type=order_type,
                span_start=1,
                span_end=1,
                position=len(entries) + 1,
            )
            file = await an_episode_file(
                db_session,
                series_jellyfin_id=series.jellyfin_id,
                season=A_FIRST_SEASON if order_index == 0 else AN_ALTERNATE_SEASON,
                number=1 if order_index == 0 else AN_ALTERNATE_FIRST,
                jellyfin_id=file_id((title_index + 1) * 10 + order_index),
            )
            entries.append(entry)
            expected.append((file.id, order_type))
    await rebuild_items(db_session, category.id)
    with counted_statements(engine) as statements:
        matches = await episodes_for_entries(db_session, list(reversed(entries)))
    assert len(statements) == STATEMENTS_PER_ENTRY
    for entry, (file_id_, order_type) in zip(entries, expected, strict=True):
        assert len(matches[entry.id]) == 1
        assert matches[entry.id][0].state is MatchState.MATCHED
        assert matches[entry.id][0].jellyfin_item_id == file_id_
        assert matches[entry.id][0].order_type == order_type
