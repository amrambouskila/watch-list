"""The `Unit` grammar: what each hand-written span string yields, and what it refuses to guess at."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from library_choice import every_workbook
from tv_watchlist.data.enums import UnitKind
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.resolver.span import (
    ABSOLUTE_ASSUMED_NOTE,
    ABSOLUTE_ORDER,
    BELOW_MINIMUM_NOTE,
    BLANK_UNIT_CONFIDENCE,
    BLANK_UNIT_NOTE,
    EPISODE_CONFIDENCE,
    MAX_NOTE_LITERAL,
    MOVIE_CONFIDENCE,
    REVERSED_SPAN_NOTE,
    SEASON_CONFIDENCE,
    SEASON_NOTE,
    SEASON_RANGE_CONFIDENCE,
    SEASON_RANGE_NOTE,
    SEASON_SCOPED_NOTE,
    SHORT_CONFIDENCE,
    SHORT_NOTE,
    SPECIAL_CONFIDENCE,
    SPECIAL_NOTE,
    UNPARSED_CONFIDENCE,
    normalise_unit,
    parse_unit,
    unparsed_note,
)
from tv_watchlist.workbook.reader import read_category
from tv_watchlist.workbook.schema import normalize_header
from workbook_facts import WorkbookFacts

# Every header the library carries the span vocabulary under, in the collapsed form
# `normalize_header` leaves a slashed label in ("Season / Unit" -> "season  unit").
#
# `event` is WWII's `Event` column and is NOT a unit vocabulary - it holds the historical event each
# film depicts ("Mar 1938 - Anschluss"). It is in this set so the library-wide tests feed the parser
# every cell in the column each workbook uses in that position, which is the honest stress test.
# **T18 must not copy this set as a resolver rule**: feeding `Event` to the span parser in production
# would mark all 84 WWII rows unresolved when their real unit is conceptually blank.
UNIT_HEADERS: Final[frozenset[str]] = frozenset(
    {"unit", "season unit", "season episode movie", "season episode block", "episodes seasons", "event"}
)

# The one by-name selection this suite is allowed: master plan section 10.1 names this workbook as the
# resolver queue's reference case, and the reference span below is hand-checked against it.
ONE_PIECE_WORKBOOK: Final[str] = "One_Piece.xlsx"
ONE_PIECE_REFERENCE_UNIT: Final[str] = "E19-53"

Parsed = tuple[UnitKind, str | None, int | None, int | None, int | None]

# Real cells, copied out of the nineteen workbooks and checked by hand against what the row means.
# Each one is asserted to still be in the library, so a curator's edit fails this table loudly rather
# than leaving it quietly describing a string nobody writes any more.
HAND_CHECKED_LIBRARY_CELLS: Final[tuple[tuple[str, Parsed], ...]] = (
    ("E19-53", (UnitKind.EPISODES, ABSOLUTE_ORDER, 19, 53, None)),
    ("E1-18", (UnitKind.EPISODES, ABSOLUTE_ORDER, 1, 18, None)),
    ("E1176 onward", (UnitKind.UNKNOWN, None, None, None, None)),
    ("Episodes 1-7", (UnitKind.EPISODES, ABSOLUTE_ORDER, 1, 7, None)),
    ("Episodes 343-366", (UnitKind.EPISODES, ABSOLUTE_ORDER, 343, 366, None)),
    # No order_type on the season-scoped shape: 8 of the library's 53 such rows number series-wide
    # (Attack_On_Titan `Season 2 E26-37`, My_Hero_Academia `Season 3 E39-58`), so "aired" would lie.
    ("S5 E10-19", (UnitKind.EPISODES, None, 10, 19, 5)),
    ("S3 E1-7", (UnitKind.EPISODES, None, 1, 7, 3)),
    ("S1E8 Flash vs. Arrow I", (UnitKind.UNKNOWN, None, None, None, None)),
    ("S1", (UnitKind.SEASON, None, None, None, 1)),
    ("Season 1", (UnitKind.SEASON, None, None, None, 1)),
    ("Season 25", (UnitKind.SEASON, None, None, None, 25)),
    ("Movie", (UnitKind.MOVIE, None, None, None, None)),
    ("Movie 1", (UnitKind.MOVIE, None, None, None, None)),
    ("Movie 14A", (UnitKind.MOVIE, None, None, None, None)),
    ("Film", (UnitKind.MOVIE, None, None, None, None)),
    ("Movie short", (UnitKind.SPECIAL, None, None, None, None)),
    ("Short", (UnitKind.SPECIAL, None, None, None, None)),
    ("OVA", (UnitKind.SPECIAL, None, None, None, None)),
    ("OVA collection", (UnitKind.SPECIAL, None, None, None, None)),
    ("TV Special", (UnitKind.SPECIAL, None, None, None, None)),
    ("TV Special 1", (UnitKind.SPECIAL, None, None, None, None)),
    ("Episode IV", (UnitKind.UNKNOWN, None, None, None, None)),
    ("Mar 1938 - Anschluss", (UnitKind.UNKNOWN, None, None, None, None)),
    # Misc_Movies leaves the cell empty on a film row and Misc_Anime on a series row. With no type
    # cell the parse falls to `movie`, and it says so in its note rather than claiming certainty.
    ("", (UnitKind.MOVIE, None, None, None, None)),
)


def _unit_keys(detail: CategoryDetail) -> list[str]:
    return [column.key for column in detail.columns if _collapsed(column.label) in UNIT_HEADERS]


def _collapsed(label: str) -> str:
    return " ".join(normalize_header(label).split())


def _unit_cells(detail: CategoryDetail) -> list[str]:
    return [row.cells.get(key, "") for row in detail.rows for key in _unit_keys(detail)]


def _library_unit_cells(library: Path) -> frozenset[str]:
    """Every distinct span cell in the copied library, folded the way the parser folds one."""
    return frozenset(
        normalise_unit(cell)
        for facts in every_workbook()
        for cell in _unit_cells(read_category(facts.copied_into(library)))
    )


@pytest.mark.parametrize(
    ("raw", "expected", "note"),
    [
        ("", (UnitKind.MOVIE, None, None, None, None, BLANK_UNIT_CONFIDENCE), BLANK_UNIT_NOTE),
        ("Movie", (UnitKind.MOVIE, None, None, None, None, MOVIE_CONFIDENCE), ""),
        ("Movie 1", (UnitKind.MOVIE, None, None, None, None, MOVIE_CONFIDENCE), ""),
        ("Film", (UnitKind.MOVIE, None, None, None, None, MOVIE_CONFIDENCE), ""),
        ("Movie short", (UnitKind.SPECIAL, None, None, None, None, SHORT_CONFIDENCE), SHORT_NOTE),
        ("Short", (UnitKind.SPECIAL, None, None, None, None, SHORT_CONFIDENCE), SHORT_NOTE),
        ("OVA", (UnitKind.SPECIAL, None, None, None, None, SPECIAL_CONFIDENCE), SPECIAL_NOTE),
        ("OVA collection", (UnitKind.SPECIAL, None, None, None, None, SPECIAL_CONFIDENCE), SPECIAL_NOTE),
        ("Special", (UnitKind.SPECIAL, None, None, None, None, SPECIAL_CONFIDENCE), SPECIAL_NOTE),
        ("TV Special", (UnitKind.SPECIAL, None, None, None, None, SPECIAL_CONFIDENCE), SPECIAL_NOTE),
        ("E19–53", (UnitKind.EPISODES, ABSOLUTE_ORDER, 19, 53, None, EPISODE_CONFIDENCE), ABSOLUTE_ASSUMED_NOTE),
        ("E19-53", (UnitKind.EPISODES, ABSOLUTE_ORDER, 19, 53, None, EPISODE_CONFIDENCE), ABSOLUTE_ASSUMED_NOTE),
        ("E19—53", (UnitKind.EPISODES, ABSOLUTE_ORDER, 19, 53, None, EPISODE_CONFIDENCE), ABSOLUTE_ASSUMED_NOTE),
        ("Ep 19–53", (UnitKind.EPISODES, ABSOLUTE_ORDER, 19, 53, None, EPISODE_CONFIDENCE), ABSOLUTE_ASSUMED_NOTE),
        (
            "Episodes 19–53",
            (UnitKind.EPISODES, ABSOLUTE_ORDER, 19, 53, None, EPISODE_CONFIDENCE),
            ABSOLUTE_ASSUMED_NOTE,
        ),
        ("E5", (UnitKind.EPISODES, ABSOLUTE_ORDER, 5, 5, None, EPISODE_CONFIDENCE), ABSOLUTE_ASSUMED_NOTE),
        ("Episode 5", (UnitKind.EPISODES, ABSOLUTE_ORDER, 5, 5, None, EPISODE_CONFIDENCE), ABSOLUTE_ASSUMED_NOTE),
        ("Season 1", (UnitKind.SEASON, None, None, None, 1, SEASON_CONFIDENCE), SEASON_NOTE),
        ("S1", (UnitKind.SEASON, None, None, None, 1, SEASON_CONFIDENCE), SEASON_NOTE),
        ("Seasons 1–25", (UnitKind.SEASON, None, 1, 25, None, SEASON_RANGE_CONFIDENCE), SEASON_RANGE_NOTE),
        ("E53–19", (UnitKind.UNKNOWN, None, None, None, None, UNPARSED_CONFIDENCE), REVERSED_SPAN_NOTE),
        (
            "Season / Episode Block",
            (UnitKind.UNKNOWN, None, None, None, None, UNPARSED_CONFIDENCE),
            unparsed_note("Season / Episode Block"),
        ),
        ("Episode IV", (UnitKind.UNKNOWN, None, None, None, None, UNPARSED_CONFIDENCE), unparsed_note("Episode IV")),
        (
            "Arc — Alabasta",
            (UnitKind.UNKNOWN, None, None, None, None, UNPARSED_CONFIDENCE),
            unparsed_note("Arc — Alabasta"),
        ),
    ],
)
def test_the_unit_vocabulary_parses_as_documented(
    raw: str, expected: tuple[UnitKind, str | None, int | None, int | None, int | None, Decimal], note: str
) -> None:
    parse = parse_unit(raw)
    assert (
        parse.unit_kind,
        parse.order_type,
        parse.span_start,
        parse.span_end,
        parse.season_number,
        parse.confidence,
    ) == expected
    assert parse.note == note


def test_the_one_piece_row_e19_53_is_span_19_to_53_in_the_absolute_numbering(library: Path) -> None:
    detail = read_category(library / ONE_PIECE_WORKBOOK)
    matching = [cell for cell in _unit_cells(detail) if normalise_unit(cell) == ONE_PIECE_REFERENCE_UNIT]
    assert len(matching) == 1
    parse = parse_unit(matching[0])
    assert (parse.unit_kind, parse.order_type, parse.episode_span, parse.season_number) == (
        UnitKind.EPISODES,
        ABSOLUTE_ORDER,
        (19, 53),
        None,
    )
    assert parse.confidence < MOVIE_CONFIDENCE


@pytest.mark.parametrize("variant", ["E19-53", "E19–53", "E19—53", "E19‒53", "E19 – 53"])
def test_a_dash_variant_does_not_change_the_parse(variant: str) -> None:
    assert parse_unit(variant) == parse_unit("E19-53")


@pytest.mark.parametrize(
    ("raw_type", "expected_kind"),
    [
        ("", UnitKind.MOVIE),
        ("Movie", UnitKind.MOVIE),
        # Misc_Anime's 66 blank cells all carry Format "Anime", a medium rather than a shape (Akira is
        # anime and is a film), so the parser will not read them as episodic. T18 settles it at the
        # TMDB match, which is exactly what the note says.
        ("Anime", UnitKind.MOVIE),
        ("TV", UnitKind.SERIES),
        ("Series", UnitKind.SERIES),
        ("Live-action TV", UnitKind.SERIES),
    ],
)
def test_a_blank_unit_defers_its_kind_to_the_resolved_title(raw_type: str, expected_kind: UnitKind) -> None:
    parse = parse_unit("", raw_type=raw_type)
    assert parse.unit_kind is expected_kind
    assert parse.confidence == BLANK_UNIT_CONFIDENCE
    assert parse.note == BLANK_UNIT_NOTE
    assert (parse.order_type, parse.span_start, parse.span_end, parse.season_number) == (None, None, None, None)


def test_an_ambiguous_unit_refuses_rather_than_guessing() -> None:
    block = parse_unit("Season / Episode Block")
    assert block.unit_kind is UnitKind.UNKNOWN
    assert block.note
    assert parse_unit("Seasons 1–25").confidence <= Decimal("0.50")


@pytest.mark.parametrize("raw", ["E53–19", "S5 E19-10", "Seasons 25–1"])
def test_a_reversed_span_is_refused(raw: str) -> None:
    parse = parse_unit(raw)
    assert parse.unit_kind is UnitKind.UNKNOWN
    assert parse.note == REVERSED_SPAN_NOTE
    assert parse.span_start is None
    assert parse.span_end is None


@pytest.mark.parametrize("raw", ["E0", "E0-5", "S3 E0-4"])
def test_an_episode_numbered_below_one_is_a_structural_refusal(raw: str) -> None:
    parse = parse_unit(raw)
    assert parse.unit_kind is UnitKind.UNKNOWN
    assert parse.note == BELOW_MINIMUM_NOTE


def test_season_zero_is_kept_because_it_is_the_specials_bucket() -> None:
    assert parse_unit("Season 0").season_number == 0


@pytest.mark.parametrize(
    ("raw_unit", "raw_type"),
    [("E1–18", "Movie"), ("Season 3", "Film"), ("Movie", "TV"), ("Movie", "Series"), ("S5 E10-19", "Movie")],
)
def test_unit_and_type_disagreement_is_refused_with_a_note(raw_unit: str, raw_type: str) -> None:
    parse = parse_unit(raw_unit, raw_type=raw_type)
    assert parse.unit_kind is UnitKind.UNKNOWN
    assert raw_unit in parse.note
    assert raw_type in parse.note
    assert parse.span_start is None
    assert parse.season_number is None


@pytest.mark.parametrize(
    ("raw_unit", "raw_type"),
    [("Movie", "Movie"), ("Movie 3", "Film"), ("Season 1", "TV"), ("E19–53", "TV"), ("OVA", "Movie"), ("", "")],
)
def test_a_type_cell_that_agrees_or_cannot_decide_leaves_the_parse_alone(raw_unit: str, raw_type: str) -> None:
    assert parse_unit(raw_unit, raw_type=raw_type) == parse_unit(raw_unit)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("S5 E10-19", (UnitKind.EPISODES, None, 10, 19, 5)),
        ("S3 E1-7", (UnitKind.EPISODES, None, 1, 7, 3)),
        ("Season 2 E26-37", (UnitKind.EPISODES, None, 26, 37, 2)),
        ("S8E8", (UnitKind.EPISODES, None, 8, 8, 8)),
    ],
)
def test_a_season_scoped_episode_range_names_no_numbering(raw: str, expected: Parsed) -> None:
    parse = parse_unit(raw)
    assert (parse.unit_kind, parse.order_type, parse.span_start, parse.span_end, parse.season_number) == expected
    assert parse.note == SEASON_SCOPED_NOTE
    assert parse.confidence == SEASON_CONFIDENCE


def test_a_span_is_read_through_the_property_that_matches_its_kind() -> None:
    seasons = parse_unit("Seasons 1–25")
    assert seasons.episode_span is None
    assert seasons.season_span == (1, 25)
    episodes = parse_unit("E19–53")
    assert episodes.episode_span == (19, 53)
    assert episodes.season_span is None
    scoped = parse_unit("S5 E10-19")
    assert scoped.episode_span == (10, 19)
    assert scoped.season_span is None
    bare_season = parse_unit("Season 1")
    assert bare_season.episode_span is None
    assert bare_season.season_span is None
    assert parse_unit("Movie").episode_span is None
    assert parse_unit("Movie").season_span is None


def test_a_refused_cell_echoes_a_bounded_sanitised_literal() -> None:
    long_run = parse_unit("E" + "9" * 3000)
    assert long_run.unit_kind is UnitKind.UNKNOWN
    assert len(long_run.note) == len(unparsed_note("")) + MAX_NOTE_LITERAL
    with_a_control_character = parse_unit("Movie\x00")
    assert with_a_control_character.note == unparsed_note("Movie")
    assert "\x00" not in with_a_control_character.note


def test_a_disagreement_note_echoes_a_bounded_literal() -> None:
    """A veto echoes both cells, so both are clipped exactly as a refusal's literal is."""
    # Folds to "E19 -53", so it parses as episodes and only then contradicts the type cell. A raw
    # control character cannot reach this note by any other route: one inside a unit string stops it
    # matching at all, and one inside a type cell stops it matching a veto set.
    padded = "E19" + " " * 500 + "-53"
    parse = parse_unit(padded, raw_type="Movie")
    assert parse.unit_kind is UnitKind.UNKNOWN
    assert padded not in parse.note
    assert padded[:MAX_NOTE_LITERAL] in parse.note


