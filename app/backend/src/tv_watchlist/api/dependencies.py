"""Shared FastAPI dependencies."""

from __future__ import annotations

from functools import lru_cache

from tv_watchlist.clients.jellyfin_client import JellyfinClient, build_jellyfin_client
from tv_watchlist.clients.qbittorrent_client import QbittorrentClient, build_qbittorrent_client
from tv_watchlist.config import get_settings
from tv_watchlist.data.session import get_session_factory
from tv_watchlist.ingest.runtime import IngestRuntime
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.hero_store import HeroStore


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    """Process-wide catalog, so the workbook cache is shared across requests."""
    return Catalog(get_settings())


@lru_cache(maxsize=1)
def get_hero_store() -> HeroStore:
    """Process-wide hero store, writing through the same catalog the endpoints read from."""
    return HeroStore(get_catalog(), get_settings())


@lru_cache(maxsize=1)
def get_ingest_runtime() -> IngestRuntime:
    """Process-wide ingest runtime: one HTTP client and one token bucket per upstream, closed by the lifespan.

    No route reaches this. Phase 1 keeps ingest a service and CLI concern (CLAUDE.md section 13.5); the
    singleton exists so the two pools are built once and torn down with the app rather than per pass.
    """
    return IngestRuntime.from_settings(get_settings(), get_catalog(), get_session_factory())


@lru_cache(maxsize=1)
def get_jellyfin_client() -> JellyfinClient:
    """Process-wide Jellyfin client: one connection pool to the media server, closed by the lifespan.

    Built even when nothing is configured, because `configured` is a property of the client rather than of
    its absence - an unconfigured one refuses every call before a request is built (CLAUDE.md section 10.3,
    B16). No route reaches this yet: the library sync (T49) and the stream proxy (T52) are its callers.
    """
    return build_jellyfin_client(get_settings())


@lru_cache(maxsize=1)
def get_qbittorrent_client() -> QbittorrentClient:
    """Process-wide qBittorrent client, so its cookie jar - the `SID` the login returns - is shared.

    Not an optimisation: the WebUI expects that cookie on every authenticated call, and a client per
    request would log in per request against a server whose documented 403 is an IP ban for repeated
    failed logins. Built even when nothing is configured, for the reason `get_jellyfin_client` is
    (CLAUDE.md section 10.3, B21). No route reaches this: the import scan (T64) and its route (T68) do.
    """
    return build_qbittorrent_client(get_settings())
