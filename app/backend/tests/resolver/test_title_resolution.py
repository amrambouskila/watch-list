"""Title resolution end to end, on recorded TMDB bodies. Nothing here touches a network."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from resolution_support import a_request, a_workbook_row

from provider_fixtures import TMDB, fixture_json, fixture_response, tmdb_client_for
from tv_watchlist.data.enums import ResolutionState, UnitKind
from tv_watchlist.resolver.candidate import MatchedUnit
from tv_watchlist.resolver.resolution_request import ResolutionRequest
from tv_watchlist.resolver.title_resolution import (
    EXACT_WITH_YEAR_CONFIDENCE,
    EXACT_WITHOUT_YEAR_CONFIDENCE,
    MAX_ALTERNATIVES,
    SECOND_PASS_CONFIDENCE,
    UNRESOLVED_CONFIDENCE,
    UNUSED_YEAR_NOTE,
    WEAKER_TITLE_CONFIDENCE,
    TitleResolution,
    TitleResolver,
    resolve_title,
)
from tv_watchlist.resolver.verification import YEAR_REASON

A_SUPERMAN_PAGE = "search_movie_superman"
AN_EMPTY_TV_PAGE = "search_tv_attack_on_titan_ilses_notebook"
AN_EMPTY_MOVIE_PAGE = "search_movie_attack_on_titan_ilses_notebook"

THE_1978_SUPERMAN = 1924
THE_2025_SUPERMAN = 1061474
ATTACK_OF_THE_CLONES = 1894
THE_MARVEL_ONE_SHOT = 76122
INUYASHA = 35610
ATTACK_ON_TITAN = 1429
ONE_PIECE = 37854
A_ZOMBIE_CLONES_FILM = 1454384


def a_superman_request(raw_release: str) -> ResolutionRequest:
    return a_request(
        "Superman",
        raw_unit="Movie",
        raw_release=raw_release,
        raw_type="Movie",
        category_slug="dcu",
        category_name="DCU",
    )


async def test_the_1978_superman_row_gets_the_1978_film_not_the_2025_one() -> None:
    """The recorded page carries six films called exactly "Superman"; only the year tells them apart."""
    client, responder = tmdb_client_for(fixture_response(TMDB, A_SUPERMAN_PAGE))
    resolution = await resolve_title(client, a_superman_request("1978"))
    assert resolution.chosen is not None
    assert (resolution.chosen.tmdb_id, resolution.chosen.year) == (THE_1978_SUPERMAN, 1978)
    assert resolution.state is ResolutionState.AUTO
    assert resolution.confidence >= EXACT_WITH_YEAR_CONFIDENCE
    assert len(responder.requested) == 1


async def test_the_real_dcu_superman_row_gets_the_2025_film(library: Path) -> None:
    """The same page, the same title, the library's own cells - and the other film wins."""
    client, _ = tmdb_client_for(fixture_response(TMDB, A_SUPERMAN_PAGE))
    resolution = await resolve_title(client, a_workbook_row(library, "DCU.xlsx", "Superman"))
    assert resolution.chosen is not None
    assert resolution.chosen.tmdb_id == THE_2025_SUPERMAN
    assert resolution.confidence == EXACT_WITH_YEAR_CONFIDENCE


async def test_a_superman_row_without_a_year_is_unresolved_with_the_alternatives_listed() -> None:
    """Ruling 35: six films are called exactly "Superman" and nothing tells them apart, so nobody picks."""
    client, _ = tmdb_client_for(fixture_response(TMDB, A_SUPERMAN_PAGE))
    resolution = await resolve_title(client, a_superman_request(""))
    assert resolution.state is ResolutionState.UNRESOLVED
    assert resolution.confidence == UNRESOLVED_CONFIDENCE
    assert resolution.chosen is None
    assert resolution.title_tmdb_id is None
    assert len(resolution.alternatives) >= 2
    for alternative in resolution.alternatives:
        assert str(alternative.tmdb_id) in resolution.note


