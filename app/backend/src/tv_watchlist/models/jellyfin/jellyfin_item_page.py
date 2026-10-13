"""One page of items, the envelope every Jellyfin query answers in."""

from __future__ import annotations

from pydantic import Field

from tv_watchlist.models.jellyfin.jellyfin_item_dto import JellyfinItemDto
from tv_watchlist.models.jellyfin.jellyfin_payload import JellyfinPayload


class JellyfinItemPage(JellyfinPayload):
    """`total_record_count` is the whole result; `items` is only this page of it.

    The two together are what bounds a walk: a page shorter than the total means another `startIndex` is
    due, and a page that is empty means the walk is over whatever the total claims.
    """

    items: tuple[JellyfinItemDto, ...] = Field(alias="Items", default=())
    total_record_count: int = Field(alias="TotalRecordCount", default=0, ge=0)
    start_index: int = Field(alias="StartIndex", default=0, ge=0)
