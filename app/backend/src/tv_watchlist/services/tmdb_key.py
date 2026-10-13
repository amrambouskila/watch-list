"""The canonical TMDB pointer: `movie:603`, `tv:1399`, `tv:1399:s2:e5`.

`watch_event.tmdb_key` is the log's own identity (CLAUDE.md section 5.13). A full TMDB re-ingest rebuilds
every metadata row and every UUID with it; the log survives because it re-links on this string. So the
grammar is a contract, it is canonical in one direction only - `str(int(...))` must reproduce every
number - and both halves live here so a writer and a reader can never disagree about it.
"""

from __future__ import annotations

import re
from typing import Final

from tv_watchlist.data.enums import MediaType

KEY_SEPARATOR: Final[str] = ":"
SEASON_PREFIX: Final[str] = "s"
EPISODE_PREFIX: Final[str] = "e"

# No leading zeros: `tv:01399` and `tv:1399` would be two pointers at one episode, and a log that can
# spell a subject two ways cannot re-link on it.
_NUMBER: Final[str] = r"(?:0|[1-9][0-9]*)"
_MEDIA_TYPES: Final[str] = "|".join(sorted(member.value for member in MediaType))
_KEY: Final[re.Pattern[str]] = re.compile(
    rf"^({_MEDIA_TYPES}){KEY_SEPARATOR}({_NUMBER})"
    rf"(?:{KEY_SEPARATOR}{SEASON_PREFIX}({_NUMBER}){KEY_SEPARATOR}{EPISODE_PREFIX}({_NUMBER}))?$"
)


def tmdb_key(
    media_type: MediaType, tmdb_id: int, *, season_number: int | None = None, episode_number: int | None = None
) -> str:
    """The pointer for a work, or for one episode of one. Refuses anything it could not parse back."""
    if tmdb_id <= 0:
        raise ValueError(f"a tmdb id is positive, not {tmdb_id}")
    _reject_an_impossible_subject(media_type, season_number, episode_number)
    key = f"{media_type.value}{KEY_SEPARATOR}{tmdb_id}"
    if season_number is None or episode_number is None:
        return key
    return f"{key}{KEY_SEPARATOR}{SEASON_PREFIX}{season_number}{KEY_SEPARATOR}{EPISODE_PREFIX}{episode_number}"


def parse_tmdb_key(key: str) -> tuple[MediaType, int, int | None, int | None]:
    """The pointer read back: media type, id, and the season and episode when it names one."""
    match = _KEY.match(key)
    if match is None:
        raise ValueError(f"{key!r} is not a tmdb key")
    media_type = MediaType(match.group(1))
    season = None if match.group(3) is None else int(match.group(3))
    episode = None if match.group(4) is None else int(match.group(4))
    if media_type is MediaType.MOVIE and season is not None:
        raise ValueError(f"{key!r} is not a tmdb key: a film has no seasons")
    return media_type, int(match.group(2)), season, episode


def _reject_an_impossible_subject(media_type: MediaType, season_number: int | None, episode_number: int | None) -> None:
    """A film has no seasons, and `sN`/`eM` travel together or not at all."""
    if media_type is MediaType.MOVIE:
        if season_number is not None:
            raise ValueError("a film has no season to point at")
        if episode_number is not None:
            raise ValueError("a film has no episode to point at")
        return
    if (season_number is None) != (episode_number is None):
        raise ValueError("a season and an episode are given together, or neither is given")
    # Season 0 is the specials bucket and is a real season, so only a negative number is refused.
    if season_number is not None and season_number < 0:
        raise ValueError(f"a season number is never negative, and {season_number} is")
    if episode_number is not None and episode_number < 0:
        raise ValueError(f"an episode number is never negative, and {episode_number} is")
