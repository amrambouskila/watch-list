"""What changed about one work inside a date window."""

from __future__ import annotations

from tv_watchlist.models.tmdb.tmdb_change_key import TmdbChangeKey
from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload


class TmdbChangesPage(TmdbPayload):
    """An empty `changes` means the window was quiet, which is what lets an ingest skip a refetch."""

    changes: tuple[TmdbChangeKey, ...] = ()
