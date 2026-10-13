"""The deterministic front of the resolver: what a title normalises to, and what a release cell yields."""

from __future__ import annotations

from pathlib import Path

import pytest

from library_choice import every_workbook
from tv_watchlist.resolver.match_key import (
    CROSS_CHARACTERS,
    match_key,
    normalise_title,
    release_year,
    strip_positional_suffix,
)
from tv_watchlist.workbook.reader import read_category
from tv_watchlist.workbook.schema import normalize_header

# Matched as a word within the header, not against the whole of it, so all nineteen workbooks are
# covered: `Release`, `Release Date`, `Release date / period` and `Release Status` all carry one.
RELEASE_HEADER_WORD = "release"
# Measured across every one of those columns. All three move when the workbooks do: 926 cells carry
# text, 922 of them open with a year, and the ones that do not are the library's one film with no
# release date yet.
RELEASE_CELLS_IN_LIBRARY = 926
RELEASE_YEARS_IN_LIBRARY = 922
RELEASE_CELLS_WITHOUT_A_YEAR = {"TBA"}


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Pokémon: The First Movie", "pokemon the first movie"),
        ("The Consultant", "consultant"),
        ("A New Hope", "new hope"),
        ("An Unexpected Journey", "unexpected journey"),
        ("Marvel's Agents of S.H.I.E.L.D.", "marvels agents of s h i e l d"),
        ("Spider-Man", "spider man"),
        ("  Dune   Part   Two  ", "dune part two"),
        ("The", "the"),
    ],
)
def test_match_key_folds_case_diacritics_dashes_and_articles(title: str, expected: str) -> None:
    assert normalise_title(title) == expected


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Star Wars: Episode II - Attack of the Clones", "Star Wars: Episode II – Attack of the Clones"),
        ("Star Wars: Episode II - Attack of the Clones", "Star Wars: Episode II — Attack of the Clones"),
        ("Ilse's Notebook", "Ilse’s Notebook"),
        ("Pokemon", "Pokémon"),
    ],
)
def test_dash_and_quote_variants_reach_the_same_key(left: str, right: str) -> None:
    assert normalise_title(left) == normalise_title(right)


@pytest.mark.parametrize(
    ("crossed", "spelled_out"),
    [
        ("Hunter × Hunter", "Hunter x Hunter"),
        ("Hunter × Hunter: G.I. Final", "Hunter x Hunter: G.I. Final"),
        ("Naruto × UT", "Naruto x UT"),
        # The fullwidth forms need no fold entry of their own: NFKD and casefold already reach "x".
        ("Ｈunter Ｘ Ｈunter", "Hunter x Hunter"),
        ("Hunter ｘ Hunter", "Hunter x Hunter"),
    ],
)
def test_a_multiplication_sign_reads_as_the_letter_x(crossed: str, spelled_out: str) -> None:
    assert normalise_title(crossed) == normalise_title(spelled_out)


@pytest.mark.parametrize("title", ["Hunter × Hunter", "Hunter × Hunter: G.I. Final", "Naruto × UT", "Yu-Gi-Oh! × Duel"])
def test_a_multiplication_sign_never_survives_into_a_key(title: str) -> None:
    key = match_key(title)
    assert all(character not in key for character in CROSS_CHARACTERS)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Kanał", "kanal"),
        ("Łódź", "lodz"),
        ("Øst for Paradis", "ost for paradis"),
        ("Røde Orm", "rode orm"),
        ("Ægir", "aegir"),
        ("Æon Flux", "aeon flux"),
        ("Œuvre", "oeuvre"),
        ("Cœur", "coeur"),
        ("Đường", "duong"),
        ("Đorđe", "dorde"),
        ("Þór", "thor"),
        ("Friðrik", "fridrik"),
    ],
)
def test_a_letter_nfkd_cannot_decompose_is_transliterated_whole(title: str, expected: str) -> None:
    assert normalise_title(title) == expected


@pytest.mark.parametrize(
    ("transliterated", "spelled_out"), [("Kanał", "Kanal"), ("Æon Flux", "Aeon Flux"), ("Þór", "Thor")]
)
def test_a_transliterated_letter_reaches_the_ascii_spellings_key(transliterated: str, spelled_out: str) -> None:
    assert normalise_title(transliterated) == normalise_title(spelled_out)


