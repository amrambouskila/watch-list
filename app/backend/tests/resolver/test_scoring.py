"""Scoring orders candidates on title, year, type and plausibility - and on nothing else."""

from __future__ import annotations

from decimal import Decimal

import pytest
from resolution_support import a_candidate, a_request

from tv_watchlist.models.tmdb.tmdb_search_hit import TmdbSearchHit
from tv_watchlist.resolver.candidate import Candidate
from tv_watchlist.resolver.scoring import (
    MINIMUM_CONTAINED_TOKENS,
    TitleMatch,
    YearAgreement,
    leading_segments,
    score_candidate,
    title_match,
    year_agreement,
)

A_POPULAR_HIT = TmdbSearchHit(id=7, title="Superman", release_date="1978-12-14", popularity=99.5, vote_count=9000)
AN_UNPOPULAR_HIT = TmdbSearchHit(id=7, title="Superman", release_date="1978-12-14", popularity=0.1, vote_count=1)


def test_popularity_contributes_nothing_to_the_score() -> None:
    """TMDB's default order is discarded: two hits differing only in how popular they are score the same."""
    request = a_request("Superman", raw_release="1978")
    popular = Candidate.from_search_hit(A_POPULAR_HIT, "movie")
    unpopular = Candidate.from_search_hit(AN_UNPOPULAR_HIT, "movie")
    assert score_candidate(request, popular) == score_candidate(request, unpopular)


def test_a_candidate_carries_no_popularity_at_all() -> None:
    """The field is absent from `Candidate`, so no later change can start ranking by it by accident."""
    assert not hasattr(Candidate.from_search_hit(A_POPULAR_HIT, "movie"), "popularity")


@pytest.mark.parametrize(
    ("raw_release", "candidate_year", "expected"),
    [
        ("2002-05-16", 2002, YearAgreement.AGREES),
        ("2002", 2001, YearAgreement.AGREES),
        ("2002", 2003, YearAgreement.AGREES),
        ("2002", 2004, YearAgreement.DISAGREES),
        ("2002", 2000, YearAgreement.DISAGREES),
        ("", 2002, YearAgreement.UNKNOWN),
        ("2002", None, YearAgreement.UNKNOWN),
    ],
)
def test_year_within_one_scores_and_year_off_by_two_does_not(
    raw_release: str, candidate_year: int | None, expected: YearAgreement
) -> None:
    request = a_request("Attack of the Clones", raw_release=raw_release)
    candidate = a_candidate("Attack of the Clones", year=candidate_year)
    assert year_agreement(request, candidate) is expected
    # A disagreeing year sinks a candidate below one whose year is merely unknown, which in turn sits below
    # one that agrees. Compared inside one request, so the two candidates differ only in their year.
    dated = a_request("Attack of the Clones", raw_release="2002")
    by_agreement = {
        YearAgreement.AGREES: score_candidate(dated, a_candidate("Attack of the Clones", year=2002)),
        YearAgreement.UNKNOWN: score_candidate(dated, a_candidate("Attack of the Clones", year=None)),
        YearAgreement.DISAGREES: score_candidate(dated, a_candidate("Attack of the Clones", year=2010)),
    }
    assert by_agreement[YearAgreement.AGREES] > by_agreement[YearAgreement.UNKNOWN]
    assert by_agreement[YearAgreement.UNKNOWN] > by_agreement[YearAgreement.DISAGREES]


@pytest.mark.parametrize(
    ("sheet_title", "tmdb_title", "expected"),
    [
        ("Attack of the Clones", "Attack of the Clones", TitleMatch.EXACT),
        ("The Consultant", "the consultant", TitleMatch.EXACT),
        ("Spider-Man", "Spider Man", TitleMatch.EXACT),
        ("Attack of the Clones", "Star Wars: Episode II - Attack of the Clones", TitleMatch.CONTAINED),
        ("Dead End Adventure", "One Piece: Dead End Adventure", TitleMatch.CONTAINED),
        ("Inuyasha: The Final Act", "InuYasha", TitleMatch.EXTENDED),
        ("Attack on Titan: Ilse's Notebook", "Attack on Titan", TitleMatch.EXTENDED),
        ("Pokémon: The First Movie — Mewtwo Strikes Back", "Pokémon: The First Movie", TitleMatch.EXTENDED),
        ("Pokémon: The First Movie — Mewtwo Strikes Back", "Pokémon", TitleMatch.EXTENDED),
        # No marker between the two, so the row is a different work rather than that one plus a subtitle.
        ("Superman Returns", "Superman", TitleMatch.PARENT),
        ("Spider-Man Noir", "Spider", TitleMatch.PARENT),
        ("Wan Pisu", "One Piece", TitleMatch.WEAK),
        ("Superman", "Batman v Superman: Dawn of Justice", TitleMatch.WEAK),
        ("", "One Piece", TitleMatch.WEAK),
    ],
)
def test_the_title_match_names_which_way_the_two_titles_contain_each_other(
    sheet_title: str, tmdb_title: str, expected: TitleMatch
) -> None:
    assert title_match(a_request(sheet_title), a_candidate(tmdb_title)) is expected