async def test_a_tie_longer_than_the_note_allows_says_how_many_it_left_out() -> None:
    client, _ = tmdb_client_for(fixture_response(TMDB, A_SUPERMAN_PAGE))
    resolution = await resolve_title(client, a_superman_request(""))
    assert len(resolution.alternatives) == MAX_ALTERNATIVES
    assert ", and 1 more" in resolution.note
    assert "6 candidates" in resolution.note


async def test_a_row_typed_tv_never_accepts_a_movie_match() -> None:
    """A film called exactly "Superman" is one search away - and a row typed TV never makes that search."""
    client, responder = tmdb_client_for(fixture_response(TMDB, AN_EMPTY_TV_PAGE))
    request = a_request(
        "Superman", raw_unit="S1", raw_release="2021", raw_type="TV", category_slug="dcu", category_name="DCU"
    )
    resolution = await resolve_title(client, request)
    assert responder.requested
    assert all("/search/movie" not in url for url in responder.requested)
    assert resolution.chosen is None
    assert resolution.state is ResolutionState.UNRESOLVED


async def test_a_movie_search_is_narrowed_by_the_year_and_a_tv_search_is_not() -> None:
    """A TV row's Release cell dates its span, not the series: Inuyasha's sheet says 2009, TMDB says 2000."""
    movie_client, movie_responder = tmdb_client_for(fixture_response(TMDB, A_SUPERMAN_PAGE))
    await resolve_title(movie_client, a_superman_request("1978"))
    assert "year=1978" in movie_responder.requested[0]

    tv_client, tv_responder = tmdb_client_for(fixture_response(TMDB, AN_EMPTY_TV_PAGE))
    await resolve_title(tv_client, a_request("Some Series", raw_unit="S1", raw_release="2009", raw_type="TV"))
    assert all("first_air_date_year" not in url for url in tv_responder.requested)


async def test_attack_of_the_clones_resolves_on_the_bare_title(library: Path) -> None:
    """The sheet writes the short title; TMDB carries the long one, and the year picks it out of three."""
    client, responder = tmdb_client_for(fixture_response(TMDB, "search_movie_attack_of_the_clones"))
    resolution = await resolve_title(client, a_workbook_row(library, "Star_Wars.xlsx", "Attack of the Clones"))
    assert resolution.chosen is not None
    assert resolution.chosen.name == "Star Wars: Episode II - Attack of the Clones"
    assert resolution.chosen.tmdb_id == ATTACK_OF_THE_CLONES
    assert resolution.state is ResolutionState.AUTO
    assert resolution.confidence == WEAKER_TITLE_CONFIDENCE
    assert len(responder.requested) == 1


async def test_the_consultant_needs_the_marvel_one_shot_template(library: Path) -> None:
    """One token is never a containment match, so the bare page resolves nothing and the template does."""
    client, responder = tmdb_client_for(
        fixture_response(TMDB, "search_movie_the_consultant"),
        fixture_response(TMDB, "search_movie_marvel_one_shot_the_consultant"),
    )
    resolution = await resolve_title(client, a_workbook_row(library, "Marvel.xlsx", "The Consultant"))
    assert resolution.chosen is not None
    assert resolution.chosen.tmdb_id == THE_MARVEL_ONE_SHOT
    assert resolution.confidence == WEAKER_TITLE_CONFIDENCE
    assert "Marvel One-Shot: The Consultant" in resolution.note
    assert len(responder.requested) == 2


async def test_inuyasha_the_final_act_is_found_as_season_2_of_the_parent(library: Path) -> None:
    client, _ = tmdb_client_for(
        fixture_response(TMDB, "search_tv_inuyasha_the_final_act"), fixture_response(TMDB, "tv_35610")
    )
    resolution = await resolve_title(client, a_workbook_row(library, "Inuyasha.xlsx", "Inuyasha: The Final Act"))
    assert resolution.chosen is not None
    assert resolution.chosen.parent_tmdb_id == INUYASHA
    assert resolution.chosen.season_number == 2
    assert resolution.chosen.episode_number is None
    assert resolution.confidence == SECOND_PASS_CONFIDENCE
    assert resolution.state is ResolutionState.AUTO
    # Ruling 33: the record describes the TITLE - the parent series, first aired 2000 - and the season it
    # matched is the descriptor beside it, not the identity.
    assert resolution.title_tmdb_id == INUYASHA
    assert resolution.chosen.title_tmdb_id == INUYASHA
    assert (resolution.chosen.name, resolution.chosen.year) == ("InuYasha", 2000)
    assert resolution.chosen.matched_unit == MatchedUnit(season_number=2, episode_number=None, name="The Final Act")
    # The unit's own TMDB id is still on the candidate, and is NOT the title's.
    assert resolution.chosen.tmdb_id != INUYASHA


