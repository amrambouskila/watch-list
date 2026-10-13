"""One entry of the runtime season-type list."""

from __future__ import annotations

from pydantic import Field

from tv_watchlist.models.tvdb.tvdb_payload import TvdbPayload


class TvdbSeasonType(TvdbPayload):
    """`type` is the path segment an episodes URL is built from, and it is data - never a value in the code."""

    id: int
    type: str
    name: str = ""
    alternate_name: str | None = Field(default=None, validation_alias="alternateName")
