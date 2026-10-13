from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from provider_fixtures import A_JELLYFIN_BASE_URL, A_RECORDED_JELLYFIN_KEY
from tv_watchlist.api.dependencies import get_jellyfin_client
from tv_watchlist.clients.jellyfin_client import JellyfinClient, build_jellyfin_http
from tv_watchlist.data.session import get_session
from tv_watchlist.main import create_app


class PlaybackServer:
    """A recorded-health endpoint and a controllable upstream byte response, never a real socket."""

    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        body: bytes = b"media",
        healthy: bool = True,
        configured: bool = True,
        failure: bool = False,
        stream: httpx.AsyncByteStream | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self.body = body
        self.healthy = healthy
        self.failure = failure
        self.stream = stream
        self.requests: list[httpx.Request] = []
        http = build_jellyfin_http(A_JELLYFIN_BASE_URL, transport=httpx.MockTransport(self.respond))
        self.client = JellyfinClient(
            A_JELLYFIN_BASE_URL if configured else None, SecretStr(A_RECORDED_JELLYFIN_KEY), http=http
        )

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200 if self.healthy else 503, text="Healthy")
        if self.failure:
            raise httpx.ConnectError(f"connection failed {A_RECORDED_JELLYFIN_KEY}", request=request)
        if self.stream is not None:
            return httpx.Response(self.status, headers=self.headers, stream=self.stream)
        return httpx.Response(self.status, headers=self.headers, content=self.body)

    @asynccontextmanager
    async def wired(self, session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
        app = create_app()
        app.dependency_overrides[get_jellyfin_client] = lambda: self.client
        app.dependency_overrides[get_session] = lambda: session
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                yield client
        finally:
            await self.client.aclose()
