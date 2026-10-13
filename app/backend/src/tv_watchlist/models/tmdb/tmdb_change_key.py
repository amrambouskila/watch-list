"""One field of a work that the changes feed reports as having moved."""

from __future__ import annotations

from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload


class TmdbChangeKey(TmdbPayload):
    """Only the key is kept. The sibling `items[].value` is polymorphic, and nothing here may be `Any`."""

    key: str
