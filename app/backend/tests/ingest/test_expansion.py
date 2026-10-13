"""The flattened queue: what one entry contributes, and where a whole category's ranks land.

The pure half runs offline against synthetic orderings, because expansion consumes `episode_order`
rather than a provider payload - nothing about the rules needs a network or a database. The half that
writes runs against a real Postgres and skips loudly without one (CLAUDE.md section 16.4).

Two of those reach for real data rather than a construction. One seeds the recorded One Piece slice
through T19's TMDB ingest and T20's order ingest, so a span is scanned over ranks a provider actually
produced. The other reads the owner's own `One_Piece.xlsx` - the one by-name selection this suite
sanctions, because the acceptance line names that file - and proves the queue interleaves its films
and its episode spans exactly as the sheet orders them (ADR-010).
"""

from __future__ import annotations

import inspect
import uuid
from collections import Counter
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final

import pytest
from ingest_support import (
    A_TYPE_THE_APP_HAS_NEVER_SEEN,
    SPECIALS,
    THEIR_ABSOLUTE,
    order_ingest,
    seeded_one_piece,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from statement_support import counted_statements
from tv_watchlist.clock import utcnow
from tv_watchlist.constants import SPECIALS_ORDER_LABEL
from tv_watchlist.data.enums import ExternalSource, MediaType, ResolutionState, UnitKind
from tv_watchlist.data.models import (
    Category,
    CuratedEntry,
    CuratedEntryItem,
    Episode,
    EpisodeOrder,
    Season,
    Title,
)
from tv_watchlist.ingest.episode_orders import AIRED_ORDER_TYPE, NO_LABEL, SPECIALS_ORDER_TYPE
from tv_watchlist.ingest.expansion import (
    EMPTY_RANGE,
    MISSING_ORDER,
    NO_SEASON,
    NO_SPAN,
    NO_TITLE,
    NOT_RESOLVED,
    QUEUE_NOTE_PREFIX,
    SEASON_NOT_COVERED,
    SHORT_COVER,
    UNSUPPORTED_KIND,
    Expansion,
    ExpansionItem,
    _reasons,
    _row,
    expand_entry,
    noted,
    rebuild_items,
    renumber_absolute_positions,
)
from tv_watchlist.ingest.reconciler import Reconciler
from tv_watchlist.resolver.span import parse_unit
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.curated_columns import curated_columns
from tv_watchlist.workbook.reader import read_projection
from workbook_facts import WorkbookFacts

A_TITLE: Final[uuid.UUID] = uuid.UUID("11111111-1111-4111-8111-111111111111")
A_CATEGORY: Final[uuid.UUID] = uuid.UUID("22222222-2222-4222-8222-222222222222")
A_RESOLVER_NOTE: Final[str] = "absolute numbering assumed"

#: The reference row: One Piece's second episode span, 35 episodes long (`One_Piece.xlsx`, row 6).
ONE_PIECE_SECOND_SPAN: Final[tuple[int, int]] = (19, 53)
ONE_PIECE_SECOND_SPAN_LENGTH: Final[int] = 35
ONE_PIECE_FILE: Final[str] = "One_Piece.xlsx"
#: What that workbook holds, measured 2026-09-20 by parsing all 71 of its `Unit` cells with T17.
ONE_PIECE_EPISODE_ROWS: Final[int] = 28
ONE_PIECE_FILM_ROWS: Final[int] = 15
ONE_PIECE_SPECIAL_ROWS: Final[int] = 22
ONE_PIECE_UNPARSED_ROWS: Final[int] = 6
ONE_PIECE_LAST_EPISODE: Final[int] = 1175

#: The recorded TMDB slice numbers season 2 absolutely inside its bucket, from Laboon at 62.
RECORDED_SEASON_TWO: Final[int] = 2
RECORDED_SEASON_TWO_FIRST: Final[int] = 62
RECORDED_SEASON_TWO_LAST: Final[int] = 77
SPECIALS_SEASON: Final[int] = 0

A_SHORT_ORDERING: Final[int] = 10
#: Keeps the synthetic specials' `tmdb_episode_id` clear of the regular run's, which is unique per row.
A_SPECIALS_TMDB_OFFSET: Final[int] = 1_000_000


# -- builders ---------------------------------------------------------------------------------------


def _slot(
    order_type: str,
    sequence: int,
    *,
    label: str = NO_LABEL,
    season: int | None = None,
    number: int | None = None,
    episode_id: uuid.UUID | None = None,
    title_id: uuid.UUID = A_TITLE,
) -> EpisodeOrder:
    """One `episode_order` row as expansion reads it, detached and never flushed."""
    return EpisodeOrder(
        id=uuid.uuid4(),
        title_id=title_id,
        episode_id=uuid.uuid4() if episode_id is None else episode_id,
        order_type=order_type,
        label=label,
        sequence=sequence,
        order_season_number=season,
        order_episode_number=number,
        source=ExternalSource.TMDB,
    )


def _numbered(order_type: str, count: int, *, label: str = NO_LABEL) -> tuple[EpisodeOrder, ...]:
    """A numbering whose rank is its own number, 1..count - the shape an absolute ordering takes."""
    return tuple(_slot(order_type, sequence, label=label) for sequence in range(1, count + 1))


def _aired_over(*runs: tuple[int, int, int]) -> tuple[EpisodeOrder, ...]:
    """The aired rank over `(season, first, last)` runs, numbered absolutely inside season buckets."""
    slots: list[EpisodeOrder] = []
    for season, first, last in runs:
        slots.extend(
            _slot(AIRED_ORDER_TYPE, len(slots) + offset + 1, season=season, number=number)
            for offset, number in enumerate(range(first, last + 1))
        )
    return tuple(slots)


def _specials(count: int) -> tuple[EpisodeOrder, ...]:
    """The specials bucket as its own numbering, which is where season 0 lives."""
    return tuple(
        _slot(SPECIALS_ORDER_TYPE, number, label=SPECIALS_ORDER_LABEL, season=SPECIALS_SEASON, number=number)
        for number in range(1, count + 1)
    )


def _entry(
    *,
    unit_kind: UnitKind,
    title_id: uuid.UUID | None = A_TITLE,
    order_type: str | None = None,
    order_label: str = NO_LABEL,
    span_start: int | None = None,
    span_end: int | None = None,
    season_number: int | None = None,
    state: ResolutionState = ResolutionState.AUTO,
    note: str = "",
    position: int = 1,
) -> CuratedEntry:
    """One entry as the reconciler leaves it. Every column-level default is spelled out: a detached
    instance has not been flushed, so `default=` has not run and every unset field is still `None`."""
    return CuratedEntry(
        id=uuid.uuid4(),
        category_id=A_CATEGORY,
        position=position,
        title_id=title_id,
        unit_kind=unit_kind,
        order_type=order_type,
        order_label=order_label,
        span_start=span_start,
        span_end=span_end,
        season_number=season_number,
        resolution_state=state,
        resolution_note=note,
        raw_cells={},
    )


def _episode_ids(orders: Sequence[EpisodeOrder]) -> tuple[uuid.UUID, ...]:
    return tuple(order.episode_id for order in orders)


# -- the pure rules, per unit kind ------------------------------------------------------------------


def test_a_movie_entry_occupies_exactly_one_slot_with_movie_title_id_set() -> None:
    expansion = expand_entry(_entry(unit_kind=UnitKind.MOVIE), ())

    assert expansion.items == (ExpansionItem(episode_id=None, movie_title_id=A_TITLE, position_in_entry=1),)
    assert expansion.note == ""


def test_an_episode_span_expands_to_a_range_scan_over_the_named_order() -> None:
    start, end = ONE_PIECE_SECOND_SPAN
    orders = _numbered(THEIR_ABSOLUTE, ONE_PIECE_LAST_EPISODE)
    entry = _entry(unit_kind=UnitKind.EPISODES, order_type=THEIR_ABSOLUTE, span_start=start, span_end=end)

    expansion = expand_entry(entry, orders)

    assert len(expansion.items) == ONE_PIECE_SECOND_SPAN_LENGTH
    assert tuple(item.position_in_entry for item in expansion.items) == tuple(
        range(1, ONE_PIECE_SECOND_SPAN_LENGTH + 1)
    )
    assert tuple(item.episode_id for item in expansion.items) == _episode_ids(orders[start - 1 : end])
    assert all(item.movie_title_id is None for item in expansion.items)
    assert expansion.note == ""


def test_the_reference_span_is_the_one_the_real_workbook_carries(library: Path) -> None:
    """T17's parse of One Piece's own `E19-53` cell, so the 35 above is the sheet's number, not a guess."""
    spans = [span for span in _one_piece_spans(library) if span.unit_kind is UnitKind.EPISODES]
    span = spans[1]

    assert (span.span_start, span.span_end) == ONE_PIECE_SECOND_SPAN
    assert span.span_end is not None and span.span_start is not None
    assert span.span_end - span.span_start + 1 == ONE_PIECE_SECOND_SPAN_LENGTH


def test_a_missing_order_leaves_no_items_and_a_note_that_never_falls_back_to_aired() -> None:
    aired_only = _aired_over((1, 1, A_SHORT_ORDERING))
    entry = _entry(unit_kind=UnitKind.EPISODES, order_type=THEIR_ABSOLUTE, span_start=1, span_end=3)

    expansion = expand_entry(entry, aired_only)

    assert expansion.items == ()
    assert expansion.reason == MISSING_ORDER
    assert THEIR_ABSOLUTE in expansion.note
    assert AIRED_ORDER_TYPE not in expansion.note


def test_a_label_a_title_lacks_is_a_missing_order_even_when_the_type_is_there() -> None:
    entry = _entry(
        unit_kind=UnitKind.EPISODES,
        order_type=THEIR_ABSOLUTE,
        order_label=SPECIALS_ORDER_LABEL,
        span_start=1,
        span_end=3,
    )

    expansion = expand_entry(entry, _numbered(THEIR_ABSOLUTE, A_SHORT_ORDERING))

    assert expansion.items == ()
    assert expansion.reason == MISSING_ORDER


def test_a_span_beyond_the_orderings_end_expands_to_nothing_with_a_note() -> None:
    entry = _entry(
        unit_kind=UnitKind.EPISODES,
        order_type=THEIR_ABSOLUTE,
        span_start=A_SHORT_ORDERING + 1,
        span_end=A_SHORT_ORDERING + 5,
    )

    expansion = expand_entry(entry, _numbered(THEIR_ABSOLUTE, A_SHORT_ORDERING))

    assert expansion.items == ()
    assert expansion.reason == EMPTY_RANGE
    assert str(A_SHORT_ORDERING + 1) in expansion.note


def test_a_span_the_ordering_only_partly_covers_expands_what_it_holds_and_says_so() -> None:
    """A stored range keeps meaning something after the ordering changes under it - but a short cover
    is the detectable half of that, so the queue says so rather than quietly ending early."""
    entry = _entry(
        unit_kind=UnitKind.EPISODES, order_type=THEIR_ABSOLUTE, span_start=A_SHORT_ORDERING - 1, span_end=999
    )

    expansion = expand_entry(entry, _numbered(THEIR_ABSOLUTE, A_SHORT_ORDERING))

    assert len(expansion.items) == 2
    assert expansion.reason == SHORT_COVER
    assert "2" in expansion.note


def test_a_season_entry_expands_to_that_seasons_own_slots_and_excludes_specials() -> None:
    orders = (*_aired_over((1, 1, 5), (2, 6, 9)), *_specials(3))
    entry = _entry(unit_kind=UnitKind.SEASON, season_number=2)

    expansion = expand_entry(entry, orders)

    assert tuple(item.episode_id for item in expansion.items) == _episode_ids(orders[5:9])
    assert tuple(item.position_in_entry for item in expansion.items) == (1, 2, 3, 4)


def test_a_season_range_expands_every_season_it_names_in_order() -> None:
    """Ruling 29: on a season row the span holds SEASON numbers, never episode numbers."""
    orders = _aired_over((1, 1, 2), (2, 3, 4), (3, 5, 6))
    entry = _entry(unit_kind=UnitKind.SEASON, span_start=1, span_end=2)

    expansion = expand_entry(entry, orders)

    assert tuple(item.episode_id for item in expansion.items) == _episode_ids(orders[:4])


def test_a_bare_season_zero_expands_to_the_specials_bucket() -> None:
    orders = (*_aired_over((1, 1, 5)), *_specials(3))
    entry = _entry(unit_kind=UnitKind.SEASON, season_number=SPECIALS_SEASON)

    expansion = expand_entry(entry, orders)

    assert len(expansion.items) == 3
    assert tuple(item.episode_id for item in expansion.items) == _episode_ids(orders[5:])


def test_a_season_the_title_does_not_carry_expands_to_nothing_with_a_note() -> None:
    entry = _entry(unit_kind=UnitKind.SEASON, season_number=9)

    expansion = expand_entry(entry, _aired_over((1, 1, 5)))

    assert expansion.items == ()
    assert expansion.reason == EMPTY_RANGE


def test_a_season_entry_naming_no_season_at_all_expands_to_nothing() -> None:
    expansion = expand_entry(_entry(unit_kind=UnitKind.SEASON), _aired_over((1, 1, 5)))

    assert expansion.items == ()
    assert expansion.reason == NO_SPAN


def test_an_episodes_entry_with_no_numbering_resolves_within_its_season() -> None:
    """Ruling 30: a season-scoped range names no numbering, so the season is what disambiguates it."""
    orders = _aired_over((1, 1, 61), (2, 62, 77))
    entry = _entry(unit_kind=UnitKind.EPISODES, order_type=None, season_number=2, span_start=64, span_end=66)

    expansion = expand_entry(entry, orders)

    assert tuple(item.episode_id for item in expansion.items) == _episode_ids(orders[63:66])


def test_an_episodes_entry_with_no_numbering_refuses_a_season_that_does_not_cover_it() -> None:
    orders = _aired_over((1, 1, 61), (2, 62, 77))
    entry = _entry(unit_kind=UnitKind.EPISODES, order_type=None, season_number=2, span_start=76, span_end=80)

    expansion = expand_entry(entry, orders)

    assert expansion.items == ()
    assert expansion.reason == SEASON_NOT_COVERED


def test_an_episodes_entry_with_no_numbering_and_no_season_expands_to_nothing() -> None:
    entry = _entry(unit_kind=UnitKind.EPISODES, order_type=None, span_start=1, span_end=3)

    expansion = expand_entry(entry, _aired_over((1, 1, 5)))

    assert expansion.items == ()
    assert expansion.reason == NO_SEASON


def test_an_episodes_entry_with_no_span_stored_expands_to_nothing() -> None:
    entry = _entry(unit_kind=UnitKind.EPISODES, order_type=THEIR_ABSOLUTE)

    expansion = expand_entry(entry, _numbered(THEIR_ABSOLUTE, A_SHORT_ORDERING))

    assert expansion.items == ()
    assert expansion.reason == NO_SPAN


def test_a_series_entry_expands_to_the_whole_aired_ordering() -> None:
    """A blank `Unit` on a matched tv title means the whole show, so the queue holds the whole show."""
    orders = (*_aired_over((1, 1, 5)), *_specials(3))
    entry = _entry(unit_kind=UnitKind.SERIES)

    expansion = expand_entry(entry, orders)

    assert tuple(item.episode_id for item in expansion.items) == _episode_ids(orders[:5])


def test_a_series_entry_on_a_title_with_no_episodes_yet_expands_to_nothing() -> None:
    expansion = expand_entry(_entry(unit_kind=UnitKind.SERIES), ())

    assert expansion.items == ()
    assert expansion.reason == MISSING_ORDER


def test_a_special_matched_inside_its_parent_expands_to_that_one_episode() -> None:
    orders = (*_aired_over((1, 1, 5)), *_specials(4))
    entry = _entry(unit_kind=UnitKind.SPECIAL, season_number=SPECIALS_SEASON, span_start=3, span_end=3)

    expansion = expand_entry(entry, orders)

    assert tuple(item.episode_id for item in expansion.items) == (orders[7].episode_id,)


def test_a_special_that_was_never_matched_inside_a_parent_expands_to_nothing() -> None:
    expansion = expand_entry(_entry(unit_kind=UnitKind.SPECIAL), _specials(4))

    assert expansion.items == ()
    assert expansion.reason == NO_SPAN
    assert "span" not in expansion.note


@pytest.mark.parametrize("unit_kind", [UnitKind.SPECIAL, UnitKind.UNKNOWN])
def test_a_span_less_row_whose_title_is_a_film_takes_the_one_slot_a_film_takes(unit_kind: UnitKind) -> None:
    """Sixty-nine library rows read `OVA`, `Short` or nothing; a title that resolved to a TMDB movie
    settles every one of them, and leaving them out would make Next skip each one (ADR-010)."""
    expansion = expand_entry(_entry(unit_kind=unit_kind), (), MediaType.MOVIE)

    assert expansion.items == (ExpansionItem(episode_id=None, movie_title_id=A_TITLE, position_in_entry=1),)
    assert expansion.note == ""


def test_a_special_whose_title_is_a_show_still_goes_looking_for_its_episode() -> None:
    orders = (*_aired_over((1, 1, 5)), *_specials(4))
    entry = _entry(unit_kind=UnitKind.SPECIAL, season_number=SPECIALS_SEASON, span_start=2, span_end=2)

    expansion = expand_entry(entry, orders, MediaType.TV)

    assert tuple(item.episode_id for item in expansion.items) == (orders[6].episode_id,)


def test_an_unknown_media_type_leaves_the_question_open_rather_than_guessing_a_film() -> None:
    expansion = expand_entry(_entry(unit_kind=UnitKind.SPECIAL), (), None)

    assert expansion.items == ()
    assert expansion.reason == NO_SPAN


@pytest.mark.parametrize("state", [ResolutionState.UNRESOLVED, ResolutionState.REJECTED])
def test_an_entry_that_never_resolved_expands_to_nothing_and_adds_no_note(state: ResolutionState) -> None:
    entry = _entry(unit_kind=UnitKind.EPISODES, order_type=THEIR_ABSOLUTE, span_start=1, span_end=3, state=state)

    expansion = expand_entry(entry, _numbered(THEIR_ABSOLUTE, A_SHORT_ORDERING))

    assert expansion.items == ()
    assert expansion.reason == NOT_RESOLVED
    assert expansion.note == ""


def test_an_entry_with_no_title_expands_to_nothing_and_adds_no_note() -> None:
    entry = _entry(unit_kind=UnitKind.MOVIE, title_id=None)

    expansion = expand_entry(entry, ())

    assert expansion == Expansion(items=(), note="", reason=NO_TITLE)


def test_a_unit_kind_that_names_no_playable_unit_expands_to_nothing_with_a_note() -> None:
    expansion = expand_entry(_entry(unit_kind=UnitKind.UNKNOWN), ())

    assert expansion.items == ()
    assert expansion.reason == UNSUPPORTED_KIND
    assert UnitKind.UNKNOWN.value in expansion.note


# -- the note the review queue reads ----------------------------------------------------------------


def test_a_queue_note_is_appended_beside_the_resolvers_own() -> None:
    combined = noted(A_RESOLVER_NOTE, "nothing to expand")

    assert combined.startswith(A_RESOLVER_NOTE)
    assert f"{QUEUE_NOTE_PREFIX}nothing to expand" in combined


def test_a_second_pass_replaces_the_queue_note_rather_than_stacking_it() -> None:
    once = noted(A_RESOLVER_NOTE, "nothing to expand")
    twice = noted(once, "nothing to expand")
    changed = noted(twice, "something else")

    assert twice == once
    assert changed.count(QUEUE_NOTE_PREFIX) == 1
    assert changed.startswith(A_RESOLVER_NOTE)


def test_an_expansion_that_refuses_nothing_clears_the_queue_note_it_left_before() -> None:
    assert noted(noted(A_RESOLVER_NOTE, "nothing to expand"), "") == A_RESOLVER_NOTE
    assert noted("", "") == ""


def test_a_skip_breakdown_is_one_sorted_log_field_of_closed_codes() -> None:
    assert _reasons(Counter()) == "-"
    assert _reasons(Counter({"no_span": 1, "missing_order": 3})) == "missing_order=3,no_span=1"


def test_an_insert_payload_carries_every_column_the_table_requires_and_no_id() -> None:
    """`id` is absent on purpose: `UuidPk`'s client-side default mints it, which is what lets the
    reconciler know a row's id before flush."""
    entry_id = uuid.uuid4()
    episode_id = uuid.uuid4()

    payload = _row(A_CATEGORY, entry_id, ExpansionItem(episode_id, None, 2), 7)

    assert payload == {
        "category_id": A_CATEGORY,
        "curated_entry_id": entry_id,
        "episode_id": episode_id,
        "movie_title_id": None,
        "position_in_entry": 2,
        "absolute_position": 7,
    }


# -- the database half ------------------------------------------------------------------------------


async def _category(session: AsyncSession, slug: str = "one-piece") -> Category:
    category = Category(slug=slug, file_name=f"{slug}.xlsx", sheet_title="Watch Order", accent="#1F2937")
    session.add(category)
    await session.flush()
    return category


async def _added(session: AsyncSession, category: Category, entry: CuratedEntry) -> CuratedEntry:
    entry.category_id = category.id
    session.add(entry)
    await session.flush()
    return entry


async def _a_film(session: AsyncSession, name: str) -> Title:
    title = Title(media_type=MediaType.MOVIE, tmdb_id=None, name=name, match_key=name.casefold())
    session.add(title)
    await session.flush()
    return title


async def _a_show_numbered(
    session: AsyncSession, name: str, order_type: str, episodes: int, *, specials: int = 0
) -> Title:
    """A tv title with one numbering 1..episodes, plus an optional season-0 bucket beside it."""
    title = Title(media_type=MediaType.TV, tmdb_id=None, name=name, match_key=name.casefold())
    session.add(title)
    await session.flush()
    season = Season(title_id=title.id, season_number=1)
    session.add(season)
    await session.flush()
    rows = [
        Episode(
            title_id=title.id,
            season_id=season.id,
            season_number=1,
            episode_number=number,
            tmdb_episode_id=number,
        )
        for number in range(1, episodes + 1)
    ]
    session.add_all(rows)
    await session.flush()
    session.add_all(
        [
            EpisodeOrder(
                title_id=title.id,
                episode_id=episode.id,
                order_type=order_type,
                label=NO_LABEL,
                sequence=number,
                order_season_number=1,
                order_episode_number=number,
                source=ExternalSource.TMDB,
            )
            for number, episode in enumerate(rows, start=1)
        ]
    )
    if specials:
        await _a_specials_bucket(session, title, specials)
    await session.flush()
    return title


async def _a_specials_bucket(session: AsyncSession, title: Title, count: int) -> None:
    """Season 0 as its own numbering, exactly where T20's aired walk puts it."""
    season = Season(title_id=title.id, season_number=SPECIALS_SEASON)
    session.add(season)
    await session.flush()
    rows = [
        Episode(
            title_id=title.id,
            season_id=season.id,
            season_number=SPECIALS_SEASON,
            episode_number=number,
            tmdb_episode_id=A_SPECIALS_TMDB_OFFSET + number,
        )
        for number in range(1, count + 1)
    ]
    session.add_all(rows)
    await session.flush()
    session.add_all(
        [
            EpisodeOrder(
                title_id=title.id,
                episode_id=episode.id,
                order_type=SPECIALS_ORDER_TYPE,
                label=SPECIALS_ORDER_LABEL,
                sequence=number,
                order_season_number=SPECIALS_SEASON,
                order_episode_number=number,
                source=ExternalSource.TMDB,
            )
            for number, episode in enumerate(rows, start=1)
        ]
    )


async def _items(session: AsyncSession, category: Category) -> list[CuratedEntryItem]:
    rows = await session.scalars(
        select(CuratedEntryItem)
        .where(CuratedEntryItem.category_id == category.id)
        .order_by(CuratedEntryItem.absolute_position)
    )
    return list(rows)


def _kinds(statements: Sequence[str]) -> list[str]:
    """Each captured statement as the one word that says what it did, in the order it was issued."""
    return [statement.lower().lstrip().split(maxsplit=1)[0] for statement in statements]


@pytest.fixture
def item_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    with counted_statements(engine, "curated_entry_item") as seen:
        yield seen


async def test_a_movie_entry_writes_exactly_one_row_carrying_movie_title_id(db_session: AsyncSession) -> None:
    category = await _category(db_session)
    film = await _a_film(db_session, "One Piece: The Movie")
    await _added(db_session, category, _entry(unit_kind=UnitKind.MOVIE, title_id=film.id, position=1))

    written = await rebuild_items(db_session, category.id)

    rows = await _items(db_session, category)
    assert written == 1
    assert [(row.episode_id, row.movie_title_id, row.position_in_entry, row.absolute_position) for row in rows] == [
        (None, film.id, 1, 1)
    ]


async def test_a_special_whose_title_is_a_film_writes_one_row_from_the_media_type_on_disk(
    db_session: AsyncSession,
) -> None:
    """The plumbing, end to end: `rebuild_items` reads `title.media_type` and the film branch follows."""
    category = await _category(db_session)
    film = await _a_film(db_session, "Defeat the Pirate Ganzack!")
    show = await _a_show_numbered(db_session, "A Show", THEIR_ABSOLUTE, A_SHORT_ORDERING, specials=2)
    ova = await _added(db_session, category, _entry(unit_kind=UnitKind.SPECIAL, title_id=film.id, position=1))
    await _added(
        db_session,
        category,
        _entry(
            unit_kind=UnitKind.SPECIAL,
            title_id=show.id,
            season_number=SPECIALS_SEASON,
            span_start=1,
            span_end=1,
            position=2,
        ),
    )

    written = await rebuild_items(db_session, category.id)

    rows = await _items(db_session, category)
    assert written == 2
    assert (rows[0].curated_entry_id, rows[0].movie_title_id, rows[0].episode_id) == (ova.id, film.id, None)
    assert rows[1].movie_title_id is None and rows[1].episode_id is not None


async def test_a_span_is_scanned_over_the_ranks_the_order_ingest_actually_wrote(db_session: AsyncSession) -> None:
    """The reference case, against ranks TheTVDB's own absolute ordering produced for the recorded slice."""
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(db_session)
    await ingest.rank_aired(title)
    await ingest.ingest_tvdb_orders(title)
    await db_session.flush()
    category = await _category(db_session)
    await _added(
        db_session,
        category,
        _entry(unit_kind=UnitKind.EPISODES, title_id=title.id, order_type=THEIR_ABSOLUTE, span_start=19, span_end=53),
    )

    written = await rebuild_items(db_session, category.id)

    rows = await _items(db_session, category)
    sequences = await db_session.scalars(
        select(EpisodeOrder.sequence)
        .where(EpisodeOrder.order_type == THEIR_ABSOLUTE, EpisodeOrder.episode_id.in_([row.episode_id for row in rows]))
        .order_by(EpisodeOrder.sequence)
    )
    assert written == ONE_PIECE_SECOND_SPAN_LENGTH
    assert list(sequences) == list(range(19, 54))
    assert [row.absolute_position for row in rows] == list(range(1, ONE_PIECE_SECOND_SPAN_LENGTH + 1))


async def test_a_season_entry_expands_to_that_seasons_ingested_slots(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(db_session)
    await ingest.rank_aired(title)
    await db_session.flush()
    category = await _category(db_session)
    await _added(
        db_session,
        category,
        _entry(unit_kind=UnitKind.SEASON, title_id=title.id, season_number=RECORDED_SEASON_TWO),
    )

    written = await rebuild_items(db_session, category.id)

    assert written == RECORDED_SEASON_TWO_LAST - RECORDED_SEASON_TWO_FIRST + 1
    numbers = await db_session.scalars(
        select(Episode.season_number).where(
            Episode.id.in_([row.episode_id for row in await _items(db_session, category)])
        )
    )
    assert set(numbers) == {RECORDED_SEASON_TWO}


async def test_a_season_zero_entry_expands_to_the_ingested_specials_bucket(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(db_session)
    await ingest.rank_aired(title)
    await db_session.flush()
    category = await _category(db_session)
    await _added(
        db_session, category, _entry(unit_kind=UnitKind.SEASON, title_id=title.id, season_number=SPECIALS_SEASON)
    )

    assert await rebuild_items(db_session, category.id) == SPECIALS


async def test_a_missing_order_writes_no_row_and_leaves_the_reason_on_the_entry(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(db_session)
    await ingest.rank_aired(title)
    await db_session.flush()
    category = await _category(db_session)
    entry = await _added(
        db_session,
        category,
        _entry(
            unit_kind=UnitKind.EPISODES,
            title_id=title.id,
            order_type=A_TYPE_THE_APP_HAS_NEVER_SEEN,
            span_start=1,
            span_end=3,
        ),
    )

    written = await rebuild_items(db_session, category.id)
    await db_session.flush()

    assert written == 0
    assert A_TYPE_THE_APP_HAS_NEVER_SEEN in entry.resolution_note
    assert AIRED_ORDER_TYPE not in entry.resolution_note
    assert await _items(db_session, category) == []


async def test_an_unresolved_entry_contributes_no_items_but_keeps_its_position(db_session: AsyncSession) -> None:
    category = await _category(db_session)
    show = await _a_show_numbered(db_session, "A Show", THEIR_ABSOLUTE, A_SHORT_ORDERING)
    unresolved = await _added(
        db_session,
        category,
        _entry(unit_kind=UnitKind.UNKNOWN, title_id=None, state=ResolutionState.UNRESOLVED, position=1),
    )
    resolved = await _added(
        db_session,
        category,
        _entry(
            unit_kind=UnitKind.EPISODES,
            title_id=show.id,
            order_type=THEIR_ABSOLUTE,
            span_start=1,
            span_end=2,
            position=2,
        ),
    )

    await rebuild_items(db_session, category.id)

    rows = await _items(db_session, category)
    assert unresolved.position == 1
    assert {row.curated_entry_id for row in rows} == {resolved.id}
    assert [row.absolute_position for row in rows] == [1, 2]


async def test_a_soft_deleted_entry_contributes_nothing_and_the_live_ranks_stay_dense(
    db_session: AsyncSession,
) -> None:
    category = await _category(db_session)
    show = await _a_show_numbered(db_session, "A Show", THEIR_ABSOLUTE, A_SHORT_ORDERING)
    first = await _added(
        db_session,
        category,
        _entry(
            unit_kind=UnitKind.EPISODES,
            title_id=show.id,
            order_type=THEIR_ABSOLUTE,
            span_start=1,
            span_end=2,
            position=1,
        ),
    )
    second = await _added(
        db_session,
        category,
        _entry(
            unit_kind=UnitKind.EPISODES,
            title_id=show.id,
            order_type=THEIR_ABSOLUTE,
            span_start=3,
            span_end=4,
            position=2,
        ),
    )
    await rebuild_items(db_session, category.id)

    second.removed_at = utcnow()
    await db_session.flush()
    await rebuild_items(db_session, category.id)

    rows = await _items(db_session, category)
    assert {row.curated_entry_id for row in rows} == {first.id}
    assert [row.absolute_position for row in rows] == [1, 2]


async def test_a_rebuild_scoped_to_one_entry_leaves_the_other_entries_rows_alone(db_session: AsyncSession) -> None:
    category = await _category(db_session)
    show = await _a_show_numbered(db_session, "A Show", THEIR_ABSOLUTE, A_SHORT_ORDERING)
    untouched = await _added(
        db_session,
        category,
        _entry(
            unit_kind=UnitKind.EPISODES,
            title_id=show.id,
            order_type=THEIR_ABSOLUTE,
            span_start=1,
            span_end=2,
            position=1,
        ),
    )
    moved = await _added(
        db_session,
        category,
        _entry(
            unit_kind=UnitKind.EPISODES,
            title_id=show.id,
            order_type=THEIR_ABSOLUTE,
            span_start=3,
            span_end=4,
            position=2,
        ),
    )
    await rebuild_items(db_session, category.id)
    before = {row.id for row in await _items(db_session, category) if row.curated_entry_id == untouched.id}

    await rebuild_items(db_session, category.id, [moved.id])

    rows = await _items(db_session, category)
    assert {row.id for row in rows if row.curated_entry_id == untouched.id} == before
    assert [row.absolute_position for row in rows] == [1, 2, 3, 4]


async def test_a_second_rebuild_writes_the_same_rows_at_the_same_positions(db_session: AsyncSession) -> None:
    category = await _category(db_session)
    show = await _a_show_numbered(db_session, "A Show", THEIR_ABSOLUTE, A_SHORT_ORDERING)
    film = await _a_film(db_session, "A Film")
    await _added(
        db_session,
        category,
        _entry(
            unit_kind=UnitKind.EPISODES,
            title_id=show.id,
            order_type=THEIR_ABSOLUTE,
            span_start=1,
            span_end=3,
            position=1,
        ),
    )
    await _added(db_session, category, _entry(unit_kind=UnitKind.MOVIE, title_id=film.id, position=2))
    await rebuild_items(db_session, category.id)
    before = [
        (row.curated_entry_id, row.episode_id, row.movie_title_id, row.position_in_entry, row.absolute_position)
        for row in await _items(db_session, category)
    ]

    await rebuild_items(db_session, category.id)

    after = [
        (row.curated_entry_id, row.episode_id, row.movie_title_id, row.position_in_entry, row.absolute_position)
        for row in await _items(db_session, category)
    ]
    assert after == before


async def test_a_rebuild_clears_before_it_inserts_and_renumbers_last(
    db_session: AsyncSession, item_statements: list[str]
) -> None:
    """The order is the whole safety argument: rows are dropped, rewritten with provisional positions,
    and only then ranked - so no row is ever left holding a number a later one renumbers onto."""
    category = await _category(db_session)
    show = await _a_show_numbered(db_session, "A Show", THEIR_ABSOLUTE, A_SHORT_ORDERING)
    await _added(
        db_session,
        category,
        _entry(
            unit_kind=UnitKind.EPISODES,
            title_id=show.id,
            order_type=THEIR_ABSOLUTE,
            span_start=1,
            span_end=4,
            position=1,
        ),
    )
    item_statements.clear()

    await rebuild_items(db_session, category.id)

    assert _kinds(item_statements) == ["delete", "insert", "update"]


async def test_renumbering_is_a_single_statement_the_deferred_unique_absorbs(
    db_session: AsyncSession, item_statements: list[str]
) -> None:
    category = await _category(db_session)
    show = await _a_show_numbered(db_session, "A Show", THEIR_ABSOLUTE, A_SHORT_ORDERING)
    await _added(
        db_session,
        category,
        _entry(
            unit_kind=UnitKind.EPISODES,
            title_id=show.id,
            order_type=THEIR_ABSOLUTE,
            span_start=1,
            span_end=4,
            position=1,
        ),
    )
    await rebuild_items(db_session, category.id)
    item_statements.clear()

    await renumber_absolute_positions(db_session, category.id)
    # Deferred constraints are checked at COMMIT, and this suite's session commits into a SAVEPOINT -
    # so the check is demanded explicitly, or "no IntegrityError" would prove nothing.
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    updates = [statement for statement in item_statements if statement.lower().lstrip().startswith("update")]
    assert len(updates) == 1


# -- the gate: the owner's own One Piece workbook ----------------------------------------------------


def _one_piece_spans(library: Path) -> list:
    """Every `Unit` cell of the real workbook, parsed exactly as the reconciler parses it."""
    projection = read_projection(library / ONE_PIECE_FILE)
    columns = curated_columns(projection.detail.columns)
    return [parse_unit(columns.raw_unit(row), raw_type=columns.raw_type(row)) for row in projection.detail.rows]


async def test_the_real_one_piece_queue_interleaves_films_and_episodes_in_sheet_order(
    db_session: AsyncSession, library: Path
) -> None:
    """ADR-010's acceptance line. Expansion consumes `episode_order`, never a provider payload, so the
    orderings here are synthetic and the *sheet* is the real thing under test.

    All three kinds the sheet actually carries contribute, because all three sit between the spans: 28
    episode ranges, 15 films, and 22 specials - `OVA`, `Short`, `Special`, `TV Special N` - each placed at
    one season-0 episode the way T18's second pass places one. Leaving the specials out would have let a
    film's neighbour be a row that contributes nothing, which is the one arrangement this assertion must
    not be allowed to skip over. The six unparsed rows stay unresolved, so a row that contributes nothing
    is still in the picture.
    """
    spans = _one_piece_spans(library)
    specials = [span for span in spans if span.unit_kind is UnitKind.SPECIAL]
    assert len(specials) == ONE_PIECE_SPECIAL_ROWS
    category = await _category(db_session)
    show = await _a_show_numbered(
        db_session, "One Piece", THEIR_ABSOLUTE, ONE_PIECE_LAST_EPISODE, specials=len(specials)
    )

    entries: list[CuratedEntry] = []
    special_number = 0
    for position, span in enumerate(spans, start=1):
        if span.unit_kind is UnitKind.EPISODES:
            entry = _entry(
                unit_kind=UnitKind.EPISODES,
                title_id=show.id,
                order_type=span.order_type,
                span_start=span.span_start,
                span_end=span.span_end,
                position=position,
            )
        elif span.unit_kind is UnitKind.MOVIE:
            film = await _a_film(db_session, f"One Piece film {position}")
            entry = _entry(unit_kind=UnitKind.MOVIE, title_id=film.id, position=position)
        elif span.unit_kind is UnitKind.SPECIAL:
            special_number += 1
            entry = _entry(
                unit_kind=UnitKind.SPECIAL,
                title_id=show.id,
                season_number=SPECIALS_SEASON,
                span_start=special_number,
                span_end=special_number,
                position=position,
            )
        else:
            entry = _entry(unit_kind=span.unit_kind, title_id=None, state=ResolutionState.UNRESOLVED, position=position)
        entries.append(await _added(db_session, category, entry))

    await rebuild_items(db_session, category.id)

    rows = await _items(db_session, category)
    by_entry: dict[uuid.UUID, list[CuratedEntryItem]] = {}
    for row in rows:
        by_entry.setdefault(row.curated_entry_id, []).append(row)

    def _rows_of(kind: UnitKind) -> list[CuratedEntry]:
        return [entry for entry, span in zip(entries, spans, strict=True) if span.unit_kind is kind]

    film_entries = _rows_of(UnitKind.MOVIE)
    assert len(_rows_of(UnitKind.EPISODES)) == ONE_PIECE_EPISODE_ROWS
    assert len(film_entries) == ONE_PIECE_FILM_ROWS
    assert len(_rows_of(UnitKind.UNKNOWN)) == ONE_PIECE_UNPARSED_ROWS
    # Every special is one slot too, so a film's neighbour is never a row the queue silently dropped.
    assert all(len(by_entry[entry.id]) == 1 for entry in _rows_of(UnitKind.SPECIAL))
    assert not any(entry.id in by_entry for entry in _rows_of(UnitKind.UNKNOWN))
    # Dense and strictly increasing along (entry.position, position_in_entry) - no gaps, no repeats.
    assert [row.absolute_position for row in rows] == list(range(1, len(rows) + 1))
    assert [(row.curated_entry_id, row.position_in_entry) for row in rows] == [
        (entry.id, position)
        for entry in sorted(entries, key=lambda candidate: candidate.position)
        for position in range(1, len(by_entry.get(entry.id, [])) + 1)
    ]
    for entry in film_entries:
        assert len(by_entry[entry.id]) == 1
    # Every (span, film, span) triple the sheet carries: the film sits between the two spans it separates.
    contributing = [
        entry for entry in sorted(entries, key=lambda candidate: candidate.position) if entry.id in by_entry
    ]
    # Contiguity first, across every neighbouring pair whatever the two kinds are: a queue with a seam
    # in it would satisfy the triples below and still be wrong between a special and the film after it.
    for before, after in zip(contributing, contributing[1:], strict=False):
        assert by_entry[after.id][0].absolute_position == by_entry[before.id][-1].absolute_position + 1
    triples = 0
    for before, film, after in zip(contributing, contributing[1:], contributing[2:], strict=False):
        if film.unit_kind is not UnitKind.MOVIE or before.unit_kind is not UnitKind.EPISODES:
            continue
        if after.unit_kind is not UnitKind.EPISODES:
            continue
        assert by_entry[film.id][0].absolute_position == by_entry[before.id][-1].absolute_position + 1
        assert by_entry[film.id][0].absolute_position == by_entry[after.id][0].absolute_position - 1
        triples += 1
    # The sheet carries the shape the acceptance line names, so this loop can never pass by running zero
    # times: One Piece seats Movie 6 between `E196-224` and `E225-263`, among others.
    assert triples > 0


# -- the seam the reconciler calls ------------------------------------------------------------------


def test_the_reconciler_wires_the_queue_rebuild_in_by_default() -> None:
    """The seam exists to be watched, not to be replaced: unwired, an ingest would leave no queue."""
    assert inspect.signature(Reconciler.__init__).parameters["expand"].default is rebuild_items


async def test_the_reconciler_rebuilds_the_queue_once_its_entries_are_visible(
    db_session: AsyncSession, catalog: Catalog, subject: WorkbookFacts
) -> None:
    """Placement and flush in one assertion: the seam sees every row the pass has just minted.

    Providers are absent, so every entry stays `unresolved` and the queue is empty - which is the point.
    What is under test is *when* the rebuild runs, and the real `rebuild_items` still does the writing.
    """
    seen: list[tuple[uuid.UUID, int]] = []

    async def recording(session: AsyncSession, category_id: uuid.UUID) -> int:
        live = await session.scalar(
            select(func.count())
            .select_from(CuratedEntry)
            .where(CuratedEntry.category_id == category_id, CuratedEntry.removed_at.is_(None))
        )
        seen.append((category_id, 0 if live is None else live))
        return await rebuild_items(session, category_id)

    reconciler = Reconciler(db_session, catalog, resolver=None, tmdb_ingest=None, order_ingest=None, expand=recording)

    outcome = await reconciler.reconcile(subject.category_id)

    category = await db_session.scalar(select(Category).where(Category.slug == subject.category_id))
    assert category is not None
    assert seen == [(category.id, outcome.minted)]
    assert outcome.minted == subject.row_count
    assert await _items(db_session, category) == []
