"""Pairing one TheTVDB ordering with the TMDB episodes already stored.

Every test here is pure: the matcher takes two sequences and returns a third, so nothing in this file
needs a database, a network or a clock. The recorded bodies are read straight off disk.

The case that decides the design is Laboon. TMDB and TheTVDB both aired it on 2001-03-21, and both also
aired something else that day, so the air-date arm cannot see it. It is the absolute-number arm that
pairs it - which is why that arm exists, and why nothing here ever falls back to position.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, timedelta
from typing import Final

import pytest

from provider_fixtures import TMDB, TVDB, fixture_json
from tv_watchlist.ingest.tvdb_matching import StoredEpisode, match_tvdb_episodes
from tv_watchlist.models.tvdb.tvdb_episode import TvdbEpisode

# One Piece, whose recorded seasons 0, 1 and 2 are the only ones this projection ever holds here.
RECORDED_SEASONS: Final[tuple[int, ...]] = (0, 1, 2)
# TMDB numbers One Piece absolute-continuously inside season buckets: season 2 runs 62-77, not 1-16.
LABOON_TMDB_EPISODE_ID: Final[int] = 1146416
LABOON_AIRED: Final[date] = date(2001, 3, 21)
LABOON_AIRED_RANK: Final[int] = 62
# Seasons 1 and 2 of the recorded slice: 61 + 16 episodes, and 39 specials that have no aired rank.
REGULAR_EPISODES: Final[int] = 77
SPECIALS: Final[int] = 39
# What each recorded ordering pairs with that slice. The specials only appear in TheTVDB's own aired
# ordering, which is the one that carries them; the other two list none.
MATCHES_BY_ORDERING: Final[dict[str, int]] = {"official": 113, "absolute": 77, "dvd": 77}
# The same recorded orderings against a projection missing One Piece's season 1. Every pair the
# absolute arm would have made across that hole is refused, so only the date arm answers.
SEASONS_WITH_A_HOLE: Final[tuple[int, ...]] = (0, 2)
MATCHES_ACROSS_A_HOLE: Final[dict[str, int]] = {"official": 45, "absolute": 9, "dvd": 9}

A_DATE: Final[date] = date(2020, 1, 1)
ANOTHER_DATE: Final[date] = date(2020, 1, 8)
A_SHARED_DATE: Final[str] = "2020-02-02"


def an_episode(
    provider_id: int,
    *,
    aired: str | None = None,
    season: int = 1,
    number: int = 1,
    absolute: int | None = None,
) -> TvdbEpisode:
    """One TheTVDB episode built through its aliases, because the model is populated by alias only."""
    return TvdbEpisode.model_validate(
        {"id": provider_id, "aired": aired, "seasonNumber": season, "number": number, "absoluteNumber": absolute}
    )


def an_episode_id(tmdb_episode_id: int) -> uuid.UUID:
    """A stand-in for the row id the projection would have minted, stable across a run."""
    return uuid.uuid5(uuid.NAMESPACE_OID, str(tmdb_episode_id))


def _recorded_episodes(season_number: int) -> list[dict[str, object]]:
    """One recorded TMDB season's episode array."""
    episodes = fixture_json(TMDB, f"tv_37854_season_{season_number}")["episodes"]
    assert isinstance(episodes, list)
    return episodes


def _tmdb_date(raw: str | None) -> date | None:
    if not raw:
        return None
    return date.fromisoformat(raw)


def stored_one_piece(seasons: tuple[int, ...] = RECORDED_SEASONS) -> tuple[StoredEpisode, ...]:
    """The recorded TMDB slice as the matcher sees it: an id, the day it aired, and its aired rank.

    The aired rank is the walk the ingest performs - `(season_number, episode_number)` ascending with
    season 0 excluded - so a special carries no rank and can only ever be paired by its air date.

    `seasons` narrows because a projection with a hole in it is the case that matters: the rank is dense
    over what is held, so a missing season slides it against TheTVDB's series-wide numbering.
    """
    recorded = [episode for season in seasons for episode in _recorded_episodes(season)]
    regular = sorted(
        (episode for episode in recorded if episode["season_number"] != 0),
        key=lambda episode: (episode["season_number"], episode["episode_number"]),
    )
    ranks = {episode["id"]: rank for rank, episode in enumerate(regular, start=1)}
    return tuple(
        StoredEpisode(
            episode_id=an_episode_id(episode["id"]),
            air_date=_tmdb_date(episode["air_date"]),
            aired_rank=ranks.get(episode["id"]),
        )
        for episode in recorded
    )