def _attack_on_titan_responses() -> tuple[httpx.Response, ...]:
    """Both searches for the sheet's own title came back empty, which is why the parent is searched for."""
    return (
        fixture_response(TMDB, AN_EMPTY_MOVIE_PAGE),
        fixture_response(TMDB, AN_EMPTY_TV_PAGE),
        fixture_response(TMDB, "search_tv_attack_on_titan"),
        fixture_response(TMDB, "tv_1429"),
        fixture_response(TMDB, "tv_1429_season_0"),
    )


async def test_ilses_notebook_is_found_in_season_zero_of_attack_on_titan(library: Path) -> None:
    client, _ = tmdb_client_for(*_attack_on_titan_responses())
    row = a_workbook_row(library, "Attack_On_Titan.xlsx", "Attack on Titan: Ilse's Notebook")
    resolution = await resolve_title(client, row)
    assert resolution.chosen is not None
    assert resolution.chosen.parent_tmdb_id == ATTACK_ON_TITAN
    assert (resolution.chosen.season_number, resolution.chosen.episode_number) == (0, 7)
    assert resolution.confidence == SECOND_PASS_CONFIDENCE
    assert resolution.title_tmdb_id == ATTACK_ON_TITAN
    assert (resolution.chosen.name, resolution.chosen.year) == ("Attack on Titan", 2013)
    assert resolution.chosen.matched_unit is not None
    assert resolution.chosen.matched_unit.name == "Ilse's Notebook: Memoirs of a Recon Corps Member"


async def test_a_top_level_match_is_its_own_title(library: Path) -> None:
    """One Piece E19-53 resolves to the series itself, so the title id is the candidate's own id."""
    client, _ = tmdb_client_for(fixture_response(TMDB, "search_tv_one_piece"))
    row = a_workbook_row(library, "One_Piece.xlsx", "One Piece", unit="E19\u201353")
    resolution = await resolve_title(client, row)
    assert resolution.chosen is not None
    assert resolution.title_tmdb_id == ONE_PIECE
    assert resolution.chosen.tmdb_id == ONE_PIECE
    assert resolution.chosen.parent_tmdb_id is None
    assert resolution.chosen.matched_unit is None
    assert (resolution.chosen.season_number, resolution.chosen.episode_number) == (None, None)


async def test_a_series_whose_year_was_not_used_says_so_rather_than_claiming_there_was_none() -> None:
    """Minor 5: the row has a release year; it is its span's, so it was deliberately not used to reject."""
    client, _ = tmdb_client_for(fixture_response(TMDB, "search_tv_inuyasha_the_final_act"))
    request = a_request(
        "InuYasha", raw_unit="Season 1", raw_release="2009-10-03", raw_type="TV", category_name="Inuyasha"
    )
    resolution = await resolve_title(client, request)
    assert resolution.confidence == EXACT_WITHOUT_YEAR_CONFIDENCE
    assert UNUSED_YEAR_NOTE in resolution.note
    assert "no release year" not in resolution.note


async def test_a_positional_suffix_is_stripped_before_anything_is_searched_or_matched() -> None:
    """ "- Part 1" is an episode index, not part of the title, so it reaches neither the query nor the match."""
    client, responder = tmdb_client_for(*_attack_on_titan_responses())
    request = a_request(
        "Attack on Titan: Ilse's Notebook — Part 1",
        raw_unit="OAD 1 / E3.5",
        raw_release="2013-12-09",
        raw_type="OAD/OVA",
        category_slug="attack-on-titan",
        category_name="Attack_On_Titan",
    )
    resolution = await resolve_title(client, request)
    assert resolution.chosen is not None
    assert (resolution.chosen.season_number, resolution.chosen.episode_number) == (0, 7)
    assert all("Part" not in url for url in responder.requested)


