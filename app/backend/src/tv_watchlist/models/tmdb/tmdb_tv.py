"""One series, as `GET /3/tv/{id}` describes it."""

from __future__ import annotations

from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload
from tv_watchlist.models.tmdb.tmdb_season_summary import TmdbSeasonSummary


class TmdbTv(TmdbPayload):
    """`number_of_seasons` counts the regular seasons; `seasons` also carries season 0, so it is longer."""

    id: int
    name: str
    original_name: str = ""
    overview: str = ""
    # Strings, not `date`s: TMDB sends "" for a series with no announced air date (see TmdbSearchHit).
    first_air_date: str | None = None
    last_air_date: str | None = None
    number_of_seasons: int = 0
    number_of_episodes: int = 0
    seasons: tuple[TmdbSeasonSummary, ...] = ()
    # MINUTES, unconverted - the ingest turns durations into seconds once, at its own boundary.
    episode_run_time: tuple[int, ...] = ()
    status: str = ""
    original_language: str = ""
    origin_country: tuple[str, ...] = ()
    in_production: bool | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
