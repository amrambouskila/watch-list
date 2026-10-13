"""The process-wide qBittorrent client and the lifespan that closes it (R63).

The singleton is not an optimisation. The WebUI hands back a `SID` cookie and expects it on every later
call, and that cookie lives in the `httpx.AsyncClient`'s own jar - so a client per request would log in per
request, against a server whose documented 403 is an IP ban for repeated failed logins.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from lifespan_support import run_lifespan
from tv_watchlist.api.dependencies import get_catalog, get_qbittorrent_client
from tv_watchlist.clients.qbittorrent_client import QbittorrentClient
from tv_watchlist.main import create_app


@pytest.fixture(autouse=True)
def _a_fresh_singleton_each_time() -> Iterator[None]:
    """Both caches, before and after: `create_app()` builds a catalog, and a leaked one crosses tests."""
    get_qbittorrent_client.cache_clear()
    get_catalog.cache_clear()
    yield
    get_qbittorrent_client.cache_clear()
    get_catalog.cache_clear()


def test_get_qbittorrent_client_is_a_singleton() -> None:
    assert get_qbittorrent_client() is get_qbittorrent_client()
    assert isinstance(get_qbittorrent_client(), QbittorrentClient)


def test_the_singleton_is_built_even_when_nothing_is_configured() -> None:
    """`configured` is a property of the client rather than of its absence, so the scan's qBittorrent arm
    is disabled rather than missing (CLAUDE.md 10.3, B21)."""
    client = get_qbittorrent_client()

    assert client.configured is False


async def test_the_lifespan_closes_the_pool_the_singleton_opened() -> None:
    app = create_app()
    client = get_qbittorrent_client()

    await run_lifespan(app)

    assert client.closed


async def test_the_lifespan_closes_it_only_if_built() -> None:
    """Asking for it at shutdown would pin a pool to a WebUI an app never touched.

    `currsize` is the whole observable: 0 before the lifespan and still 0 after, so the shutdown path did
    not call the singleton. The test above proves the other half - that a client which WAS built is closed.
    """
    app = create_app()
    assert get_qbittorrent_client.cache_info().currsize == 0

    await run_lifespan(app)

    assert get_qbittorrent_client.cache_info().currsize == 0
