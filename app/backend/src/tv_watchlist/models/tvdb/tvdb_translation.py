"""One language variant of a series record."""

from __future__ import annotations

from pydantic import AliasPath, Field

from tv_watchlist.models.tvdb.tvdb_payload import TvdbPayload


class TvdbTranslation(TvdbPayload):
    """The English name, which the un-suffixed endpoints do not return: their default is the original language."""

    name: str = Field(default="", validation_alias=AliasPath("data", "name"))
    overview: str | None = Field(default=None, validation_alias=AliasPath("data", "overview"))
    language: str = Field(default="", validation_alias=AliasPath("data", "language"))
    aliases: tuple[str, ...] = Field(default=(), validation_alias=AliasPath("data", "aliases"))
