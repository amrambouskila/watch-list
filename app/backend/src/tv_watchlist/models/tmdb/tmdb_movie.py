"""One film, as `GET /3/movie/{id}` describes it."""

from __future__ import annotations

from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload


class TmdbMovie(TmdbPayload):
    """`runtime` is whole MINUTES, exactly as TMDB sends it."""

    id: int
    title: str
    original_title: str = ""
    overview: str = ""
    # A string, not a `date`: TMDB sends "" for an unreleased or undated film (see TmdbSearchHit).
    release_date: str | None = None
    # MINUTES, and deliberately not converted here. The ingest multiplies by 60 once, at its own
    # boundary, so `runtime_seconds` is the only duration the schema ever holds (CLAUDE.md section 11.2).
    runtime: int | None = None
    status: str = ""
    original_language: str = ""
    origin_country: tuple[str, ...] = ()
    imdb_id: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    adult: bool | None = None
