"""One entry of a series' `seasons` array - the stub, not the episode list."""

from __future__ import annotations

from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload


class TmdbSeasonSummary(TmdbPayload):
    """`season_number` 0 is the specials bucket, which is kept: it is why `seasons` outnumbers the count."""

    id: int
    season_number: int
    name: str = ""
    overview: str = ""
    air_date: str | None = None
    episode_count: int = 0
    poster_path: str | None = None
