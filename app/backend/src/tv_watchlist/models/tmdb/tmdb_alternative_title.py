"""One alternative title a region knows a work by."""

from __future__ import annotations

from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload


class TmdbAlternativeTitle(TmdbPayload):
    """`iso_3166_1` is the region, not a language; `type` is free text and is often empty."""

    iso_3166_1: str
    title: str
    type: str = ""