async def test_no_row_costs_an_alternative_titles_call() -> None:
    """The dropped third pass: choosing which unmatched hit to ask needs TMDB's own order, so none is asked."""
    client, responder = tmdb_client_for(*_attack_on_titan_responses())
    await resolve_title(client, a_request("Wan Pisu", raw_type="TV", category_name="One_Piece"))
    assert all("alternative_titles" not in url for url in responder.requested)


async def test_a_blank_unit_takes_its_kind_from_the_matched_media_type() -> None:
    """Ruling 27: 66 Misc_Anime rows leave `Unit` empty, so only the TMDB match can settle movie vs series."""
    client, _ = tmdb_client_for(
        fixture_response(TMDB, AN_EMPTY_MOVIE_PAGE), fixture_response(TMDB, "search_tv_one_piece")
    )
    request = a_request(
        "One Piece", raw_unit="", raw_release="1999", raw_type="", category_slug="one-piece", category_name="One_Piece"
    )
    assert request.span.unit_kind is UnitKind.MOVIE
    resolution = await resolve_title(client, request)
    assert resolution.chosen is not None
    assert (resolution.chosen.tmdb_id, resolution.chosen.media_type) == (ONE_PIECE, "tv")
    assert resolution.unit_kind is UnitKind.SERIES


async def test_a_stated_unit_keeps_its_kind_whatever_matched() -> None:
    client, _ = tmdb_client_for(fixture_response(TMDB, A_SUPERMAN_PAGE))
    resolution = await resolve_title(client, a_superman_request("1978"))
    assert resolution.unit_kind is UnitKind.MOVIE


async def test_a_row_nothing_answers_for_is_unresolved_with_a_note() -> None:
    client, _ = tmdb_client_for(fixture_response(TMDB, AN_EMPTY_TV_PAGE))
    request = a_request("A Title No Catalogue Carries", raw_unit="Season 1", raw_type="TV")
    resolution = await resolve_title(client, request)
    assert resolution == TitleResolution(
        state=ResolutionState.UNRESOLVED,
        confidence=UNRESOLVED_CONFIDENCE,
        note=resolution.note,
        chosen=None,
        alternatives=(),
        unit_kind=UnitKind.SEASON,
    )
    assert resolution.note


async def test_an_unconfigured_client_leaves_the_row_unresolved_with_a_note() -> None:
    client, responder = tmdb_client_for(fixture_response(TMDB, A_SUPERMAN_PAGE), token=None)
    resolution = await resolve_title(client, a_superman_request("1978"))
    assert resolution.state is ResolutionState.UNRESOLVED
    assert "ProviderNotConfiguredError" in resolution.note
    assert responder.requested == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [(503, "ProviderUnavailableError"), (429, "ProviderRefusedError"), (401, "ProviderRefusedError")],
)
async def test_a_provider_outage_is_unresolved_not_an_exception(status: int, expected: str) -> None:
    client, _ = tmdb_client_for(fixture_response(TMDB, A_SUPERMAN_PAGE, status=status))
    resolution = await resolve_title(client, a_superman_request("1978"))
    assert resolution.state is ResolutionState.UNRESOLVED
    assert resolution.confidence == UNRESOLVED_CONFIDENCE
    assert expected in resolution.note
    assert resolution.chosen is None


async def test_the_resolver_class_delegates_to_the_function() -> None:
    client, _ = tmdb_client_for(fixture_response(TMDB, A_SUPERMAN_PAGE))
    through_the_class = await TitleResolver(client).resolve(a_superman_request("1978"))
    other, _ = tmdb_client_for(fixture_response(TMDB, A_SUPERMAN_PAGE))
    assert through_the_class == await resolve_title(other, a_superman_request("1978"))


