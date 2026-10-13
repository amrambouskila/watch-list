"""The canonical pointer `watch_event.tmdb_key` stores, and the only reader of it.

The log outlives every metadata rebuild by re-linking on this string, so its grammar is a contract:
`movie:603`, `tv:1399`, `tv:1399:s2:e5` and nothing else (CLAUDE.md section 5.13).
"""

from __future__ import annotations

import pytest

from tv_watchlist.data.enums import MediaType
from tv_watchlist.services.tmdb_key import parse_tmdb_key, tmdb_key

ROUND_TRIPS: list[tuple[str, MediaType, int, int | None, int | None]] = [
    ("movie:603", MediaType.MOVIE, 603, None, None),
    ("movie:1894", MediaType.MOVIE, 1894, None, None),
    ("tv:1399", MediaType.TV, 1399, None, None),
    ("tv:1399:s2:e5", MediaType.TV, 1399, 2, 5),
    # Season 0 is the specials bucket and is a real season, so a key must be able to name it.
    ("tv:37854:s0:e1", MediaType.TV, 37854, 0, 1),
    # The reference value the ingest test asserts: One Piece's Laboon, absolute-numbered inside season 2.
    ("tv:37854:s2:e62", MediaType.TV, 37854, 2, 62),
]

MALFORMED: list[str] = [
    "",
    "movie",
    "movie:",
    "movie:abc",
    "film:603",
    "603",
    "tv:1399:s2",
    "tv:1399:e5",
    "tv:1399:s2:e5:extra",
    "tv:1399:x2:e5",
    "tv:-1",
    # Not canonical: `str(int(...))` would not reproduce it, so two spellings would key one episode.
    "tv:01399:s2:e5",
    "movie:603:s1:e1",
    "TV:1399",
    " movie:603",
    "movie:603 ",
    "movie:6 03",
]


@pytest.mark.parametrize(
    ("key", "media_type", "tmdb_id", "season", "episode"), ROUND_TRIPS, ids=[row[0] for row in ROUND_TRIPS]
)
def test_the_pointer_round_trips(
    key: str, media_type: MediaType, tmdb_id: int, season: int | None, episode: int | None
) -> None:
    built = tmdb_key(media_type, tmdb_id, season_number=season, episode_number=episode)

    assert built == key
    assert parse_tmdb_key(built) == (media_type, tmdb_id, season, episode)


@pytest.mark.parametrize("key", MALFORMED, ids=[repr(key) for key in MALFORMED])
def test_a_malformed_pointer_is_refused(key: str) -> None:
    with pytest.raises(ValueError, match="tmdb key"):
        parse_tmdb_key(key)


def test_a_film_cannot_carry_a_season_or_an_episode() -> None:
    """A movie has no seasons, so a key that claims one is a bug in the caller, not a shape to store."""
    with pytest.raises(ValueError, match="season"):
        tmdb_key(MediaType.MOVIE, 603, season_number=1)
    with pytest.raises(ValueError, match="episode"):
        tmdb_key(MediaType.MOVIE, 603, episode_number=1)


def test_half_an_episode_pointer_is_refused() -> None:
    """`sN` and `eM` travel together: either names one episode or neither names anything."""
    with pytest.raises(ValueError, match="together"):
        tmdb_key(MediaType.TV, 1399, season_number=2)
    with pytest.raises(ValueError, match="together"):
        tmdb_key(MediaType.TV, 1399, episode_number=5)


@pytest.mark.parametrize(
    ("tmdb_id", "season", "episode"),
    [(0, None, None), (-1, None, None), (1399, -1, 5), (1399, 2, -1)],
)
def test_a_negative_or_absent_number_is_refused(tmdb_id: int, season: int | None, episode: int | None) -> None:
    with pytest.raises(ValueError, match="positive|negative"):
        tmdb_key(MediaType.TV, tmdb_id, season_number=season, episode_number=episode)