def recorded_ordering(season_type: str) -> tuple[TvdbEpisode, ...]:
    """One recorded page of one TheTVDB ordering for One Piece."""
    body = fixture_json(TVDB, f"series_81797_episodes_{season_type}_eng_page0")
    data = body["data"]
    assert isinstance(data, dict)
    return tuple(TvdbEpisode.model_validate(episode) for episode in data["episodes"])


def test_a_unique_air_date_matches_first() -> None:
    stored = (StoredEpisode(episode_id=an_episode_id(1), air_date=A_DATE, aired_rank=5),)

    result = match_tvdb_episodes((an_episode(10, aired=A_DATE.isoformat(), absolute=999),), stored)

    assert result.matched == {10: an_episode_id(1)}
    assert result.by_air_date == 1
    assert result.by_absolute_number == 0
    assert result.unmatched == ()


def test_absolute_number_breaks_a_shared_air_date() -> None:
    stored = (
        StoredEpisode(episode_id=an_episode_id(1), air_date=date.fromisoformat(A_SHARED_DATE), aired_rank=1),
        StoredEpisode(episode_id=an_episode_id(2), air_date=date.fromisoformat(A_SHARED_DATE), aired_rank=2),
    )
    ordering = (an_episode(10, aired=A_SHARED_DATE, absolute=2), an_episode(11, aired=A_SHARED_DATE, absolute=1))

    result = match_tvdb_episodes(ordering, stored)

    assert result.matched == {10: an_episode_id(2), 11: an_episode_id(1)}
    assert result.by_air_date == 0
    assert result.by_absolute_number == 2


def test_unmatched_episodes_are_counted_not_invented() -> None:
    stored = (StoredEpisode(episode_id=an_episode_id(1), air_date=A_DATE, aired_rank=1),)

    result = match_tvdb_episodes((an_episode(10, aired=ANOTHER_DATE.isoformat(), absolute=999),), stored)

    assert result.matched == {}
    assert result.unmatched == (10,)


def test_an_absolute_number_of_zero_is_never_a_match() -> None:
    # TheTVDB writes 0 for "this episode has no absolute number", and a rank is 1-based, so the two can
    # never meet. A special listed in an ordering carries exactly that zero.
    stored = (StoredEpisode(episode_id=an_episode_id(1), air_date=None, aired_rank=None),)

    result = match_tvdb_episodes((an_episode(10, aired=None, season=0, absolute=0),), stored)

    assert result.matched == {}
    assert result.unmatched == (10,)


def test_a_stored_episode_is_claimed_at_most_once() -> None:
    # `uq(episode_id, order_type, label)` makes a second claim unstorable, so the second claimant is
    # left unmatched rather than quietly overwriting the first.
    stored = (StoredEpisode(episode_id=an_episode_id(1), air_date=A_DATE, aired_rank=7),)
    # Both claimants are numbered episodes, so the class guard lets each arm reach this stored row: the
    # first takes it on the date, and the second finds it already taken.
    ordering = (an_episode(10, aired=A_DATE.isoformat(), absolute=99), an_episode(11, aired=None, absolute=7))

    result = match_tvdb_episodes(ordering, stored)

    assert result.matched == {10: an_episode_id(1)}
    assert result.unmatched == (11,)


