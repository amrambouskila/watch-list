"""The ingest's composition root: what is built once per process, and what is built once per pass.

The split is the whole point. One `httpx.AsyncClient` and one `TokenBucket` per upstream live as long as
the process does, because a bucket rebuilt per call is not a rate limit and a client rebuilt per call is a
new connection pool every time (CLAUDE.md section 10.3, B10). Everything that touches the database -
the response cache, the provider clients that write cursors through it, the ingest and the reconciler -
is built around ONE session, because a cursor that committed independently would record a payload as
seen after the ingest that needed it rolled back.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tv_watchlist.clients.rate_limiter import TokenBucket
from tv_watchlist.clients.tmdb_client import TmdbClient, build_tmdb_client
from tv_watchlist.clients.transport import ACCEPT_JSON, build_provider_http
from tv_watchlist.clients.tvdb_client import TvdbClient, build_tvdb_client
from tv_watchlist.config import Settings
from tv_watchlist.constants import (
    TMDB_API_BASE_URL,
    TMDB_REQUESTS_PER_SECOND,
    TVDB_API_BASE_URL,
    TVDB_REQUESTS_PER_SECOND,
)
from tv_watchlist.ingest.episode_orders import EpisodeOrderIngest
from tv_watchlist.ingest.reconciler import OrderIngest, Reconciler
from tv_watchlist.ingest.sync_cursor import PostgresResponseCache
from tv_watchlist.ingest.tmdb_ingest import TmdbIngest
from tv_watchlist.resolver.title_resolution import TitleResolver
from tv_watchlist.services.artwork_cache import ArtworkCache
from tv_watchlist.services.catalog import Catalog

# One second's worth of calls may arrive at once; the sustained rate is the constant beside it. Small
# enough that a burst cannot outrun the provider's own window, large enough that a pass does not stutter.
_BURST_SECONDS = 1


def _bucket(rate_per_second: float) -> TokenBucket:
    return TokenBucket(rate_per_second, max(int(rate_per_second * _BURST_SECONDS), 1))


@dataclass(slots=True)
class IngestRuntime:
    """Process-wide ingest plumbing, and the per-session factories that hang off it."""

    settings: Settings
    catalog: Catalog
    session_factory: async_sessionmaker[AsyncSession]
    tmdb_http: httpx.AsyncClient
    tvdb_http: httpx.AsyncClient
    tmdb_bucket: TokenBucket
    tvdb_bucket: TokenBucket
    artwork: ArtworkCache

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        catalog: Catalog,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> IngestRuntime:
        """Build the long-lived halves. `transport` is the seam a test replays recorded bodies through."""
        return cls(
            settings=settings,
            catalog=catalog,
            session_factory=session_factory,
            tmdb_http=build_provider_http(TMDB_API_BASE_URL, headers=ACCEPT_JSON, transport=transport),
            tvdb_http=build_provider_http(TVDB_API_BASE_URL, headers=ACCEPT_JSON, transport=transport),
            # One bucket per upstream, never one shared: TMDB's budget and TheTVDB's are different
            # numbers against different services, and a shared bucket would throttle each by the other.
            tmdb_bucket=_bucket(TMDB_REQUESTS_PER_SECOND),
            tvdb_bucket=_bucket(TVDB_REQUESTS_PER_SECOND),
            artwork=ArtworkCache(settings, transport=transport),
        )

    def tmdb_client(self, session: AsyncSession) -> TmdbClient:
        """A TMDB client whose cursors are this session's, so its cache moves with this transaction."""
        return build_tmdb_client(
            self.settings, http=self.tmdb_http, bucket=self.tmdb_bucket, cache=PostgresResponseCache(session)
        )

    def tvdb_client(self, session: AsyncSession) -> TvdbClient:
        """The same, for TheTVDB. Its bearer lives a month and is held by the client, not by this class."""
        return build_tvdb_client(
            self.settings, http=self.tvdb_http, bucket=self.tvdb_bucket, cache=PostgresResponseCache(session)
        )

    def reconciler(self, session: AsyncSession, *, order_ingest: OrderIngest | None = None) -> Reconciler:
        """One pass's reconciler. The resolver, the ingest and the orders share one session apiece.

        The two providers are configured independently, and each unconfigured one is a disabled feature
        rather than a boot failure: with no TMDB token every entry stays unresolved with the reason on it
        and the rest of the pass - identity, adoption, position, soft delete - still runs; with no
        TheTVDB key a series gets TMDB's aired order and no alternates. `order_ingest` stays overridable
        so a test can hand in its own without a TheTVDB credential.
        """
        client = self.tmdb_client(session)
        tvdb = self.tvdb_client(session)
        if order_ingest is None and tvdb.configured:
            order_ingest = EpisodeOrderIngest(session, tvdb)
        return Reconciler(
            session,
            self.catalog,
            resolver=TitleResolver(client) if client.configured else None,
            tmdb_ingest=TmdbIngest(session, client, artwork=self.artwork) if client.configured else None,
            order_ingest=order_ingest,
        )

    async def aclose(self) -> None:
        """Both connection pools, closed with the app. Neither may outlive the process that opened it."""
        await self.tmdb_http.aclose()
        await self.tvdb_http.aclose()