def test_match_key_appends_the_year_when_known() -> None:
    assert match_key("Superman", year=1978) == "superman 1978"
    assert match_key("Superman") == "superman"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Dune (2021)", "dune"),
        ("Bleach [TYBW]", "bleach"),
        ("Bleach (Thousand-Year Blood War) [cour 1]", "bleach"),
    ],
)
def test_parentheticals_are_stripped(title: str, expected: str) -> None:
    assert normalise_title(title) == expected


@pytest.mark.parametrize(("roman", "arabic"), [("Episode IV", "Episode 4"), ("Part II", "Part 2")])
def test_numerals_are_normalised_as_whole_tokens_only(roman: str, arabic: str) -> None:
    assert normalise_title(roman) == normalise_title(arabic)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("MIX", "mix"),
        ("X-Men", "x men"),
        ("I Am Groot", "i am groot"),
        ("V for Vendetta", "v for vendetta"),
        ("Batman v Superman", "batman v superman"),
        ("Blade II", "blade ii"),
    ],
)
def test_a_roman_numeral_is_only_read_as_one_after_a_positional_word(title: str, expected: str) -> None:
    assert normalise_title(title) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Ilse's Notebook — Part 1", ("Ilse's Notebook", 1)),
        ("The Pacific — Part 10", ("The Pacific", 10)),
        ("Attack on Titan: No Regrets — Part 2", ("Attack on Titan: No Regrets", 2)),
        ("Wall Sina, Goodbye Part 1", ("Wall Sina, Goodbye", 1)),
        ("No Regrets (Part 2)", ("No Regrets", 2)),
        ("No Regrets Pt. 2", ("No Regrets", 2)),
        ("  Ilse's Notebook — Part 1  ", ("Ilse's Notebook", 1)),
        ("Part 2", ("Part 2", None)),
        ("  Part 2  ", ("  Part 2  ", None)),
        ("— Part 1", ("— Part 1", None)),
        (": Part 1", (": Part 1", None)),
        ("Generation War — Parts 1–2", ("Generation War — Parts 1–2", None)),
        ("Attack on Titan Part 1: Crimson Bow and Arrow", ("Attack on Titan Part 1: Crimson Bow and Arrow", None)),
        ("Dead End Adventure", ("Dead End Adventure", None)),
    ],
)
def test_a_positional_suffix_is_stripped_and_returned(title: str, expected: tuple[str, int | None]) -> None:
    assert strip_positional_suffix(title) == expected


@pytest.mark.parametrize(
    ("raw_release", "expected"),
    [
        ("2002", 2002),
        ("1999–2000", 1999),
        ("1977-05-25", 1977),
        ("2003-10", 2003),
        ("2002–2004 JP", 2002),
        ("1998-04-04 to 1998-10-10", 1998),
        ("  2015  ", 2015),
        ("", None),
        ("TBA", None),
        ("sometime in the eighties", None),
        ("20250", None),
    ],
)
def test_release_year_reads_every_workbook_release_shape(raw_release: str, expected: int | None) -> None:
    assert release_year(raw_release) == expected


def test_every_release_cell_in_the_library_parses_to_a_year_or_nothing(library: Path) -> None:
    years: list[int | None] = []
    without_a_year: set[str] = set()
    covered: set[str] = set()
    for facts in every_workbook():
        detail = read_category(facts.copied_into(library))
        keys = [column.key for column in detail.columns if RELEASE_HEADER_WORD in normalize_header(column.label)]
        if keys:
            covered.add(facts.category_id)
        for row in detail.rows:
            for cell in (row.cells.get(key, "") for key in keys):
                if not cell:
                    continue
                year = release_year(cell)
                years.append(year)
                if year is None:
                    without_a_year.add(cell)
    # Named, not implied: a workbook quietly dropping out of this test would otherwise be invisible.
    assert covered == {facts.category_id for facts in every_workbook()}
    assert len(years) == RELEASE_CELLS_IN_LIBRARY
    assert sum(year is not None for year in years) == RELEASE_YEARS_IN_LIBRARY
    assert without_a_year == RELEASE_CELLS_WITHOUT_A_YEAR