def test_a_date_repeated_inside_the_ordering_is_not_a_match() -> None:
    stored = (StoredEpisode(episode_id=an_episode_id(1), air_date=A_DATE, aired_rank=1),)
    ordering = (an_episode(10, aired=A_DATE.isoformat()), an_episode(11, aired=A_DATE.isoformat()))

    result = match_tvdb_episodes(ordering, stored)

    assert result.matched == {}
    assert result.unmatched == (10, 11)


def test_a_date_repeated_in_the_projection_is_not_a_match() -> None:
    stored = (
        StoredEpisode(episode_id=an_episode_id(1), air_date=A_DATE, aired_rank=1),
        StoredEpisode(episode_id=an_episode_id(2), air_date=A_DATE, aired_rank=2),
    )

    result = match_tvdb_episodes((an_episode(10, aired=A_DATE.isoformat()),), stored)

    assert result.matched == {}


def test_a_special_without_an_aired_rank_can_still_match_on_its_own_date() -> None:
    stored = (StoredEpisode(episode_id=an_episode_id(1), air_date=A_DATE, aired_rank=None),)

    result = match_tvdb_episodes((an_episode(10, aired=A_DATE.isoformat(), season=0, absolute=0),), stored)

    assert result.matched == {10: an_episode_id(1)}


def test_a_numbered_episode_never_takes_a_specials_date() -> None:
    # The bug this guard exists for, in miniature: a special and a regular episode air the same day,
    # and this projection holds only one of them, so each is the only one on its own side.
    stored = (StoredEpisode(episode_id=an_episode_id(1), air_date=A_DATE, aired_rank=None),)

    result = match_tvdb_episodes((an_episode(10, aired=A_DATE.isoformat(), absolute=579),), stored)

    assert result.matched == {}
    assert result.unmatched == (10,)


def test_a_special_never_takes_a_numbered_episodes_date() -> None:
    stored = (StoredEpisode(episode_id=an_episode_id(1), air_date=A_DATE, aired_rank=4),)

    result = match_tvdb_episodes((an_episode(10, aired=A_DATE.isoformat(), season=0, absolute=0),), stored)

    assert result.matched == {}


def test_an_unparseable_air_date_is_simply_absent() -> None:
    stored = (StoredEpisode(episode_id=an_episode_id(1), air_date=A_DATE, aired_rank=1),)

    result = match_tvdb_episodes((an_episode(10, aired="not a date", absolute=1),), stored)

    assert result.matched == {10: an_episode_id(1)}
    assert result.by_absolute_number == 1


@pytest.mark.parametrize("season_type", sorted(MATCHES_BY_ORDERING))
def test_laboon_is_paired_in_every_recorded_ordering(season_type: str) -> None:
    result = match_tvdb_episodes(recorded_ordering(season_type), stored_one_piece())

    assert an_episode_id(LABOON_TMDB_EPISODE_ID) in result.matched.values()


def test_laboon_is_paired_by_its_absolute_number_because_its_air_date_is_shared() -> None:
    stored = stored_one_piece()
    shared = [episode for episode in stored if episode.air_date == LABOON_AIRED]

    result = match_tvdb_episodes(recorded_ordering("absolute"), stored)

    assert len(shared) > 1
    assert next(episode for episode in stored if episode.aired_rank == LABOON_AIRED_RANK).episode_id == an_episode_id(
        LABOON_TMDB_EPISODE_ID
    )
    assert result.matched[361955] == an_episode_id(LABOON_TMDB_EPISODE_ID)


@pytest.mark.parametrize(("season_type", "expected"), sorted(MATCHES_BY_ORDERING.items()))
def test_each_recorded_ordering_pairs_the_episodes_this_projection_actually_holds(
    season_type: str, expected: int
) -> None:
    ordering = recorded_ordering(season_type)

    result = match_tvdb_episodes(ordering, stored_one_piece())

    assert len(result.matched) == expected
    assert len(result.matched) + len(result.unmatched) == len(ordering)
    assert len(set(result.matched.values())) == len(result.matched)


