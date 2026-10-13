from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, AsyncExitStack

import anyio
import httpx
from fastapi import status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.types import Receive, Scope, Send

from tv_watchlist.api.errors import payload_for
from tv_watchlist.clients.errors import ProviderError
from tv_watchlist.clients.streamed_response import StreamedResponse
from tv_watchlist.constants import DEFAULT_STREAM_CONTENT_TYPE
from tv_watchlist.data.errors import PlaybackUpstreamError


class PlaybackResponse(Response):
    """Acquire media after dependency teardown, then own it until ASGI finishes or disconnects."""

    def __init__(self, context: AbstractAsyncContextManager[StreamedResponse]) -> None:
        super().__init__(content=None)
        # The unopened upstream determines the length; this response has no empty local body to measure.
        self.raw_headers.clear()
        self._context = context

    @staticmethod
    async def _relay(upstream: StreamedResponse) -> AsyncGenerator[bytes]:
        try:
            async for chunk in upstream.body:
                yield chunk
        except (httpx.HTTPError, ProviderError, OSError) as error:
            # Headers have already gone: terminate the stream, never append an error to media bytes.
            raise PlaybackUpstreamError(type(error).__name__) from None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        stack = AsyncExitStack()
        try:
            upstream = await stack.enter_async_context(self._context)
        except (httpx.HTTPError, ProviderError, OSError) as error:
            failure = PlaybackUpstreamError(type(error).__name__)
            response = JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content=payload_for(failure),
                background=self.background,
            )
        else:
            await self._send_media(upstream, stack, scope, receive, send)
            return
        # Send outside the except block: a downstream disconnect must not chain the upstream's error.
        response.raw_headers.extend(self.raw_headers)
        await response(scope, receive, send)

    async def _send_media(
        self, upstream: StreamedResponse, stack: AsyncExitStack, scope: Scope, receive: Receive, send: Send
    ) -> None:
        chunks = self._relay(upstream)
        try:
            headers = {name.lower(): value for name, value in upstream.headers.items()}
            headers.setdefault("content-type", DEFAULT_STREAM_CONTENT_TYPE)
            headers["accept-ranges"] = "bytes"
            response = StreamingResponse(
                chunks, status_code=upstream.status_code, headers=headers, background=self.background
            )
            response.raw_headers.extend(self.raw_headers)
            await response(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    try:
                        await chunks.aclose()
                    finally:
                        await stack.aclose()
                except (httpx.HTTPError, ProviderError, OSError) as error:
                    raise PlaybackUpstreamError(type(error).__name__) from None
