"""One page of the updates feed."""

from __future__ import annotations

from pydantic import AliasPath, Field

from tv_watchlist.models.tvdb.tvdb_payload import TvdbPayload
from tv_watchlist.models.tvdb.tvdb_update import TvdbUpdate


class TvdbUpdatePage(TvdbPayload):
    """`next_url` is the field that matters: without reading it, a truncated window looks like a quiet one."""

    updates: tuple[TvdbUpdate, ...] = Field(default=(), validation_alias=AliasPath("data"))
    next_url: str | None = Field(default=None, validation_alias=AliasPath("links", "next"))
    total_items: int = Field(default=0, validation_alias=AliasPath("links", "total_items"))
    page_size: int = Field(default=0, validation_alias=AliasPath("links", "page_size"))
