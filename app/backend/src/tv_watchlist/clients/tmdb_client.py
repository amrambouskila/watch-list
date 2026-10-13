"""The TMDB client: one throttled, base-pinned, conditional GET per resource, into a frozen model.

The Read Access Token travels as an `Authorization: Bearer` header and nowhere else - never `?api_key=`,
never a log line, never the browser bundle (CLAUDE.md section 10.3, B10). `None` from a details call is
not an error: it means nothing the ingest would write has changed since the cursor.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date, datetime
from http import HTTPStatus
from typing import Final, NoReturn

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from tv_watchlist.clients.errors import (
    ProviderError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
)
from tv_watchlist.clients.http_guard import provider_url
from tv_watchlist.clients.rate_limiter import TokenBucket
from tv_watchlist.clients.response_cache import CachedResponse, ResponseCache, ceiling_cutoff
from tv_watchlist.clients.transport import (
    CacheOutcome,
    Cursor,
    ProviderBody,
    elapsed_ms_since,
    log_call,
    payload_digest,
    read_json,
    refusal_for,
    unreachable,
)
from tv_watchlist.clock import utcnow
from tv_watchlist.config import Settings
from tv_watchlist.constants import TMDB_API_BASE_URL, TMDB_CACHE_CEILING_DAYS
from tv_watchlist.models.tmdb.tmdb_alternative_titles import TmdbAlternativeTitles
from tv_watchlist.models.tmdb.tmdb_changes_page import TmdbChangesPage
from tv_watchlist.models.tmdb.tmdb_configuration import TmdbConfiguration
from tv_watchlist.models.tmdb.tmdb_external_ids import TmdbExternalIds
from tv_watchlist.models.tmdb.tmdb_movie import TmdbMovie
from tv_watchlist.models.tmdb.tmdb_search_hit import TmdbMediaType
from tv_watchlist.models.tmdb.tmdb_search_page import TmdbSearchPage
from tv_watchlist.models.tmdb.tmdb_season import TmdbSeason
from tv_watchlist.models.tmdb.tmdb_tv import TmdbTv

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_SOURCE: Final[str] = "tmdb"
_PROVIDER: Final[str] = "TMDB"
# These mirror `data.enums.SyncResourceType`'s VALUES by hand, because `clients/` may not import `data/`.
# T15's cache adapter converts a string back into the enum, so a drift fails there rather than silently.
_CONFIGURATION: Final[str] = "tmdb_configuration"
_MOVIE: Final[str] = "tmdb_movie"
_TV: Final[str] = "tmdb_tv"
_SEASON: Final[str] = "tmdb_season"
_EXTERNAL_IDS: Final[str] = "tmdb_external_ids"
_ALTERNATIVE_TITLES: Final[str] = "tmdb_alternative_titles"
_CHANGES: Final[str] = "tmdb_changes"

# `GET /3/configuration` is a singleton, so its cursor needs a key rather than an id.
_CONFIGURATION_KEY: Final[str] = "configuration"


class TmdbClient:
    """Every TMDB call this project makes. The `http` it is handed carries no credential; this class adds it."""

    def __init__(
        self,
        read_access_token: SecretStr | None,
        *,
        http: httpx.AsyncClient,
        bucket: TokenBucket,
        cache: ResponseCache,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._token = read_access_token
        self._http = http
        self._bucket = bucket
        self._cache = cache
        self._clock = clock

    @property
    def configured(self) -> bool:
        """Whether a token is present. `False` means every call refuses before a request is built."""
        return self._token is not None

    async def configuration(self) -> TmdbConfiguration | None:
        """The image host and size slugs an artwork URL is composed against."""
        return await self._fetch(
            TmdbConfiguration,
            cursor=Cursor(_CONFIGURATION, _CONFIGURATION_KEY),
            url=provider_url(TMDB_API_BASE_URL, "configuration"),
        )

    async def search_movie(self, query: str, *, year: int | None = None, page: int = 1) -> TmdbSearchPage:
        """A film search. Never cached: a query is not a resource, and its answer moves with the catalogue."""
        return await self._fetch_uncached(
            TmdbSearchPage, url=provider_url(TMDB_API_BASE_URL, "search", "movie", query=query, year=year, page=page)
        )

    async def search_tv(self, query: str, *, first_air_date_year: int | None = None, page: int = 1) -> TmdbSearchPage:
        """A series search. Never cached, for the same reason `search_movie` is not."""
        return await self._fetch_uncached(
            TmdbSearchPage,
            url=provider_url(
                TMDB_API_BASE_URL, "search", "tv", query=query, first_air_date_year=first_air_date_year, page=page
            ),
        )

    async def movie_details(self, movie_id: int) -> TmdbMovie | None:
        """One film. `runtime` arrives in minutes and stays in minutes until the ingest converts it."""
        return await self._fetch(
            TmdbMovie,
            cursor=Cursor(_MOVIE, str(movie_id)),
            url=provider_url(TMDB_API_BASE_URL, "movie", movie_id),
        )

    async def tv_details(self, tv_id: int) -> TmdbTv | None:
        """One series, including the `seasons` stub array that carries season 0."""
        return await self._fetch(
            TmdbTv, cursor=Cursor(_TV, str(tv_id)), url=provider_url(TMDB_API_BASE_URL, "tv", tv_id)
        )

    async def season_details(self, tv_id: int, season_number: int) -> TmdbSeason | None:
        """One season with its episodes, numbered exactly as TMDB numbers them."""
        return await self._fetch(
            TmdbSeason,
            cursor=Cursor(_SEASON, f"{tv_id}/{season_number}"),
            url=provider_url(TMDB_API_BASE_URL, "tv", tv_id, "season", season_number),
        )

    async def external_ids(self, media_type: TmdbMediaType, tmdb_id: int) -> TmdbExternalIds | None:
        """The other services' ids, which is how a title reaches TheTVDB without searching for it."""
        return await self._fetch(
            TmdbExternalIds,
            cursor=Cursor(_EXTERNAL_IDS, f"{media_type}/{tmdb_id}"),
            url=provider_url(TMDB_API_BASE_URL, media_type, tmdb_id, "external_ids"),
        )

    async def alternative_titles(self, media_type: TmdbMediaType, tmdb_id: int) -> TmdbAlternativeTitles | None:
        """Every regional title a work carries, which is what a romaji-or-English resolution falls back on."""
        return await self._fetch(
            TmdbAlternativeTitles,
            cursor=Cursor(_ALTERNATIVE_TITLES, f"{media_type}/{tmdb_id}"),
            url=provider_url(TMDB_API_BASE_URL, media_type, tmdb_id, "alternative_titles"),
        )

    async def changes(
        self, media_type: TmdbMediaType, tmdb_id: int, *, start_date: date, end_date: date
    ) -> TmdbChangesPage | None:
        """Which fields of one work moved inside a window, so a refresh can skip the works that did not."""
        return await self._fetch(
            TmdbChangesPage,
            # The window is part of what was fetched, so it is part of the key that remembers it: two
            # windows are two cursors, and neither can answer for the other. The order is fixed rather
            # than the call's, so the same window always produces the same key.
            cursor=Cursor(
                _CHANGES, f"{media_type}/{tmdb_id}?start_date={start_date.isoformat()}&end_date={end_date.isoformat()}"
            ),
            url=provider_url(
                TMDB_API_BASE_URL,
                media_type,
                tmdb_id,
                "changes",
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            ),
        )

    async def _fetch[ModelT: BaseModel](self, model: type[ModelT], *, cursor: Cursor, url: str) -> ModelT | None:
        """A cached resource: conditional on the stored ETag, `None` when there is nothing new to write."""
        bearer = self._bearer()
        cached = await self._cache.lookup(_SOURCE, cursor.resource_type, cursor.resource_key)
        renewing = self._past_the_cache_ceiling(cached)
        etag = None if renewing or cached is None else cached.etag
        body = await self._send(url, bearer=bearer, cursor=cursor, etag=etag)
        if body is None:
            if etag is None:
                await self._rogue_304(cursor, url)
            return None
        if not renewing and cached is not None and cached.payload_digest == body.digest:
            # TMDB does not send an ETag on every endpoint, so an identical body is the other way to learn
            # that no row needs rewriting (CLAUDE.md section 9.2). The cursor is left alone: only a stored
            # write moves `last_success_at`, which is what eventually trips the six-month ceiling.
            self._log(url, HTTPStatus.OK, body, "not-modified")
            return None
        parsed = await self._validated(model, body, cursor=cursor, url=url)
        await self._cache.store(
            _SOURCE,
            cursor.resource_type,
            cursor.resource_key,
            etag=body.etag,
            last_modified=body.last_modified,
            payload_digest=body.digest,
        )
        self._log(url, HTTPStatus.OK, body, "fresh")
        return parsed

    async def _fetch_uncached[ModelT: BaseModel](self, model: type[ModelT], *, url: str) -> ModelT:
        """A query. It is throttled and logged like any call, but it writes no cursor and reads none."""
        body = await self._send(url, bearer=self._bearer(), cursor=None, etag=None)
        if body is None:
            await self._rogue_304(None, url)
        parsed = await self._validated(model, body, cursor=None, url=url)
        self._log(url, HTTPStatus.OK, body, "fresh")
        return parsed

    async def _send(self, url: str, *, bearer: str, cursor: Cursor | None, etag: str | None) -> ProviderBody | None:
        """One throttled, guarded GET. `None` is a 304; every other non-200 raises and records the failure."""
        await self._bucket.acquire()
        started = time.monotonic()
        # The credential rides in this header and in no other place: not the URL, not a query parameter,
        # and not the `http` client's defaults, so `configured` and the header cannot disagree.
        headers = {"Authorization": bearer}
        if etag is not None:
            headers["If-None-Match"] = etag
        status: int | None = None
        try:
            async with self._http.stream("GET", url, headers=headers) as response:
                status = response.status_code
                if status == HTTPStatus.NOT_MODIFIED:
                    # Only a conditional request can honestly be answered with a 304. When this call sent
                    # no `If-None-Match` the caller reports a failure, and a `not-modified` line here would
                    # contradict it.
                    if etag is not None:
                        self._log_line(url, status, elapsed_ms_since(started), 0, "not-modified")
                    return None
                if status != HTTPStatus.OK:
                    raise refusal_for(response, _PROVIDER)
                parsed, raw = await read_json(response)
                return ProviderBody(
                    parsed=parsed,
                    digest=payload_digest(raw),
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                    elapsed_ms=elapsed_ms_since(started),
                    bytes_read=len(raw),
                )
        except ProviderError as error:
            await self._failed(cursor, url, status, elapsed_ms_since(started), error)
            raise
        except httpx.HTTPError as error:
            # The shared reading of an outage, which is the one place the error's TEXT is kept out of the
            # message: a token with a stray newline would otherwise arrive here inside h11's complaint.
            failure = unreachable(_PROVIDER, error)
            await self._failed(cursor, url, status, elapsed_ms_since(started), failure)
            raise failure from error

    async def _validated[ModelT: BaseModel](
        self, model: type[ModelT], body: ProviderBody, *, cursor: Cursor | None, url: str
    ) -> ModelT:
        """The body as `model`. A shape this client cannot read is an unusable answer, not a crash."""
        try:
            return model.model_validate(body.parsed)
        except ValidationError as error:
            # The count, never the errors themselves: `ValidationError.errors()` embeds the input values,
            # and those would land in `sync_state.last_error` and in the log. The chained cause keeps them
            # for a traceback.
            failure = ProviderUnavailableError(
                f"TMDB answered {model.__name__} with a shape this client cannot read ({error.error_count()} problems)"
            )
            await self._failed(cursor, url, HTTPStatus.OK, body.elapsed_ms, failure)
            raise failure from error

    async def _failed(
        self, cursor: Cursor | None, url: str, status: int | None, elapsed_ms: int, error: ProviderError
    ) -> None:
        """Record a failed attempt against its cursor and log it. A query has no cursor, so it records nothing."""
        if cursor is not None:
            await self._cache.record_failure(
                _SOURCE, cursor.resource_type, cursor.resource_key, f"{type(error).__name__}: {error}"
            )
        # A refusal, an outage and a body this client cannot read are all the same outcome - nothing
        # arrived that anything could write. The `status` field says which kind of nothing it was, and
        # `throttled` stays reserved for a wait on the bucket.
        self._log_line(url, status, elapsed_ms, 0, "failed")

    async def _rogue_304(self, cursor: Cursor | None, url: str) -> NoReturn:
        """A 304 answering an `If-None-Match` this call never sent: the upstream misbehaving, not agreeing."""
        # Read as "nothing changed" it would silently skip a write, so it is recorded and raised like any
        # other unusable answer. A query carries no cursor and so records nothing.
        failure = ProviderUnavailableError(f"TMDB answered {httpx.URL(url).path} with 304 to an unconditional GET")
        await self._failed(cursor, url, HTTPStatus.NOT_MODIFIED, 0, failure)
        raise failure

    def _past_the_cache_ceiling(self, cached: CachedResponse | None) -> bool:
        """TMDB's terms cap caching at six months, so a cursor older than the ceiling forces a full refresh."""
        if cached is None:
            return False
        if cached.last_success_at is None:
            # Unknown age renews. A cursor carrying a validator but no stamp of when it was earned could
            # answer 304 - or match on the digest - for ever, and the ceiling would never fire. A cursor
            # carrying neither has simply never succeeded, and that is a first fetch, not a renewal.
            # The `ingest.sync_cursor` twin answers False here: `store` always stamps, so it never sees this.
            return cached.etag is not None or cached.payload_digest is not None
        # One arithmetic for the licence term, shared with the cursor that lists what has reached it.
        return cached.last_success_at <= ceiling_cutoff(self._clock(), TMDB_CACHE_CEILING_DAYS)

    def _bearer(self) -> str:
        """The `Authorization` value, and the one place the token is read. Refuses before a request is built."""
        if self._token is None:
            raise ProviderNotConfiguredError("TV_TMDB_READ_ACCESS_TOKEN is unset, so TMDB ingest is disabled")
        return f"Bearer {self._token.get_secret_value()}"

    def _log(self, url: str, status: int, body: ProviderBody, outcome: CacheOutcome) -> None:
        self._log_line(url, status, body.elapsed_ms, body.bytes_read, outcome)

    def _log_line(self, url: str, status: int | None, elapsed_ms: int, bytes_read: int, outcome: CacheOutcome) -> None:
        parsed = httpx.URL(url)
        log_call(
            _LOGGER,
            method="GET",
            host=parsed.host,
            path=parsed.path,
            status=status,
            elapsed_ms=elapsed_ms,
            bytes_read=bytes_read,
            outcome=outcome,
        )


def build_tmdb_client(
    settings: Settings, *, http: httpx.AsyncClient, bucket: TokenBucket, cache: ResponseCache
) -> TmdbClient:
    """The composition seam: the token comes from settings, everything else is handed in by the caller."""
    return TmdbClient(settings.tmdb_read_access_token, http=http, bucket=bucket, cache=cache)
