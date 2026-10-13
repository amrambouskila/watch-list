"""One page of TMDB search results."""

from __future__ import annotations

from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload
from tv_watchlist.models.tmdb.tmdb_search_hit import TmdbSearchHit


class TmdbSearchPage(TmdbPayload):
    """`total_results` is the whole match count; `results` is only this page of it."""

    page: int = 1
    results: tuple[TmdbSearchHit, ...] = ()
    total_pages: int = 0
    total_results: int = 0
