"""The service-wide configuration document."""

from __future__ import annotations

from pydantic import Field

from tv_watchlist.models.tmdb.tmdb_image_configuration import TmdbImageConfiguration
from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload


class TmdbConfiguration(TmdbPayload):
    """`change_keys` names every field the changes feed can report as having moved."""

    images: TmdbImageConfiguration = Field(default_factory=TmdbImageConfiguration)
    change_keys: tuple[str, ...] = ()
