"""Verification is the gate a top hit has to pass. A confidently wrong match is the worst failure shape."""

from __future__ import annotations

from decimal import Decimal

import pytest
from resolution_support import a_candidate, a_request

from tv_watchlist.models.tmdb.tmdb_search_hit import TmdbMediaType
from tv_watchlist.resolver.verification import (
    ACCEPTED_REASON,
    CONTAINED_WITHOUT_A_YEAR_REASON,
    EPISODE_COUNT_REASON,
    EXTENDED_SERIES_REASON,
    EXTENDED_WITHOUT_A_YEAR_REASON,
    RUNTIME_TOLERANCE,
    TITLE_REASON,
    TYPE_REASON,
    YEAR_REASON,
    runtime_reason,
    verify,
)

A_MOVIE_TYPE_CELL = "Movie"
A_TV_TYPE_CELL = "TV"


@pytest.mark.parametrize(
    ("raw_type", "raw_unit", "media_type", "accepted"),
    [
        (A_TV_TYPE_CELL, "Season 1", "movie", False),
        (A_TV_TYPE_CELL, "Season 1", "tv", True),
        (A_MOVIE_TYPE_CELL, "Movie", "tv", False),
        (A_MOVIE_TYPE_CELL, "Movie", "movie", True),
    ],
)
def test_type_disagreement_is_always_rejected(
    raw_type: str, raw_unit: str, media_type: TmdbMediaType, accepted: bool
) -> None:
    request = a_request("Some Work", raw_unit=raw_unit, raw_type=raw_type, raw_release="2009")
    verdict, reason = verify(request, a_candidate("Some Work", media_type=media_type, year=2009))
    assert verdict is accepted
    assert reason == (ACCEPTED_REASON if accepted else TYPE_REASON)


@pytest.mark.parametrize(
    ("expected_runtime", "candidate_runtime", "accepted"),
    [
        (142, 100, False),
        (142, 130, True),
        (142, None, True),
        (None, 100, True),
        (None, None, True),
    ],
)
def test_runtime_outside_25_percent_is_rejected_when_both_known(
    expected_runtime: int | None, candidate_runtime: int | None, accepted: bool
) -> None:
    request = a_request("Some Film", raw_release="2002", expected_runtime_minutes=expected_runtime)
    candidate = a_candidate("Some Film", year=2002, runtime_minutes=candidate_runtime)
    verdict, reason = verify(request, candidate)
    assert verdict is accepted
    assert reason == (ACCEPTED_REASON if accepted else runtime_reason(expected_runtime, candidate_runtime))


def test_the_runtime_tolerance_is_a_quarter() -> None:
    assert RUNTIME_TOLERANCE == Decimal("0.25")


def test_a_movie_whose_year_disagrees_is_rejected() -> None:
    request = a_request("Superman", raw_release="1978", raw_type=A_MOVIE_TYPE_CELL)
    verdict, reason = verify(request, a_candidate("Superman", year=2025))
    assert verdict is False
    assert reason == YEAR_REASON


def test_a_series_whose_first_air_date_predates_the_rows_span_is_not_rejected_on_the_year() -> None:
    """Inuyasha's sheet row is dated 2009; the series first aired in 2000. A TV row's year is its span's."""
    request = a_request("InuYasha", raw_unit="Episodes 1-26", raw_type=A_TV_TYPE_CELL, raw_release="2009-10-03")
    verdict, reason = verify(request, a_candidate("InuYasha", media_type="tv", year=2000))
    assert verdict is True
    assert reason == ACCEPTED_REASON


def test_a_title_that_matches_neither_the_name_nor_an_alternative_title_is_rejected() -> None:
    request = a_request("Wan Pisu")
    verdict, reason = verify(request, a_candidate("One Piece"))
    assert (verdict, reason) == (False, TITLE_REASON)
    rescued = a_candidate("One Piece", also_known_as=("Wan Pisu",))
    assert verify(request, rescued) == (True, ACCEPTED_REASON)