def test_a_single_token_title_is_never_a_containment_match() -> None:
    """ "Superman" inside "Batman v Superman" is not evidence; only two tokens or more can be contained."""
    assert MINIMUM_CONTAINED_TOKENS == 2
    inside = a_candidate("Batman v Superman: Dawn of Justice", year=2016)
    assert title_match(a_request("Superman", raw_release="2016"), inside) is TitleMatch.WEAK


def test_an_alternative_title_can_carry_the_match() -> None:
    request = a_request("Wan Pisu")
    candidate = a_candidate("One Piece", media_type="tv", also_known_as=("ワンピース", "Wan Pisu"))
    assert title_match(request, candidate) is TitleMatch.EXACT


A_SUBTITLED_ROW = "Pokémon: The First Movie — Mewtwo Strikes Back"


@pytest.mark.parametrize("match", list(TitleMatch))
def test_a_stronger_title_match_always_scores_higher(match: TitleMatch) -> None:
    """EXACT > CONTAINED > EXTENDED > PARENT > WEAK is what ranks a page, so it is asserted directly."""
    request = a_request(A_SUBTITLED_ROW, raw_release="1998")
    by_match = {
        TitleMatch.EXACT: a_candidate(A_SUBTITLED_ROW, year=1998),
        TitleMatch.CONTAINED: a_candidate(f"Legend of {A_SUBTITLED_ROW}", year=1998),
        TitleMatch.EXTENDED: a_candidate("Pokémon: The First Movie", year=1998),
        # A token prefix that stops in the middle of a segment, so no marker follows it.
        TitleMatch.PARENT: a_candidate("Pokémon: The", year=1998),
        TitleMatch.WEAK: a_candidate("Something Else Entirely", year=1998),
    }
    scores = {kind: score_candidate(request, candidate) for kind, candidate in by_match.items()}
    assert title_match(request, by_match[match]) is match
    assert scores[TitleMatch.EXACT] > scores[TitleMatch.CONTAINED] > scores[TitleMatch.EXTENDED]
    assert scores[TitleMatch.EXTENDED] > scores[TitleMatch.PARENT] > scores[TitleMatch.WEAK]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Pokémon: The First Movie — Mewtwo Strikes Back", {"pokemon", "pokemon the first movie"}),
        ("Pokémon 3: The Movie — Spell of the Unown", {"pokemon 3", "pokemon 3 the movie"}),
        ("Inuyasha: The Final Act", {"inuyasha"}),
        ("Generation War – Parts 1–2", {"generation war"}),
        ("Band of Brothers - Episode 2", {"band of brothers"}),
        # A hyphen inside a word is not a marker, so the word is never cut in half.
        ("Spider-Man", set()),
        ("Attack of the Clones", set()),
    ],
)
def test_the_leading_segments_are_cut_at_every_subtitle_marker(title: str, expected: set[str]) -> None:
    assert leading_segments(title) == expected


def test_a_type_disagreement_sinks_a_candidate_below_every_agreeing_one() -> None:
    request = a_request("Inuyasha: The Final Act", raw_unit="Episodes 1-26", raw_type="TV", raw_release="2009")
    a_film = a_candidate("Inuyasha: The Final Act", media_type="movie", year=2009)
    a_series = a_candidate("Inuyasha: The Final Act", media_type="tv", year=2009)
    assert score_candidate(request, a_film) < Decimal("0")
    assert score_candidate(request, a_series) > score_candidate(request, a_film)


def test_a_runtime_and_an_episode_count_outside_the_span_sink_a_candidate() -> None:
    request = a_request("Some Film", raw_release="2002", expected_runtime_minutes=142)
    plausible = a_candidate("Some Film", year=2002, runtime_minutes=130)
    implausible = a_candidate("Some Film", year=2002, runtime_minutes=40)
    assert score_candidate(request, plausible) > score_candidate(request, implausible)

    episodes = a_request("Some Series", raw_unit="E1-53", raw_type="TV", raw_release="1999")
    enough = a_candidate("Some Series", media_type="tv", year=1999, episode_count=1100)
    too_few = a_candidate("Some Series", media_type="tv", year=1999, episode_count=12)
    assert score_candidate(request=episodes, candidate=enough) > score_candidate(request=episodes, candidate=too_few)
