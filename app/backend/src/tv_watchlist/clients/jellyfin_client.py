"""The one thing in this project that talks to Jellyfin, and the only place its key is ever read.

Five facts shape this file, and each is a rule rather than a preference:

1. **The configured host IS the allowlist.** Jellyfin is a server the owner runs, so its origin is
   configuration - the only upstream address in the project that is not a constant. `agent/url_guard`
   rejects every private, loopback and link-local address by design, so it is deliberately not used here;
   the pinned base is what stands in its place, and this class exposes no method that takes a URL at all.
2. **The key travels in one header and nowhere else.** `GET /Videos/{id}/stream` would accept an
   `api_key` query parameter - the OpenAPI document declares no security on it - and this client never
   uses that form, because a credential in a URL is a credential in every log on the path. There is
   deliberately no `build_stream_url()`: a URL a caller could hold is a URL that can leak.
3. **No upstream error's TEXT is ever repeated.** Only its class name is. A key containing a CR, an LF or a
   NUL makes h11 raise `Illegal header value b'MediaBrowser Token="..."'` - an `httpx.HTTPError` whose
   message is the whole header - so interpolating `{error}` anywhere here would put the key into an
   exception a route could return and a log could keep. `type(error).__name__` is the whole rule.
4. **An unreachable Jellyfin is data, not a failure of the app.** The workbooks must open with the media
   server stopped, absent or mid-scan, so `health()` answers `False` rather than raising and every other
   call raises one `ProviderUnavailableError` on one attempt - never a retry storm (CLAUDE.md section 6.6).
5. **Jellyfin has no provider-id lookup endpoint.** There is no `?tmdbId=` filter, so the index is built
   by walking `/Items` a page at a time and reading `ProviderIds` off each row (CLAUDE.md section 20.2,
   item 1). That walk is bounded: a server that reports more records than it hands back is the shape that
   loops for ever, and a truncated index is worse than a failed one because it reads as "not in library".

This client deliberately does NOT use `clients/response_cache.py`. TMDB and TheTVDB are metered services
under caching terms; Jellyfin is a local server with its own `minDateLastSaved` cursor and no ETag
discipline, so a `sync_state` row for it would be a cursor about a cursor.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime
from http import HTTPStatus
from typing import Final

import httpx
from pydantic import SecretStr, ValidationError

from tv_watchlist.clients.configured_upstream import (
    GET,
    POST,
    UpstreamCalls,
    build_configured_http,
    unreadable_shape,
)
from tv_watchlist.clients.errors import (
    ProviderError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
)
from tv_watchlist.clients.http_guard import configured_url
from tv_watchlist.clients.streamed_response import StreamedResponse
from tv_watchlist.clients.transport import elapsed_ms_since, read_json, read_text, refusal_for
from tv_watchlist.clock import utcnow
from tv_watchlist.config import Settings
from tv_watchlist.constants import (
    JELLYFIN_AUTH_HEADER,
    JELLYFIN_AUTH_HEADER_TEMPLATE,
    JELLYFIN_ITEM_FIELDS,
    JELLYFIN_PAGE_SIZE,
    JELLYFIN_RELAYED_HEADERS,
    JELLYFIN_TIMEOUT_SECONDS,
    MAX_JELLYFIN_PAGES,
    UNCONFIGURED_UPSTREAM_BASE_URL,
)
from tv_watchlist.models.jellyfin.jellyfin_item_dto import JellyfinItemDto
from tv_watchlist.models.jellyfin.jellyfin_item_page import JellyfinItemPage

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_PROVIDER: Final[str] = "Jellyfin"

# Every path this project asks Jellyfin for. Constants, never composed from anything a caller supplied.
_ITEMS: Final[str] = "Items"
_SHOWS: Final[str] = "Shows"
_EPISODES: Final[str] = "Episodes"
_VIDEOS: Final[str] = "Videos"
_STREAM: Final[str] = "stream"
_HEALTH: Final[str] = "health"
_LIBRARY: Final[str] = "Library"
_REFRESH: Final[str] = "Refresh"

_TRUE: Final[str] = "true"
_FALSE: Final[str] = "false"
_RANGE_HEADER: Final[str] = "Range"
_ACCEPT_HEADER: Final[str] = "Accept"
_ACCEPT_MEDIA: Final[str] = "*/*"
_ACCEPT_ENCODING_HEADER: Final[str] = "Accept-Encoding"
_CONTENT_ENCODING_HEADER: Final[str] = "Content-Encoding"
_IDENTITY_ENCODING: Final[str] = "identity"
_TYPE_SEPARATOR: Final[str] = ","
_STREAMABLE: Final[frozenset[int]] = frozenset({HTTPStatus.OK, HTTPStatus.PARTIAL_CONTENT})
# One sentence for every refusal, so which of the two values is missing is never leaked by the wording and
# the check order cannot drift between the two places that make it.
_UNCONFIGURED: Final[str] = "TV_JELLYFIN_BASE_URL or TV_JELLYFIN_API_KEY is unset, so Jellyfin is disabled"


class JellyfinClient:
    """Every Jellyfin call this project makes. The `http` it is handed carries no credential; this adds it."""

    def __init__(
        self,
        base_url: str | None,
        api_key: SecretStr | None,
        *,
        http: httpx.AsyncClient,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._http = http
        self._clock = clock
        self._calls = UpstreamCalls(_LOGGER, _PROVIDER)

    @property
    def configured(self) -> bool:
        """Both a base URL and a key are present; `False` means every call refuses before a request."""
        return self._base_url is not None and self._api_key is not None

    @property
    def closed(self) -> bool:
        """Whether the pool has been shut - the lifespan's only observable, and T52's before it streams."""
        return self._http.is_closed

    async def health(self) -> bool:
        """`GET /health`: `False`, never an exception, when Jellyfin is stopped, scanning or unreachable."""
        # Not in the OpenAPI document - it is the ASP.NET health-check endpoint compose already probes, and
        # it answers plain text. The body is read only so it is bounded: a server that is not the server we
        # think it is can answer a probe with a megabyte of HTML.
        if not self.configured:
            return False
        url = self._url(_HEALTH)
        started = time.monotonic()
        status: int | None = None
        try:
            async with self._http.stream(GET, url, headers=self._headers()) as response:
                status = response.status_code
                _, raw = await read_text(response)
                healthy = status == HTTPStatus.OK
                self._calls.log(url, status, elapsed_ms_since(started), len(raw), "fresh" if healthy else "failed", GET)
                return healthy
        except (ProviderError, httpx.HTTPError) as error:
            # The one call that swallows a failure, because "is it up" already has a `False` to say so. It
            # is still logged, so an operator sees a stopped server rather than nothing at all.
            self._calls.failed(url, status, elapsed_ms_since(started), error, method=GET)
            return False

    async def items(
        self,
        *,
        include_item_types: Sequence[str],
        has_tmdb_id: bool | None = True,
        min_date_last_saved: datetime | None = None,
        start_index: int = 0,
        limit: int = JELLYFIN_PAGE_SIZE,
        fields: str = JELLYFIN_ITEM_FIELDS,
    ) -> JellyfinItemPage:
        """One page of `/Items`, recursively over the whole library."""
        # Jellyfin has NO provider-id lookup endpoint, so this paged scan is the only way to build the
        # `tmdb_id -> Jellyfin Id` index. Never assume a `?tmdbId=` filter exists.
        url = self._url(
            _ITEMS,
            recursive=_TRUE,
            includeItemTypes=_TYPE_SEPARATOR.join(include_item_types),
            hasTmdbId=_boolean(has_tmdb_id),
            fields=fields,
            startIndex=start_index,
            limit=limit,
            minDateLastSaved=None if min_date_last_saved is None else min_date_last_saved.isoformat(),
        )
        return await self._get_page(url)

    async def iter_items(
        self,
        *,
        include_item_types: Sequence[str],
        has_tmdb_id: bool | None = True,
        min_date_last_saved: datetime | None = None,
        limit: int = JELLYFIN_PAGE_SIZE,
    ) -> AsyncIterator[JellyfinItemDto]:
        """Every item the filter matches, page by page, bounded by `MAX_JELLYFIN_PAGES`."""
        # The walk stops on an empty page whatever `TotalRecordCount` claims, and RAISES rather than
        # truncating at the cap: an index that is quietly short reports the owner's own files as "not in
        # your library", which is the failure shape this project refuses most.
        start_index = 0
        for _ in range(MAX_JELLYFIN_PAGES):
            page = await self.items(
                include_item_types=include_item_types,
                has_tmdb_id=has_tmdb_id,
                min_date_last_saved=min_date_last_saved,
                start_index=start_index,
                limit=limit,
            )
            for item in page.items:
                yield item
            start_index += len(page.items)
            if not page.items or start_index >= page.total_record_count:
                return
        self._overflowed(start_index)

    async def series_episodes(self, series_id: str, *, fields: str = JELLYFIN_ITEM_FIELDS) -> JellyfinItemPage:
        """`GET /Shows/{seriesId}/Episodes` - the episode join's source (T50)."""
        # `ParentIndexNumber`, `IndexNumber` and `IndexNumberEnd` are carried VERBATIM and never
        # reinterpreted: what they mean is whatever the file naming produced.
        return await self._get_page(self._url(_SHOWS, series_id, _EPISODES, fields=fields))

    @asynccontextmanager
    async def stream(self, jellyfin_id: str, *, range_header: str | None) -> AsyncIterator[StreamedResponse]:
        """A streaming `GET /Videos/{id}/stream?static=true`, for the proxy to relay chunk by chunk (T52)."""
        # `static=true` asks for the original file rather than a transcode. What is yielded is a
        # `StreamedResponse`, not the raw one: a relay may pass on a status, three headers and a byte
        # iterator, and must never be handed an upstream `Set-Cookie` (B17).
        url = self._url(_VIDEOS, jellyfin_id, _STREAM, static=_TRUE)
        headers = self._headers()
        headers[_ACCEPT_HEADER] = _ACCEPT_MEDIA
        headers[_ACCEPT_ENCODING_HEADER] = _IDENTITY_ENCODING
        if range_header is not None:
            headers[_RANGE_HEADER] = range_header
        started = time.monotonic()
        async with AsyncExitStack() as stack:
            try:
                response = await stack.enter_async_context(self._http.stream(GET, url, headers=headers))
            except httpx.HTTPError as error:
                raise self._calls.unreachable(url, elapsed_ms_since(started), error, method=GET) from error
            if response.status_code not in _STREAMABLE:
                failure = refusal_for(response, _PROVIDER)
                self._calls.failed(url, response.status_code, elapsed_ms_since(started), failure, method=GET)
                raise failure
            # aiter_bytes decodes compressed bodies, invalidating the relayed byte length and ranges.
            if response.headers.get(_CONTENT_ENCODING_HEADER, _IDENTITY_ENCODING).strip().lower() != _IDENTITY_ENCODING:
                failure = ProviderUnavailableError("Jellyfin returned encoded media")
                self._calls.failed(url, response.status_code, elapsed_ms_since(started), failure, method=GET)
                raise failure
            self._calls.log(url, response.status_code, elapsed_ms_since(started), 0, "fresh", GET)
            # Deliberately outside the `try`. An error raised while the CALLER relays the body is the
            # caller's - reclassifying it as a provider failure here would log a second, false failure and
            # hide what actually happened. The exit stack still closes the upstream either way.
            yield _relayed(response)

    async def refresh_library(self) -> None:
        """`POST /Library/Refresh` - start a scan, so a file the owner just added can be found."""
        # No body, and the documented answer is 204. Anything else is a refusal or an outage like any other
        # call's, because a scan that silently did not start looks exactly like a library already up to date.
        url = self._url(_LIBRARY, _REFRESH)
        headers = self._headers()
        started = time.monotonic()
        status: int | None = None
        try:
            async with self._http.stream(POST, url, headers=headers) as response:
                status = response.status_code
                _, raw = await read_text(response)
                if status != HTTPStatus.NO_CONTENT:
                    raise refusal_for(response, _PROVIDER)
                self._calls.log(url, status, elapsed_ms_since(started), len(raw), "fresh", POST)
        except ProviderError as error:
            self._calls.failed(url, status, elapsed_ms_since(started), error, method=POST)
            raise
        except httpx.HTTPError as error:
            raise self._calls.unreachable(url, elapsed_ms_since(started), error, method=POST) from error

    async def aclose(self) -> None:
        """The connection pool, closed with the app; it must not outlive the process that opened it."""
        await self._http.aclose()

    async def _get_page(self, url: str) -> JellyfinItemPage:
        """One guarded, streamed GET parsed into a page; every refusal and outage lands here."""
        started = time.monotonic()
        status: int | None = None
        try:
            async with self._http.stream(GET, url, headers=self._headers()) as response:
                status = response.status_code
                if status != HTTPStatus.OK:
                    raise refusal_for(response, _PROVIDER)
                parsed, raw = await read_json(response)
                page = self._validated(parsed)
                self._calls.log(url, status, elapsed_ms_since(started), len(raw), "fresh", GET)
                return page
        except ProviderError as error:
            self._calls.failed(url, status, elapsed_ms_since(started), error, method=GET)
            raise
        except httpx.HTTPError as error:
            raise self._calls.unreachable(url, elapsed_ms_since(started), error, method=GET) from error

    def _validated(self, parsed: object) -> JellyfinItemPage:
        """The body as a page; a shape this client cannot read is an unusable answer, not a crash."""
        try:
            return JellyfinItemPage.model_validate(parsed)
        except ValidationError as error:
            raise unreadable_shape(_PROVIDER, error) from error

    def _url(self, *segments: str, **query: str | int | None) -> str:
        """A URL on the configured base, built by the shared builder and never held by anything."""
        base_url, _ = self._configuration()
        return configured_url(base_url, *segments, **query)

    def _headers(self) -> dict[str, str]:
        """The one place the key is read, and the one header it is ever written into."""
        _, api_key = self._configuration()
        return {JELLYFIN_AUTH_HEADER: JELLYFIN_AUTH_HEADER_TEMPLATE.format(token=api_key.get_secret_value())}

    def _configuration(self) -> tuple[str, SecretStr]:
        """The base and the key, or the one refusal: one check, one order, one sentence for both callers."""
        if self._base_url is None or self._api_key is None:
            raise ProviderNotConfiguredError(_UNCONFIGURED)
        return self._base_url, self._api_key

    def _overflowed(self, seen: int) -> None:
        """A walk that hit the page cap: logged as the failure it is, then raised rather than truncated."""
        failure = ProviderUnavailableError(
            f"{_PROVIDER} reported more than {MAX_JELLYFIN_PAGES} pages of items (stopped after {seen})"
        )
        self._calls.failed(self._url(_ITEMS), None, 0, failure, method=GET)
        raise failure


