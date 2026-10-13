"""One episode, as a season's `episodes` array describes it."""

from __future__ import annotations

from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload


class TmdbEpisode(TmdbPayload):
    """`episode_number` is stored exactly as TMDB numbers it, which for anime is not `SxxEyy`."""

    id: int
    # TMDB numbers anime absolute-continuously INSIDE season buckets: One Piece season 2 runs 62-77, not
    # 1-16. So `(season_number, episode_number)` is a valid key and is NOT a human `SxxEyy` and will not
    # match a filename or a Jellyfin ParentIndexNumber/IndexNumber pair. This client stores the pair
    # verbatim and fabricates nothing; `episode_order` is where a numbering becomes a rank (CLAUDE.md 11.2).
    episode_number: int
    season_number: int
    name: str = ""
    overview: str = ""
    air_date: str | None = None
    # MINUTES, unconverted - the ingest converts once, at its own boundary.
    runtime: int | None = None
    still_path: str | None = None
    production_code: str = ""
    episode_type: str = ""
    vote_average: float | None = None
