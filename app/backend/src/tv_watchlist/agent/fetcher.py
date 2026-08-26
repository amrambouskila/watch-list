"""Read a URL cheaply with httpx, escalating to a real browser only when visibly blocked."""

from __future__ import annotations

import httpx

from tv_watchlist.agent.constants import (
    BLOCK_STATUS_CODES,
    CHALLENGE_MARKERS,
    FETCH_TIMEOUT_SECONDS,
    FETCH_USER_AGENT,
    MAX_FETCH_BYTES,
    MAX_FETCH_CHARS,
    MAX_FETCH_REDIRECTS,
    MIN_RENDERED_CHARS,
    REDIRECT_STATUS_CODES,
)
from tv_watchlist.agent.errors import FetchFailedError
from tv_watchlist.agent.fetch_result import FetchResult, FetchTransport
from tv_watchlist.agent.html_text import html_to_text
from tv_watchlist.agent.page_reader import PageReader
from tv_watchlist.agent.url_guard import assert_public_http_url


def _capped(text: str, via: FetchTransport, *, incomplete: bool = False) -> FetchResult:
    return FetchResult(text=text[:MAX_FETCH_CHARS], via=via, truncated=incomplete or len(text) > MAX_FETCH_CHARS)


class Fetcher:
    """One URL in, page text out; owns the browser it escalates to."""

    def __init__(self, reader: PageReader, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._reader = reader
        self._transport = transport

    async def fetch(self, url: str) -> FetchResult:
        """Page text for `url`, from httpx when it works and from the browser when it does not."""
        await assert_public_http_url(url)
        cheap = await self._read_with_httpx(url)
        if cheap is not None:
            return cheap
        rendered = await self._reader.read_text(url)
        if not rendered.strip():
            raise FetchFailedError(f"{url} rendered no text in either path")
        return _capped(rendered, "chromium")

    async def aclose(self) -> None:
        """Tear down the browser this fetcher escalates to."""
        await self._reader.aclose()

    async def _read_with_httpx(self, url: str) -> FetchResult | None:
        """Page text, or None when the response is a block signal the browser should retry."""
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=False,
            headers={"User-Agent": FETCH_USER_AGENT},
            transport=self._transport,
        ) as client:
            target = url
            for _ in range(MAX_FETCH_REDIRECTS + 1):
                try:
                    async with client.stream("GET", target) as response:
                        if response.status_code in REDIRECT_STATUS_CODES:
                            location = response.headers.get("location")
                            if not location:
                                return None
                            target = str(httpx.URL(target).join(location))
                        elif response.status_code in BLOCK_STATUS_CODES:
                            return None
                        else:
                            return await _read_body(response)
                except httpx.HTTPError:
                    return None
                await assert_public_http_url(target)
        return None


async def _read_body(response: httpx.Response) -> FetchResult | None:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) >= MAX_FETCH_BYTES:
            break
    markup = bytes(body).decode(response.charset_encoding or "utf-8", errors="replace")
    lowered = markup.lower()
    if any(marker in lowered for marker in CHALLENGE_MARKERS):
        return None
    text = html_to_text(markup)
    if len(text) < MIN_RENDERED_CHARS:
        return None
    return _capped(text, "httpx", incomplete=len(body) >= MAX_FETCH_BYTES)
