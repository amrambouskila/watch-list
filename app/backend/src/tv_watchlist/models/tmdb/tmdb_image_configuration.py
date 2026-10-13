"""The image host and the size slugs a poster path is composed against."""

from __future__ import annotations

from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload


class TmdbImageConfiguration(TmdbPayload):
    """An artwork URL is `secure_base_url + size + file_path`: composed, never accepted from a payload."""

    base_url: str = ""
    secure_base_url: str = ""
    poster_sizes: tuple[str, ...] = ()
    backdrop_sizes: tuple[str, ...] = ()
    logo_sizes: tuple[str, ...] = ()
    still_sizes: tuple[str, ...] = ()
    profile_sizes: tuple[str, ...] = ()
