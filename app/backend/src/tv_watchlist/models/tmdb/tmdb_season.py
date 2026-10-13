"""One season with its episodes, as `GET /3/tv/{id}/season/{n}` describes it."""

from __future__ import annotations

from tv_watchlist.models.tmdb.tmdb_episode import TmdbEpisode
from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload


class TmdbSeason(TmdbPayload):
    """The endpoint also answers with a string `_id`; `id` is the integer one every other endpoint uses."""

    id: int
    season_number: int
    name: str = ""
    overview: str = ""
    air_date: str | None = None
    episodes: tuple[TmdbEpisode, ...] = ()
    poster_path: str | None = None
