"""The other services' ids for one TMDB entity."""

from __future__ import annotations

from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload


class TmdbExternalIds(TmdbPayload):
    """`tvdb_id` is how a title reaches TheTVDB: its own search ranks the One Piece anime eighth."""

    id: int | None = None
    imdb_id: str | None = None
    tvdb_id: int | None = None
    tvrage_id: int | None = None
    wikidata_id: str | None = None
