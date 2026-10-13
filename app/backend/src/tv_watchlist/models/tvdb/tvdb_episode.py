"""One episode, as an ordering lists it."""

from __future__ import annotations

from pydantic import Field

from tv_watchlist.models.tvdb.tvdb_payload import TvdbPayload


class TvdbEpisode(TvdbPayload):
    """`number` is THIS ordering's number; `absolute_number` is the absolute one. Nothing here derives either."""

    id: int
    series_id: int = Field(default=0, validation_alias="seriesId")
    name: str | None = None
    aired: str | None = None
    # MINUTES, unconverted - the ingest converts once, at its own boundary.
    runtime: int | None = None
    overview: str | None = None
    image: str | None = None
    season_number: int = Field(default=0, validation_alias="seasonNumber")
    number: int = 0
    absolute_number: int | None = Field(default=None, validation_alias="absoluteNumber")
    last_updated: str | None = Field(default=None, validation_alias="lastUpdated")
    is_movie: int = Field(default=0, validation_alias="isMovie")
    finale_type: str | None = Field(default=None, validation_alias="finaleType")
    year: str | None = None