def _every_happy_path() -> list[tuple[str, Callable[[], tuple[ResolutionRequest, tuple[httpx.Response, ...]]]]]:
    """Every scenario above, as (request, responses), so one test can sweep all of them."""
    return [
        ("superman 1978", lambda: (a_superman_request("1978"), (fixture_response(TMDB, A_SUPERMAN_PAGE),))),
        ("superman no year", lambda: (a_superman_request(""), (fixture_response(TMDB, A_SUPERMAN_PAGE),))),
        (
            "attack of the clones",
            lambda: (
                a_request(
                    "Attack of the Clones",
                    raw_release="2002-05-16",
                    raw_type="Movie",
                    category_slug="star-wars",
                    category_name="Star_Wars",
                ),
                (fixture_response(TMDB, "search_movie_attack_of_the_clones"),),
            ),
        ),
        (
            "the consultant",
            lambda: (
                a_request(
                    "The Consultant",
                    raw_unit="Marvel One-Shot",
                    raw_release="2011-09-13",
                    raw_type="Short",
                    category_slug="marvel",
                    category_name="Marvel",
                ),
                (
                    fixture_response(TMDB, "search_movie_the_consultant"),
                    fixture_response(TMDB, "search_movie_marvel_one_shot_the_consultant"),
                ),
            ),
        ),
        (
            "inuyasha the final act",
            lambda: (
                a_request(
                    "Inuyasha: The Final Act",
                    raw_unit="Episodes 1-26",
                    raw_release="2009-10-03",
                    raw_type="TV",
                    category_slug="inuyasha",
                    category_name="Inuyasha",
                ),
                (fixture_response(TMDB, "search_tv_inuyasha_the_final_act"), fixture_response(TMDB, "tv_35610")),
            ),
        ),
        (
            "ilse's notebook",
            lambda: (
                a_request(
                    "Attack on Titan: Ilse's Notebook",
                    raw_unit="OAD 1 / E3.5",
                    raw_release="2013-12-09",
                    raw_type="OAD/OVA",
                    category_slug="attack-on-titan",
                    category_name="Attack_On_Titan",
                ),
                _attack_on_titan_responses(),
            ),
        ),
        ("nothing found", lambda: (a_request("Nothing", raw_type="TV"), (fixture_response(TMDB, AN_EMPTY_TV_PAGE),))),
    ]


@pytest.mark.parametrize(("name", "build"), _every_happy_path(), ids=[name for name, _ in _every_happy_path()])
async def test_the_resolver_never_returns_confirmed(
    name: str, build: Callable[[], tuple[ResolutionRequest, tuple[httpx.Response, ...]]]
) -> None:
    """A human sets `confirmed` in T30. Nothing the resolver does may claim it, whatever it matched."""
    request, responses = build()
    client, _ = tmdb_client_for(*responses)
    resolution = await resolve_title(client, request)
    assert resolution.state in {ResolutionState.AUTO, ResolutionState.UNRESOLVED}
    assert resolution.state is not ResolutionState.CONFIRMED
    assert UNRESOLVED_CONFIDENCE <= resolution.confidence <= EXACT_WITH_YEAR_CONFIDENCE
    if resolution.state is ResolutionState.AUTO:
        # Every rung the resolver can award sits at or above the second pass, its lowest.
        assert resolution.confidence >= SECOND_PASS_CONFIDENCE
        assert resolution.chosen is not None
        assert resolution.title_tmdb_id == resolution.chosen.title_tmdb_id


async def test_an_exact_match_with_no_year_to_check_stops_one_rung_lower() -> None:
    """A unique exact title and nothing to confirm it with: `auto`, but never the top rung."""
    client, _ = tmdb_client_for(fixture_response(TMDB, "search_movie_attack_of_the_clones"))
    resolution = await resolve_title(client, a_request("Attack of the Zombie Clones!"))
    assert resolution.chosen is not None
    assert resolution.chosen.tmdb_id == A_ZOMBIE_CLONES_FILM
    assert resolution.confidence == EXACT_WITHOUT_YEAR_CONFIDENCE
    assert "no release year" in resolution.note


