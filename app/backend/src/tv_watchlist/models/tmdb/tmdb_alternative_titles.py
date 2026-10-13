"""Every alternative title one work carries."""

from __future__ import annotations

from pydantic import AliasChoices, Field

from tv_watchlist.models.tmdb.tmdb_alternative_title import TmdbAlternativeTitle
from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload


class TmdbAlternativeTitles(TmdbPayload):
    """One shape for both endpoints: `/tv/{id}` answers under `results`, `/movie/{id}` under `titles`."""

    id: int | None = None
    results: tuple[TmdbAlternativeTitle, ...] = Field(default=(), validation_alias=AliasChoices("results", "titles"))