def test_the_two_arms_never_disagree_on_a_recorded_ordering() -> None:
    """Where both arms answer for the same episode, they answer the same thing - on real recorded data."""
    stored = stored_one_piece()
    by_rank = {episode.aired_rank: episode.episode_id for episode in stored if episode.aired_rank is not None}
    dates = Counter(episode.air_date for episode in stored if episode.air_date is not None)
    once = {
        episode.air_date: episode.episode_id
        for episode in stored
        if episode.air_date is not None and dates[episode.air_date] == 1
    }
    ordering = recorded_ordering("official")
    aired = Counter(episode.aired for episode in ordering if episode.aired)

    both = [
        (once[date.fromisoformat(episode.aired)], by_rank[episode.absolute_number])
        for episode in ordering
        if episode.aired
        and aired[episode.aired] == 1
        and date.fromisoformat(episode.aired) in once
        and episode.absolute_number in by_rank
    ]

    assert both
    assert [pair for pair in both if pair[0] != pair[1]] == []


def test_the_recorded_slice_holds_the_counts_these_assertions_rest_on() -> None:
    stored = stored_one_piece()

    assert sum(episode.aired_rank is not None for episode in stored) == REGULAR_EPISODES
    assert sum(episode.aired_rank is None for episode in stored) == SPECIALS


def _aired_of(ordering: tuple[TvdbEpisode, ...], provider_id: int) -> date | None:
    episode = next(entry for entry in ordering if entry.id == provider_id)
    return None if not episode.aired else date.fromisoformat(episode.aired)


@pytest.mark.parametrize(("season_type", "expected"), sorted(MATCHES_ACROSS_A_HOLE.items()))
def test_a_gap_in_the_projection_pairs_nothing_across_it(season_type: str, expected: int) -> None:
    """The failure this guard exists for, on real data: 7 confidently wrong pairs per ordering.

    With One Piece's season 1 absent, our dense aired rank runs 1..16 over season 2's episodes 62-77,
    while TheTVDB's series-wide `absoluteNumber` 1..16 is its first sixteen episodes. Without the
    air-date guard the second arm paired those - seven rows per ordering, every one of them wrong and
    every one of them looking perfectly ordered on screen.
    """
    gapped = stored_one_piece(SEASONS_WITH_A_HOLE)
    days = {episode.episode_id: episode.air_date for episode in gapped}
    ordering = recorded_ordering(season_type)

    result = match_tvdb_episodes(ordering, gapped)

    assert result.by_absolute_number == 0
    assert len(result.matched) == expected
    disagreeing = [
        provider_id
        for provider_id, episode_id in result.matched.items()
        if (there := _aired_of(ordering, provider_id)) is not None
        and days[episode_id] is not None
        and abs((there - days[episode_id]).days) > 1
    ]
    assert disagreeing == []


def test_a_day_the_two_sides_disagree_about_refuses_the_absolute_pair() -> None:
    stored = (StoredEpisode(episode_id=an_episode_id(1), air_date=A_DATE, aired_rank=1),)

    result = match_tvdb_episodes((an_episode(10, aired=ANOTHER_DATE.isoformat(), absolute=1),), stored)

    assert result.matched == {}
    assert result.unmatched == (10,)


def test_a_day_that_differs_by_one_is_the_same_broadcast() -> None:
    # The two services record a broadcast in different timezones, and a late-night episode lands either
    # side of midnight.
    stored = (StoredEpisode(episode_id=an_episode_id(1), air_date=A_DATE, aired_rank=1),)
    a_day_later = an_episode(10, aired=(A_DATE + timedelta(days=1)).isoformat(), absolute=1)

    result = match_tvdb_episodes((a_day_later,), stored)

    assert result.matched == {10: an_episode_id(1)}
    assert result.by_absolute_number == 1


def test_a_side_that_does_not_know_the_day_cannot_object_to_the_absolute_pair() -> None:
    stored = (StoredEpisode(episode_id=an_episode_id(1), air_date=None, aired_rank=1),)

    result = match_tvdb_episodes((an_episode(10, aired=ANOTHER_DATE.isoformat(), absolute=1),), stored)

    assert result.matched == {10: an_episode_id(1)}