async def test_a_film_row_never_descends_into_a_series_and_says_what_it_refused() -> None:
    """The second pass is a series search, so a row that states it is a film never reaches it."""
    client, responder = tmdb_client_for(fixture_response(TMDB, A_SUPERMAN_PAGE))
    resolution = await resolve_title(client, a_superman_request("1990"))
    assert resolution.state is ResolutionState.UNRESOLVED
    assert all("/search/tv" not in url for url in responder.requested)
    assert "was refused" in resolution.note
    assert str(THE_1978_SUPERMAN) in resolution.note or str(THE_2025_SUPERMAN) in resolution.note


async def test_a_row_titled_exactly_like_its_category_has_no_parent_to_fall_back_on() -> None:
    """Neither the title's own leading segment nor the franchise name adds anything, so neither is searched."""
    client, responder = tmdb_client_for(fixture_response(TMDB, AN_EMPTY_TV_PAGE))
    request = a_request(
        "One Piece", raw_unit="E1-53", raw_type="TV", category_slug="one-piece", category_name="One_Piece"
    )
    resolution = await resolve_title(client, request)
    assert resolution.state is ResolutionState.UNRESOLVED
    assert len(responder.requested) == 1


async def test_a_parent_found_by_the_franchise_name_matches_the_whole_title_inside_it() -> None:
    """Nothing strips the parent's name here - the row never carried it - so the whole title is matched."""
    client, responder = tmdb_client_for(
        fixture_response(TMDB, "search_tv_one_piece"),
        fixture_response(TMDB, "search_tv_one_piece"),
        fixture_response(TMDB, "search_tv_one_piece"),
        fixture_response(TMDB, "tv_37854"),
        fixture_response(TMDB, "tv_37854_season_0"),
    )
    request = a_request(
        "Dead End Adventure",
        raw_unit="Season 1",
        raw_type="TV",
        category_slug="one-piece",
        category_name="One_Piece",
    )
    resolution = await resolve_title(client, request)
    assert resolution.state is ResolutionState.UNRESOLVED
    # The franchise name was searched for as a parent, and its specials bucket was read and matched nothing.
    assert sum("/search/" in url for url in responder.requested) == 3
    assert any(f"/tv/{ONE_PIECE}/season/0" in url for url in responder.requested)


async def test_the_best_of_several_parent_leads_is_the_one_the_second_pass_follows() -> None:
    """Three hits normalise to "One Piece"; the row's year is what puts the 1999 series in front."""
    client, responder = tmdb_client_for(
        fixture_response(TMDB, "search_tv_one_piece"),
        fixture_response(TMDB, "tv_37854"),
        fixture_response(TMDB, "tv_37854_season_0"),
    )
    request = a_request(
        "One Piece: Dead End Adventure",
        raw_unit="Season 1",
        raw_release="1999",
        raw_type="TV",
        category_slug="one-piece",
        category_name="One_Piece",
    )
    resolution = await resolve_title(client, request)
    assert resolution.state is ResolutionState.UNRESOLVED
    # One search only: the lead came out of the page already read, so no separate parent search was made.
    assert sum("/search/" in url for url in responder.requested) == 1
    assert any(f"/tv/{ONE_PIECE}" in url for url in responder.requested)


async def test_a_row_with_no_title_at_all_searches_only_for_its_parent_and_matches_nothing() -> None:
    client, responder = tmdb_client_for(
        fixture_response(TMDB, "search_tv_one_piece"),
        fixture_response(TMDB, "tv_37854"),
        fixture_response(TMDB, "tv_37854_season_0"),
    )
    request = a_request("", raw_unit="Season 1", raw_type="TV", category_slug="one-piece", category_name="One_Piece")
    resolution = await resolve_title(client, request)
    assert resolution.state is ResolutionState.UNRESOLVED
    # A blank title expands to no query form of its own, so the only search made is the parent's.
    assert sum("/search/" in url for url in responder.requested) == 1