def test_a_containment_match_needs_the_year_to_agree() -> None:
    """ "Attack of the Clones" sits inside three TMDB titles; only the year tells them apart."""
    inside = "Star Wars: Episode II - Attack of the Clones"
    without_a_year = a_request("Attack of the Clones")
    assert verify(without_a_year, a_candidate(inside, year=2002)) == (False, CONTAINED_WITHOUT_A_YEAR_REASON)
    with_a_year = a_request("Attack of the Clones", raw_release="2002-05-16")
    assert verify(with_a_year, a_candidate(inside, year=2002)) == (True, ACCEPTED_REASON)


def test_an_episode_span_reaching_past_the_last_episode_is_rejected() -> None:
    request = a_request("Some Series", raw_unit="E1-53", raw_type=A_TV_TYPE_CELL, raw_release="1999")
    short = a_candidate("Some Series", media_type="tv", year=1999, episode_count=26)
    assert verify(request, short) == (False, EPISODE_COUNT_REASON)
    long_enough = a_candidate("Some Series", media_type="tv", year=1999, episode_count=1100)
    assert verify(request, long_enough) == (True, ACCEPTED_REASON)


def test_a_blank_unit_row_accepts_either_media_type() -> None:
    """Ruling 27: a blank `Unit` states nothing, so the matched media type is what settles the kind."""
    request = a_request("Some Work", raw_unit="", raw_type="", raw_release="2011")
    assert verify(request, a_candidate("Some Work", media_type="movie", year=2011))[0] is True
    assert verify(request, a_candidate("Some Work", media_type="tv", year=2011))[0] is True


def test_a_blank_unit_row_whose_type_cell_says_tv_still_refuses_a_film() -> None:
    """The Type cell is a statement even when the Unit cell is empty, and it binds."""
    request = a_request("Some Work", raw_unit="", raw_type=A_TV_TYPE_CELL, raw_release="2011")
    assert verify(request, a_candidate("Some Work", media_type="movie", year=2011)) == (False, TYPE_REASON)


A_SUBTITLED_FILM_ROW = "Pokémon: The First Movie — Mewtwo Strikes Back"
THE_TITLE_TMDB_CARRIES = "Pokémon: The First Movie"


def test_a_film_this_row_extends_is_accepted_when_the_years_agree() -> None:
    """Ruling 37: the catalogue leaves the subtitle off, and the year is the whole of the evidence."""
    request = a_request(A_SUBTITLED_FILM_ROW, raw_release="1998", raw_type=A_MOVIE_TYPE_CELL)
    assert verify(request, a_candidate(THE_TITLE_TMDB_CARRIES, year=1998)) == (True, ACCEPTED_REASON)


@pytest.mark.parametrize(
    ("raw_release", "candidate_year", "reason"),
    [
        ("1993", 1989, YEAR_REASON),
        ("", 1998, EXTENDED_WITHOUT_A_YEAR_REASON),
        ("1998", None, EXTENDED_WITHOUT_A_YEAR_REASON),
    ],
)
def test_a_film_this_row_extends_needs_the_years_to_agree(
    raw_release: str, candidate_year: int | None, reason: str
) -> None:
    """ "Batman: Mask of the Phantasm" (1993) must never take a 1989 "Batman", and never one with no year."""
    request = a_request("Batman: Mask of the Phantasm", raw_release=raw_release, raw_type=A_MOVIE_TYPE_CELL)
    assert verify(request, a_candidate("Batman", year=candidate_year)) == (False, reason)


def test_a_series_this_row_extends_is_never_accepted_by_that_rung() -> None:
    """The same shape over a series is one of its seasons, which only the second pass may resolve."""
    request = a_request("Inuyasha: The Final Act", raw_unit="Season 2", raw_type=A_TV_TYPE_CELL, raw_release="2009")
    verdict, reason = verify(request, a_candidate("InuYasha", media_type="tv", year=2009))
    assert (verdict, reason) == (False, EXTENDED_SERIES_REASON)
