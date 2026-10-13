"""The ingest's composition root: what it builds once, what it builds per pass, and what it closes."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from mock_responder import MockResponder
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lifespan_support import run_lifespan
from tv_watchlist.api.dependencies import get_catalog, get_ingest_runtime
from tv_watchlist.config import Settings
from tv_watchlist.constants import TMDB_API_BASE_URL, TMDB_REQUESTS_PER_SECOND, TVDB_API_BASE_URL
from tv_watchlist.ingest.episode_orders import EpisodeOrderIngest
from tv_watchlist.ingest.reconciler import OrderIngest
from tv_watchlist.ingest.runtime import IngestRuntime
from tv_watchlist.main import create_app
from tv_watchlist.services.catalog import Catalog

A_TOKEN = "recorded-token"  # noqa: S105 - a deliberate fake, never a credential


# The factory is only ever handed to a caller that opens a session; nothing in this file does, so a
# sentinel proves the runtime passes it through rather than using one of its own.
_NO_FACTORY = cast("async_sessionmaker[AsyncSession]", object())


@pytest.fixture
def runtime(settings: Settings, catalog: Catalog) -> IngestRuntime:
    """Built on a mock transport, so nothing here can reach a network even by accident."""
    return IngestRuntime.from_settings(
        settings, catalog, session_factory=_NO_FACTORY, transport=MockResponder().transport
    )


def test_it_builds_one_bucket_and_one_client_per_upstream(runtime: IngestRuntime) -> None:
    assert runtime.tmdb_bucket is not runtime.tvdb_bucket
    assert runtime.tmdb_http is not runtime.tvdb_http
    assert str(runtime.tmdb_http.base_url).rstrip("/") == TMDB_API_BASE_URL
    assert str(runtime.tvdb_http.base_url).rstrip("/") == TVDB_API_BASE_URL


def test_the_bucket_carries_the_upstreams_own_documented_rate(runtime: IngestRuntime) -> None:
    """One bucket shared between the two would throttle each provider by the other's budget."""
    assert runtime.tmdb_bucket._rate == TMDB_REQUESTS_PER_SECOND
    assert runtime.tvdb_bucket._rate != runtime.tmdb_bucket._rate


def test_it_keeps_the_session_factory_it_was_handed(runtime: IngestRuntime) -> None:
    assert runtime.session_factory is _NO_FACTORY


async def test_aclose_closes_both_pools(runtime: IngestRuntime) -> None:
    await runtime.aclose()

    assert runtime.tmdb_http.is_closed
    assert runtime.tvdb_http.is_closed


def test_an_unconfigured_tmdb_still_yields_a_reconciler(runtime: IngestRuntime) -> None:
    """A missing token is a disabled feature: identity, adoption and position still reconcile."""
    reconciler = runtime.reconciler(_a_session())

    assert reconciler._resolver is None
    assert reconciler._tmdb is None


def test_a_configured_tmdb_yields_a_resolver_and_an_ingest(library: Path, tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        library_dir=library,
        backup_dir=tmp_path / "backups",
        heroes_dir=tmp_path / "heroes",
        tmdb_read_access_token=SecretStr(A_TOKEN),
    )
    runtime = IngestRuntime.from_settings(
        settings, Catalog(settings), session_factory=_NO_FACTORY, transport=MockResponder().transport
    )

    reconciler = runtime.reconciler(_a_session())

    assert reconciler._resolver is not None
    assert reconciler._tmdb is not None
    # TheTVDB is configured separately, so its ingest stays absent while its two credentials do.
    assert reconciler._orders is None


def test_an_injected_order_ingest_is_used_as_given(runtime: IngestRuntime) -> None:
    sentinel = object()

    reconciler = runtime.reconciler(_a_session(), order_ingest=cast("OrderIngest", sentinel))

    assert reconciler._orders is sentinel


async def test_the_lifespan_closes_the_runtime() -> None:
    """The provider pools must not outlive the backend, exactly as Chromium and the engine must not."""
    get_ingest_runtime.cache_clear()
    get_catalog.cache_clear()
    app = create_app()
    runtime = get_ingest_runtime()

    await run_lifespan(app)

    assert runtime.tmdb_http.is_closed
    assert runtime.tvdb_http.is_closed
    get_ingest_runtime.cache_clear()
    get_catalog.cache_clear()


def _a_session() -> AsyncSession:
    """A session object that is never executed against: `reconciler()` only stores it."""
    return AsyncSession()


def test_a_configured_thetvdb_yields_an_episode_order_ingest(library: Path, tmp_path: Path) -> None:
    """Both credentials or neither: TheTVDB's login sends the subscriber PIN on every call (section 8.3)."""
    settings = Settings(
        _env_file=None,
        library_dir=library,
        backup_dir=tmp_path / "backups",
        heroes_dir=tmp_path / "heroes",
        tvdb_api_key=SecretStr("recorded-api-key"),
        tvdb_pin=SecretStr("recorded-pin"),
    )
    runtime = IngestRuntime.from_settings(
        settings, Catalog(settings), session_factory=_NO_FACTORY, transport=MockResponder().transport
    )

    reconciler = runtime.reconciler(_a_session())

    assert isinstance(reconciler._orders, EpisodeOrderIngest)


async def test_a_process_that_never_ingested_builds_no_runtime_to_close() -> None:
    """Asking for it at shutdown would open the two provider pools it is being asked to close.

    `currsize` is the whole observable: it is 0 before the lifespan and still 0 after, so the shutdown
    path did not call the singleton. The test above proves the other half - that a runtime which WAS
    built is closed.
    """
    get_ingest_runtime.cache_clear()
    get_catalog.cache_clear()
    app = create_app()
    assert get_ingest_runtime.cache_info().currsize == 0

    await run_lifespan(app)

    assert get_ingest_runtime.cache_info().currsize == 0
    get_catalog.cache_clear()