async def test_a_parent_with_no_specials_bucket_is_never_asked_for_one() -> None:
    """A derived body: the recorded Attack on Titan with its season 0 removed, which many real series lack."""
    details = fixture_json(TMDB, "tv_1429")
    seasons = [season for season in details["seasons"] if season["season_number"] != 0]  # type: ignore[attr-defined]
    client, responder = tmdb_client_for(
        fixture_response(TMDB, AN_EMPTY_MOVIE_PAGE),
        fixture_response(TMDB, AN_EMPTY_TV_PAGE),
        fixture_response(TMDB, "search_tv_attack_on_titan"),
        httpx.Response(200, json=details | {"seasons": seasons}),
    )
    request = a_request(
        "Attack on Titan: Ilse's Notebook",
        raw_unit="OAD 1 / E3.5",
        raw_release="2013-12-09",
        raw_type="OAD/OVA",
        category_slug="attack-on-titan",
        category_name="Attack_On_Titan",
    )
    resolution = await resolve_title(client, request)
    assert resolution.state is ResolutionState.UNRESOLVED
    assert all("/season/" not in url for url in responder.requested)


THE_POKEMON_FIRST_MOVIE = 10228
A_POKEMON_ROW = "Pokémon: The First Movie — Mewtwo Strikes Back"


async def test_a_row_that_extends_tmdbs_film_title_resolves_on_the_year(library: Path) -> None:
    """Ruling 37, and the largest recoverable class in T31's run: TMDB leaves the subtitle off."""
    client, responder = tmdb_client_for(
        fixture_response(TMDB, "search_movie_pokemon_the_first_movie_mewtwo_strikes_back")
    )
    resolution = await resolve_title(client, a_workbook_row(library, "Pokemon.xlsx", A_POKEMON_ROW))
    assert resolution.chosen is not None
    assert resolution.chosen.tmdb_id == THE_POKEMON_FIRST_MOVIE
    assert resolution.chosen.name == "Pokémon: The First Movie"
    assert resolution.state is ResolutionState.AUTO
    assert resolution.confidence == WEAKER_TITLE_CONFIDENCE
    assert 'extends TMDB\'s "Pokémon: The First Movie"' in resolution.note
    assert len(responder.requested) == 1


@pytest.mark.parametrize(
    ("raw_release", "state", "confidence"),
    [
        ("1978-12-15", ResolutionState.AUTO, WEAKER_TITLE_CONFIDENCE),
        ("1990", ResolutionState.UNRESOLVED, UNRESOLVED_CONFIDENCE),
    ],
)
async def test_the_same_extended_title_turns_on_the_year_alone(
    raw_release: str, state: ResolutionState, confidence: Decimal
) -> None:
    """Six films are called exactly "Superman"; only the row's year says which one it is extending."""
    client, _ = tmdb_client_for(fixture_response(TMDB, A_SUPERMAN_PAGE))
    request = a_request(
        "Superman: The Movie",
        raw_unit="Movie",
        raw_release=raw_release,
        raw_type="Movie",
        category_slug="dcu",
        category_name="DCU",
    )
    resolution = await resolve_title(client, request)
    assert resolution.state is state
    assert resolution.confidence == confidence
    if state is ResolutionState.AUTO:
        assert resolution.chosen is not None
        assert resolution.chosen.tmdb_id == THE_1978_SUPERMAN
    else:
        assert YEAR_REASON in resolution.note


async def test_a_series_row_with_a_subtitle_still_goes_through_the_second_pass(library: Path) -> None:
    """Ruling 37 is films only: the series shape is a season of a parent, and resolves as one."""
    client, _ = tmdb_client_for(
        fixture_response(TMDB, "search_tv_inuyasha_the_final_act"), fixture_response(TMDB, "tv_35610")
    )
    resolution = await resolve_title(client, a_workbook_row(library, "Inuyasha.xlsx", "Inuyasha: The Final Act"))
    assert resolution.confidence == SECOND_PASS_CONFIDENCE
    assert resolution.chosen is not None
    assert resolution.chosen.matched_unit is not None
    assert resolution.chosen.matched_unit.season_number == 2