def test_hand_checked_library_cells_parse_as_hand_checked(library: Path) -> None:
    present = _library_unit_cells(library)
    for raw, expected in HAND_CHECKED_LIBRARY_CELLS:
        assert raw in present, f"{raw!r} is no longer a cell in the library; re-check this table by hand"
        parse = parse_unit(raw)
        assert (
            parse.unit_kind,
            parse.order_type,
            parse.span_start,
            parse.span_end,
            parse.season_number,
        ) == expected, raw


@pytest.mark.parametrize("facts", every_workbook(), ids=lambda facts: facts.category_id)
def test_every_unit_string_in_the_library_parses_without_raising_and_every_unknown_carries_a_note(
    library: Path, facts: WorkbookFacts
) -> None:
    detail = read_category(facts.copied_into(library))
    assert len(_unit_keys(detail)) == 1
    for cell in _unit_cells(detail):
        parse = parse_unit(cell)
        assert UNPARSED_CONFIDENCE <= parse.confidence <= MOVIE_CONFIDENCE
        assert (parse.unit_kind is UnitKind.UNKNOWN) == (parse.confidence == UNPARSED_CONFIDENCE)
        if parse.unit_kind is UnitKind.UNKNOWN:
            assert parse.note


@pytest.mark.parametrize("facts", every_workbook(), ids=lambda facts: facts.category_id)
def test_a_bare_episode_span_names_its_numbering_and_a_season_scoped_one_does_not(
    library: Path, facts: WorkbookFacts
) -> None:
    detail = read_category(facts.copied_into(library))
    for cell in _unit_cells(detail):
        parse = parse_unit(cell)
        if parse.unit_kind is not UnitKind.EPISODES:
            assert parse.episode_span is None
            continue
        span = parse.episode_span
        assert span is not None and span[0] <= span[1]
        # The bare `E19-53` shape reads as absolute. `S5 E10-19` names no numbering at all, because
        # the sheet's own numbers are within-season in some workbooks and series-wide in others.
        assert (parse.order_type is None) == (parse.season_number is not None)
        assert parse.order_type in (None, ABSOLUTE_ORDER)


def test_a_bare_episode_span_in_the_hand_checked_table_always_names_its_numbering() -> None:
    for raw, _ in HAND_CHECKED_LIBRARY_CELLS:
        parse = parse_unit(raw)
        if parse.unit_kind is UnitKind.EPISODES and parse.season_number is None:
            assert parse.order_type == ABSOLUTE_ORDER


def test_the_result_is_frozen() -> None:
    parse = parse_unit("Movie")
    with pytest.raises(AttributeError):
        setattr(parse, "span_start", 1)
