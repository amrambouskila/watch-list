"""One page of one ordering."""

from __future__ import annotations

from pydantic import AliasPath, Field

from tv_watchlist.models.tvdb.tvdb_episode import TvdbEpisode
from tv_watchlist.models.tvdb.tvdb_payload import TvdbPayload


class TvdbEpisodePage(TvdbPayload):
    """An absent or empty `episodes` array parses to `()`; what that MEANS is `TvdbEpisodesResult.known`."""

    episodes: tuple[TvdbEpisode, ...] = Field(default=(), validation_alias=AliasPath("data", "episodes"))
    next_url: str | None = Field(default=None, validation_alias=AliasPath("links", "next"))
    total_items: int = Field(default=0, validation_alias=AliasPath("links", "total_items"))
    page_size: int = Field(default=0, validation_alias=AliasPath("links", "page_size"))
