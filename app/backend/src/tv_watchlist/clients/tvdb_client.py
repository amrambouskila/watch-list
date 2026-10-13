"""The TheTVDB v4 client: a PIN'd login, a runtime list of orderings, and pages walked to the last one.

Three upstream facts shape this file, and each is a rule rather than a preference:

1. The bearer token lives one month and there is no refresh endpoint, so it is replaced on AGE - never in
   response to a 401, which would hide a revoked credential behind an endless retry.
2. The list of orderings is documented as examples, not an enum, so it is read from `GET /v4/seasons/types`
   at runtime and appears nowhere in this file as a value. A name this app has never seen must be storable.
3. An unrecognised ordering answers HTTP 200 with an empty `episodes` array, not a 4xx. That is *unknown* and
   never *this series has no episodes*: a plugin that read it as authoritative deleted 194 seasons a scan.

There is deliberately no search method. The series id arrives from TMDB `external_ids.tvdb_id`; TheTVDB's own
search ranked the One Piece anime eighth, behind a live-action namesake (`docs/status.md` section 2.9).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Final

import httpx
from pydantic import BaseModel, SecretStr, TypeAdapter, ValidationError

from tv_watchlist.clients.errors import (
    ProviderError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
    UnknownSeasonTypeError,
)
from tv_watchlist.clients.http_guard import assert_within_base, provider_url
from tv_watchlist.clients.rate_limiter import TokenBucket
from tv_watchlist.clients.response_cache import CachedResponse, ResponseCache
from tv_watchlist.clients.transport import (
    CacheOutcome,
    Cursor,
    ProviderBody,
    elapsed_ms_since,
    log_call,
    payload_digest,
    read_json,
    refusal_for,
    scrubbed,
    unreachable,
)
from tv_watchlist.clock import utcnow
from tv_watchlist.config import Settings
from tv_watchlist.constants import TVDB_API_BASE_URL, TVDB_TOKEN_REFRESH_DAYS
from tv_watchlist.models.tvdb.tvdb_episode import TvdbEpisode
from tv_watchlist.models.tvdb.tvdb_episode_page import TvdbEpisodePage
from tv_watchlist.models.tvdb.tvdb_episodes_result import TvdbEpisodesResult
from tv_watchlist.models.tvdb.tvdb_login import TvdbLogin
from tv_watchlist.models.tvdb.tvdb_season_type import TvdbSeasonType
from tv_watchlist.models.tvdb.tvdb_translation import TvdbTranslation
from tv_watchlist.models.tvdb.tvdb_update import TvdbUpdate
from tv_watchlist.models.tvdb.tvdb_update_page import TvdbUpdatePage

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_SOURCE: Final[str] = "tvdb"
_PROVIDER: Final[str] = "TheTVDB"
# These mirror `data.enums.SyncResourceType`'s VALUES by hand, because `clients/` may not import `data/`.
# T15's cache adapter converts a string back into the enum, so a drift fails there rather than silently.
_SEASON_TYPES: Final[str] = "tvdb_season_types"
_EPISODES: Final[str] = "tvdb_episodes"
_UPDATES: Final[str] = "tvdb_updates"

# `GET /v4/seasons/types` is a singleton, so its cursor needs a key rather than an id.
_SEASON_TYPES_KEY: Final[str] = "all"
# The language variant every name is read through: the un-suffixed endpoints answer in the original
# language, which for anime is Japanese (`docs/status.md` section 2.9, correction 3).
_ENGLISH: Final[str] = "eng"
# TheTVDB pages from zero, unlike TMDB.
_FIRST_PAGE: Final[int] = 0
_PAGE_PARAMETER: Final[str] = "page"
_DEFAULT_UPDATE_TYPE: Final[str] = "episodes"
_ENVELOPE_DATA: Final[str] = "data"
_REFRESH_AFTER: Final[timedelta] = timedelta(days=TVDB_TOKEN_REFRESH_DAYS)


@dataclass(frozen=True, slots=True)
class TvdbToken:
    """One bearer token and the moment it was issued, which is the only thing that decides when it is replaced."""

    value: SecretStr
    issued_at: datetime


def _envelope_data(parsed: object) -> object:
    """The `data` member of a TheTVDB envelope. What is inside it is the model's business, not this function's."""
    return parsed.get(_ENVELOPE_DATA) if isinstance(parsed, Mapping) else parsed


def _page_of(url: str) -> str:
    """The page number in a URL, which is what keys an episode page's cursor even when the provider built it."""
    return httpx.URL(url).params.get(_PAGE_PARAMETER, str(_FIRST_PAGE))


