"""One result row of a TMDB search, movie or tv."""

from __future__ import annotations

from typing import Literal

from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload

# The provider's own vocabulary. `data.enums.MediaType` is the schema's, and the two meet at the T19
# ingest boundary - `clients/` and the models it parses into never import `data/`.
TmdbMediaType = Literal["movie", "tv"]


class TmdbSearchHit(TmdbPayload):
    """A movie or tv hit; a movie carries `title`/`release_date`, a series `name`/`first_air_date`."""

    id: int
    media_type: TmdbMediaType | None = None
    title: str | None = None
    name: str | None = None
    original_title: str | None = None
    original_name: str | None = None
    # Dates stay strings: TMDB sends "" for an unknown release, which no `date` field would accept, and
    # coercing here would turn a missing date into a parse failure for the whole page.
    release_date: str | None = None
    first_air_date: str | None = None
    overview: str = ""
    original_language: str = ""
    origin_country: tuple[str, ...] = ()
    genre_ids: tuple[int, ...] = ()
    popularity: float | None = None
    vote_average: float | None = None
    vote_count: int | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    adult: bool | None = None