def _relayed(response: httpx.Response) -> StreamedResponse:
    """The upstream response narrowed to what a relay may pass on: status, three headers, and bytes."""
    return StreamedResponse(
        status_code=response.status_code,
        # An allowlist built by asking for three names, not a copy with names removed: a header nobody
        # thought about cannot slip through a list that only ever adds.
        headers={name: response.headers[name] for name in JELLYFIN_RELAYED_HEADERS if name in response.headers},
        body=response.aiter_bytes(),
    )


def _boolean(value: bool | None) -> str | None:
    """A filter Jellyfin reads as a boolean, or `None` to leave the parameter off the URL entirely."""
    if value is None:
        return None
    return _TRUE if value else _FALSE


def build_jellyfin_http(base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """The pool this client holds - the shared configured-upstream builder, at Jellyfin's own timeout."""
    return build_configured_http(base_url, timeout=JELLYFIN_TIMEOUT_SECONDS, transport=transport)


def build_jellyfin_client(settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> JellyfinClient:
    """The composition seam: both values come from settings, and neither is required for the app to boot."""
    base_url = settings.jellyfin_base_url
    # An unconfigured client still holds a pool, because `configured` is a property of the client rather
    # than of its absence. It is pinned to a loopback port nothing listens on, so even a bug that got past
    # the `configured` refusal is guarded against a dead address rather than against no base at all.
    http = build_jellyfin_http(base_url or UNCONFIGURED_UPSTREAM_BASE_URL, transport=transport)
    return JellyfinClient(base_url, settings.jellyfin_api_key, http=http)