class TvdbClient:
    """Every TheTVDB call this project makes. The `http` it is handed carries no credential; this class adds it."""

    def __init__(
        self,
        api_key: SecretStr | None,
        pin: SecretStr | None,
        *,
        http: httpx.AsyncClient,
        bucket: TokenBucket,
        cache: ResponseCache,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._api_key = api_key
        self._pin = pin
        self._http = http
        self._bucket = bucket
        self._cache = cache
        self._clock = clock
        self._token: TvdbToken | None = None
        self._season_types: tuple[TvdbSeasonType, ...] | None = None

    @property
    def configured(self) -> bool:
        """Whether BOTH the key and the subscriber PIN are present. Either one missing disables the ingest."""
        return self._api_key is not None and self._pin is not None

    @property
    def token_issued_at(self) -> datetime | None:
        """When the token this client holds was issued, or `None` before the first login."""
        return None if self._token is None else self._token.issued_at

    async def login(self) -> None:
        """Exchange the key and the PIN for a bearer token, kept in memory with the moment it was issued."""
        await self._logged_in()

    async def season_types(self) -> tuple[TvdbSeasonType, ...]:
        """The orderings the service currently offers, read once per process and hard-coded nowhere."""
        if self._season_types is not None:
            return self._season_types
        # Fetched unconditionally rather than with an `If-None-Match`: a 304 would leave this client with no
        # list to validate a season type against, and that validation is worth far more than a saved request.
        types = await self._get_many(
            TvdbSeasonType,
            cursor=Cursor(_SEASON_TYPES, _SEASON_TYPES_KEY),
            url=provider_url(TVDB_API_BASE_URL, "seasons", "types"),
        )
        self._season_types = types
        return types

    async def series_translation(self, series_id: int) -> TvdbTranslation:
        """The English name of a series, which the un-suffixed endpoints do not return.

        Never `None`: a series with no English translation answers 404, which is `ProviderNotFoundError`
        for the caller to catch, not an empty result it has to tell apart from an empty name.
        """
        return await self._get(
            TvdbTranslation,
            cursor=None,
            url=provider_url(TVDB_API_BASE_URL, "series", series_id, "translations", _ENGLISH),
        )

    async def series_episodes(self, series_id: int, season_type: str, *, page: int = _FIRST_PAGE) -> TvdbEpisodePage:
        """One page of one ordering, in English. The season type is checked against the live list FIRST."""
        await self._assert_known(season_type)
        return await self._page(
            provider_url(TVDB_API_BASE_URL, "series", series_id, "episodes", season_type, _ENGLISH, page=page),
            series_id=series_id,
            season_type=season_type,
        )

    async def all_series_episodes(self, series_id: int, season_type: str) -> TvdbEpisodesResult:
        """Every page of one ordering, following `links.next` to the last page and logging what it walked."""
        await self._assert_known(season_type)
        url: str | None = provider_url(
            TVDB_API_BASE_URL, "series", series_id, "episodes", season_type, _ENGLISH, page=_FIRST_PAGE
        )
        episodes: list[TvdbEpisode] = []
        walked: set[str] = set()
        pages = 0
        reported = 0
        while url is not None and url not in walked:
            walked.add(url)
            page = await self._page(url, series_id=series_id, season_type=season_type)
            episodes.extend(page.episodes)
            reported = page.total_items or reported
            pages += 1
            url = self._next_page(page)
        # `or None`: `total_items` defaults to 0 for a page that carried no count, and "did not say" is
        # not "said none" - a caller comparing against 0 would refuse every walk of an ordering whose
        # pages omit the field.
        result = TvdbEpisodesResult(episodes=tuple(episodes), pages=pages, reported=reported or None)
        self._log_pages(f"series/{series_id}/{season_type}", pages=pages, total=len(result.episodes), reported=reported)
        return result

    async def updates(self, since: datetime, *, type_: str = _DEFAULT_UPDATE_TYPE) -> tuple[TvdbUpdate, ...]:
        """Which records of one kind moved since a moment - ONE page, and a refusal rather than a short read."""
        cursor = Cursor(_UPDATES, type_)
        url = provider_url(TVDB_API_BASE_URL, "updates", since=int(since.timestamp()), type=type_, page=_FIRST_PAGE)
        page, body, cached = await self._fetched(TvdbUpdatePage, cursor=cursor, url=url)
        if page.next_url is not None:
            # This method reads one page by contract, so a second page means the caller would silently act
            # on a partial window - the failure mode section 9.2 names: a truncated read reporting success
            # is worse than one that fails. Nothing is stored, so the cursor does not claim to be current.
            raise await self._truncated(cursor, url, body, page)
        await self._recorded(cursor, body, url, cached)
        self._log_pages(f"updates/{type_}", pages=1, total=len(page.updates), reported=page.total_items)
        return page.updates

    async def _assert_known(self, season_type: str) -> None:
        """Refuse an ordering the live list does not carry, BEFORE a URL is built out of it."""
        known = {entry.type for entry in await self.season_types()}
        if season_type not in known:
            # Never a hard-coded list: this compares against what the service said today. An unrecognised
            # type would otherwise answer 200 with an empty array, which reads exactly like a real answer.
            raise UnknownSeasonTypeError(f"{_PROVIDER} does not offer a season type named {season_type!r}")

    async def _page(self, url: str, *, series_id: int, season_type: str) -> TvdbEpisodePage:
        return await self._get(
            TvdbEpisodePage,
            cursor=Cursor(_EPISODES, f"{series_id}/{season_type}/{_page_of(url)}"),
            url=url,
        )

    def _next_page(self, page: TvdbEpisodePage) -> str | None:
        """The next page's URL, re-checked against the base: a provider-supplied URL is still outside input."""
        if page.next_url is None:
            return None
        assert_within_base(page.next_url, TVDB_API_BASE_URL)
        return page.next_url

    async def _logged_in(self) -> TvdbToken:
        """One `POST /login` carrying both the key and the PIN, and the token it answers with."""
        api_key, pin = self._credentials()
        url = provider_url(TVDB_API_BASE_URL, "login")
        body = await self._send("POST", url, cursor=None, headers=None, payload={"apikey": api_key, "pin": pin})
        parsed = await self._validated(TvdbLogin, body, cursor=None, url=url)
        self._log(url, HTTPStatus.OK, body, "fresh", method="POST")
        token = TvdbToken(value=parsed.token, issued_at=self._clock())
        self._token = token
        return token

    async def _get[ModelT: BaseModel](self, model: type[ModelT], *, cursor: Cursor | None, url: str) -> ModelT:
        """One GET whose body is a single shape. The cursor is recorded whether or not anything changed."""
        parsed, body, cached = await self._fetched(model, cursor=cursor, url=url)
        await self._recorded(cursor, body, url, cached)
        return parsed

    async def _fetched[ModelT: BaseModel](
        self, model: type[ModelT], *, cursor: Cursor | None, url: str
    ) -> tuple[ModelT, ProviderBody, CachedResponse | None]:
        """Everything a fetch does BEFORE its cursor is written, so a caller can refuse what arrived first."""
        bearer = await self._bearer()
        cached = await self._lookup(cursor)
        body = await self._send("GET", url, cursor=cursor, headers={"Authorization": bearer}, payload=None)
        return await self._validated(model, body, cursor=cursor, url=url), body, cached

    async def _get_many[ModelT: BaseModel](
        self, model: type[ModelT], *, cursor: Cursor | None, url: str
    ) -> tuple[ModelT, ...]:
        """One GET whose envelope carries an array of one shape."""
        bearer = await self._bearer()
        cached = await self._lookup(cursor)
        body = await self._send("GET", url, cursor=cursor, headers={"Authorization": bearer}, payload=None)
        parsed = await self._validated_many(model, body, cursor=cursor, url=url)
        await self._recorded(cursor, body, url, cached)
        return parsed

    async def _send(
        self,
        method: str,
        url: str,
        *,
        cursor: Cursor | None,
        headers: dict[str, str] | None,
        payload: dict[str, str] | None,
    ) -> ProviderBody:
        """One throttled, guarded request. Every non-200 - a 304 included - raises and records the failure."""
        await self._bucket.acquire()
        started = time.monotonic()
        status: int | None = None
        try:
            async with self._http.stream(method, url, headers=headers, json=payload) as response:
                status = response.status_code
                if status != HTTPStatus.OK:
                    # TheTVDB sends no ETag, so nothing here ever asks conditionally and a 304 is the
                    # upstream misbehaving rather than agreeing with a cursor.
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
            await self._failed(cursor, url, status, elapsed_ms_since(started), error, method=method)
            raise
        except httpx.HTTPError as error:
            # The shared reading of an outage; see `transport.unreachable` for why the text is dropped.
            failure = unreachable(_PROVIDER, error)
            await self._failed(cursor, url, status, elapsed_ms_since(started), failure, method=method)
            raise failure from error

    async def _validated[ModelT: BaseModel](
        self, model: type[ModelT], body: ProviderBody, *, cursor: Cursor | None, url: str
    ) -> ModelT:
        """The body as `model`. A shape this client cannot read is an unusable answer, not a crash."""
        try:
            return model.model_validate(body.parsed)
        except ValidationError as error:
            raise await self._unreadable(model.__name__, error, cursor=cursor, url=url, body=body) from error

    async def _validated_many[ModelT: BaseModel](
        self, model: type[ModelT], body: ProviderBody, *, cursor: Cursor | None, url: str
    ) -> tuple[ModelT, ...]:
        """The envelope's array as a tuple of `model`."""
        adapter: TypeAdapter[tuple[ModelT, ...]] = TypeAdapter(tuple[model, ...])
        try:
            return adapter.validate_python(_envelope_data(body.parsed))
        except ValidationError as error:
            raise await self._unreadable(f"{model.__name__} list", error, cursor=cursor, url=url, body=body) from error

    async def _unreadable(
        self, shape: str, error: ValidationError, *, cursor: Cursor | None, url: str, body: ProviderBody
    ) -> ProviderUnavailableError:
        """The failure a shape this client cannot read becomes, recorded without quoting one byte of it."""
        # The count, never the errors themselves: `ValidationError.errors()` embeds the input values, and
        # those would land in `sync_state.last_error` and in the log. The chained cause keeps them for a
        # traceback.
        failure = ProviderUnavailableError(
            f"{_PROVIDER} answered {shape} with a shape this client cannot read ({error.error_count()} problems)"
        )
        await self._failed(cursor, url, HTTPStatus.OK, body.elapsed_ms, failure)
        return failure

    async def _truncated(
        self, cursor: Cursor, url: str, body: ProviderBody, page: TvdbUpdatePage
    ) -> ProviderUnavailableError:
        """A window that carries a `links.next` this method does not follow: recorded as the failure it is."""
        failure = ProviderUnavailableError(
            f"{_PROVIDER} answered {httpx.URL(url).path} with {len(page.updates)} of {page.total_items} "
            f"records and a further page; this call reads one page and will not report a partial window"
        )
        await self._failed(cursor, url, HTTPStatus.OK, body.elapsed_ms, failure)
        return failure

    async def _bearer(self) -> str:
        """The `Authorization` value, logging in first when no token is held or the one held is old enough."""
        token = self._token
        if token is None or self._clock() - token.issued_at >= _REFRESH_AFTER:
            # Proactive, and only proactive. A re-login triggered by a 401 would turn a revoked key into an
            # endless retry loop against an upstream whose rate limit is undocumented.
            token = await self._logged_in()
        return f"Bearer {token.value.get_secret_value()}"

    def _credentials(self) -> tuple[str, str]:
        """The two values `POST /login` needs, and the one place either is read."""
        if self._api_key is None or self._pin is None:
            # Both, always: this project holds an End-User Subscriptions key, whose login fails without the
            # subscriber PIN. A missing credential is a disabled feature, never a boot failure.
            raise ProviderNotConfiguredError(
                "TV_TVDB_API_KEY and TV_TVDB_PIN must both be set, so TheTVDB ingest is disabled"
            )
        return self._api_key.get_secret_value(), self._pin.get_secret_value()

    async def _lookup(self, cursor: Cursor | None) -> CachedResponse | None:
        if cursor is None:
            return None
        return await self._cache.lookup(_SOURCE, cursor.resource_type, cursor.resource_key)

    async def _recorded(
        self, cursor: Cursor | None, body: ProviderBody, url: str, cached: CachedResponse | None
    ) -> None:
        """Store what arrived and log whether it differed from what the cursor already held."""
        # An unchanged body is still stored, which is where this differs from TMDB. TheTVDB sends no ETag
        # and this project keeps no six-month ceiling against it, so the only question a cursor has to
        # answer is "when did this last sync successfully" - and skipping the write on an equal digest
        # would let that answer go stale while the ingest was in fact healthy.
        outcome: CacheOutcome = (
            "not-modified" if cached is not None and cached.payload_digest == body.digest else "fresh"
        )
        if cursor is not None:
            await self._cache.store(
                _SOURCE,
                cursor.resource_type,
                cursor.resource_key,
                etag=body.etag,
                last_modified=body.last_modified,
                payload_digest=body.digest,
            )
        self._log(url, HTTPStatus.OK, body, outcome)

    async def _failed(
        self,
        cursor: Cursor | None,
        url: str,
        status: int | None,
        elapsed_ms: int,
        error: ProviderError,
        *,
        method: str = "GET",
    ) -> None:
        """Record a failed attempt against its cursor and log it. A cursorless call records nothing."""
        if cursor is not None:
            await self._cache.record_failure(
                _SOURCE, cursor.resource_type, cursor.resource_key, f"{type(error).__name__}: {error}"
            )
        # A refusal, an outage and a body this client cannot read are all the same outcome - nothing
        # arrived that anything could write. The `status` field says which kind of nothing it was, and
        # `throttled` stays reserved for a wait on the bucket.
        self._log_line(url, status, elapsed_ms, 0, "failed", method=method)

    def _log_pages(self, subject: str, *, pages: int, total: int, reported: int) -> None:
        """One record per multi-page read. `total` is what was collected, `reported` is what was claimed.

        A reader compares the two: they disagree when a walk was cut short, which is the one failure that
        otherwise looks exactly like success. `total=0` is also how an ordering that came back unknown
        reads here, which is why no separate `known` field is emitted.
        """
        _LOGGER.info(
            "provider_pages source=%s subject=%s pages=%d total=%d reported=%d",
            _SOURCE,
            scrubbed(subject),
            pages,
            total,
            reported,
        )

    def _log(self, url: str, status: int, body: ProviderBody, outcome: CacheOutcome, *, method: str = "GET") -> None:
        self._log_line(url, status, body.elapsed_ms, body.bytes_read, outcome, method=method)

    def _log_line(
        self,
        url: str,
        status: int | None,
        elapsed_ms: int,
        bytes_read: int,
        outcome: CacheOutcome,
        *,
        method: str = "GET",
    ) -> None:
        parsed = httpx.URL(url)
        log_call(
            _LOGGER,
            method=method,
            host=parsed.host,
            path=parsed.path,
            status=status,
            elapsed_ms=elapsed_ms,
            bytes_read=bytes_read,
            outcome=outcome,
        )


def build_tvdb_client(
    settings: Settings, *, http: httpx.AsyncClient, bucket: TokenBucket, cache: ResponseCache
) -> TvdbClient:
    """The composition seam: both credentials come from settings, everything else is handed in by the caller."""
    return TvdbClient(settings.tvdb_api_key, settings.tvdb_pin, http=http, bucket=bucket, cache=cache)
