"""Recorded provider bodies, replayed. Every provider test runs on these; none of them touches a network.

`tests/fixtures/<provider>/<name>.json` is the body exactly as the service sent it, so a digest over those
bytes is the digest the real bytes produce. `<name>.headers.json` carries the ETag/Date/Last-Modified that
came with it, which is what lets a conditional-request test replay a real cursor.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final

import httpx
from mock_responder import MockResponder
from pydantic import SecretStr

from tv_watchlist.clients.jellyfin_client import JellyfinClient, build_jellyfin_http
from tv_watchlist.clients.qbittorrent_client import QbittorrentClient, build_qbittorrent_http
from tv_watchlist.clients.rate_limiter import TokenBucket
from tv_watchlist.clients.response_cache import CachedResponse, ResponseCache
from tv_watchlist.clients.tmdb_client import TmdbClient
from tv_watchlist.clients.transport import build_provider_http
from tv_watchlist.clients.tvdb_client import TvdbClient
from tv_watchlist.clock import utcnow
from tv_watchlist.constants import (
    TMDB_API_BASE_URL,
    TMDB_REQUESTS_PER_SECOND,
    TVDB_API_BASE_URL,
    TVDB_REQUESTS_PER_SECOND,
    UNCONFIGURED_UPSTREAM_BASE_URL,
)

FIXTURE_ROOT: Final[Path] = Path(__file__).resolve().parent / "fixtures"
TMDB: Final[str] = "tmdb"
TVDB: Final[str] = "tvdb"
# Jellyfin's bodies are the one set here that is HAND-AUTHORED rather than recorded, because no Jellyfin
# has ever been reachable on this machine. `tests/fixtures/jellyfin/README.md` says what that costs.
JELLYFIN: Final[str] = "jellyfin"
RECORDED_TOKEN: Final[str] = "recorded-token"  # noqa: S105 - the deliberate fake every recorded fixture replays
# TheTVDB authenticates with two values, and a test that only ever sees one of them cannot prove the
# End-User Subscriptions shape. Neither of these resembles a real credential.
A_RECORDED_KEY: Final[str] = "recorded-api-key"
A_RECORDED_PIN: Final[str] = "recorded-pin"
# Jellyfin authenticates with one key in one header, and this one resembles a real key no more than the
# others do. The base is the compose service name, which is what the backend container actually talks to.
A_RECORDED_JELLYFIN_KEY: Final[str] = "recorded-jellyfin-key"  # noqa: S105 - a deliberate fake, not a credential
A_JELLYFIN_BASE_URL: Final[str] = "http://jellyfin:8096"
# qBittorrent's bodies are hand-authored too, and for a second reason Jellyfin does not have: the
# owner's own instance holds the owner's own download history, which may not enter a public repository.
# `tests/fixtures/qbittorrent/README.md` records both.
QBITTORRENT: Final[str] = "qbittorrent"
# The WebUI authenticates with a username and a password posted to `/api/v2/auth/login`, and answers
# with a `SID` cookie. None of the three below resembles anything real.
A_RECORDED_QBITTORRENT_USER: Final[str] = "recorded-user"
A_RECORDED_QBITTORRENT_PASSWORD: Final[str] = "recorded-password"  # noqa: S105 - a deliberate fake
A_RECORDED_SID: Final[str] = "recorded0sid0value"
# Loopback, because that is where a WebUI the owner runs actually listens; 8080 is qBittorrent's own
# default WebUI port. The guard admits `http` here precisely because of that (CLAUDE.md 10.3, B21).
A_QBITTORRENT_BASE_URL: Final[str] = "http://127.0.0.1:8080"
# A credential with a newline in it - the shape that makes h11 quote the whole header into its error.
A_CREDENTIAL_WITH_A_NEWLINE: Final[str] = "se\ncret-newline-credential"  # noqa: S105 - a deliberate fake
# Big enough that no unit test ever waits on the bucket; the rate itself is covered by the bucket's own tests.
A_BURST_NO_TEST_EXHAUSTS: Final[int] = 64


def fixture_path(provider: str, name: str) -> Path:
    """Where one recorded body lives."""
    return FIXTURE_ROOT / provider / f"{name}.json"


def fixture_bytes(provider: str, name: str) -> bytes:
    """The recorded body verbatim, so a digest over it matches the digest of what the service really sent."""
    return fixture_path(provider, name).read_bytes()


def fixture_json(provider: str, name: str) -> dict[str, object]:
    """One recorded body, parsed."""
    parsed = json.loads(fixture_bytes(provider, name))
    if not isinstance(parsed, dict):
        raise TypeError(f"{provider}/{name}.json is not a JSON object")
    return parsed


def fixture_text_response(provider: str, name: str, *, status: int = 200) -> httpx.Response:
    """A recorded `.txt` body as a response - `/health` answers plain text rather than JSON."""
    body = (FIXTURE_ROOT / provider / f"{name}.txt").read_bytes()
    return httpx.Response(status, content=body, headers={"content-type": "text/plain"})


def fixture_rows(provider: str, name: str) -> list[dict[str, object]]:
    """One recorded body that is a JSON ARRAY, parsed - qBittorrent answers lists, not envelopes."""
    parsed = json.loads(fixture_bytes(provider, name))
    if not isinstance(parsed, list):
        raise TypeError(f"{provider}/{name}.json is not a JSON array")
    # Refused rather than filtered: a fixture that grew a bare string would otherwise shrink every
    # assertion made over it and nobody would see the row go.
    if not all(isinstance(row, dict) for row in parsed):
        raise TypeError(f"{provider}/{name}.json carries a row that is not a JSON object")
    return [row for row in parsed if isinstance(row, dict)]


def fixture_headers(provider: str, name: str) -> dict[str, str]:
    """The ETag / Last-Modified / Date recorded beside a body, or nothing when none were captured."""
    path = FIXTURE_ROOT / provider / f"{name}.headers.json"
    if not path.exists():
        return {}
    recorded = json.loads(path.read_text())
    return {str(key): str(value) for key, value in recorded.items()}


def fixture_etag(provider: str, name: str) -> str | None:
    """The ETag the service really sent with that body, which a 304 test primes its cache with."""
    return fixture_headers(provider, name).get("etag")


def fixture_response(
    provider: str, name: str, *, status: int = 200, headers: Mapping[str, str] | None = None
) -> httpx.Response:
    """That recorded body as a response, carrying the headers it was recorded with unless they are overridden."""
    merged = fixture_headers(provider, name) | dict(headers or {})
    return httpx.Response(status, content=fixture_bytes(provider, name), headers=merged)


class RecordingResponder(MockResponder):
    """A `MockResponder` that keeps the whole request, so a test can assert on headers as well as on URLs."""

    def __init__(self, *responses: httpx.Response) -> None:
        # Recording is an override of `_handle`, not a second transport wrapped around it: the base class
        # builds its `MockTransport` over `self._handle`, so reassigning `self.transport` here would leave
        # that first transport alive, unreachable, and able to answer nothing.
        self.requests: list[httpx.Request] = []
        super().__init__(*responses)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return super()._handle(request)


class H11RejectingResponder(RecordingResponder):
    """A transport that fails the way h11 really does: by quoting the whole illegal header value back.

    Measured against h11 directly - `LocalProtocolError: Illegal header value b'Bearer se\ncret'` - and
    `httpx.LocalProtocolError` subclasses `httpx.HTTPError`, so this is the exact path a CR, LF or NUL in a
    credential takes in production. `httpx.MockTransport` does no header validation of its own, which is
    precisely why this has to be reproduced rather than waited for.

    A request that does not carry `header` is answered normally, so a TheTVDB login - which carries its
    credentials in a JSON body and gets its bearer back - still succeeds and the NEXT call is the one that
    fails on the header built from it. `header` is `Authorization` for the three clients that authenticate
    by header; qBittorrent authenticates by cookie, so its secret rides in `Cookie` and that is the header
    h11 would quote back at it.
    """

    def __init__(self, *responses: httpx.Response, header: str = "Authorization") -> None:
        self._rejected_header = header
        super().__init__(*responses)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        header = request.headers.get(self._rejected_header)
        if header is None:
            self.requested.append(str(request.url))
            return self._remaining.pop(0) if len(self._remaining) > 1 else self._remaining[0]
        raise httpx.LocalProtocolError(f"Illegal header value {header.encode()!r}")


class CountingBucket(TokenBucket):
    """A real bucket that also counts, so a test can prove every call went through the provider's budget."""

    def __init__(self, rate_per_second: float = TMDB_REQUESTS_PER_SECOND) -> None:
        super().__init__(rate_per_second=rate_per_second, burst=A_BURST_NO_TEST_EXHAUSTS)
        self.acquires = 0

    async def acquire(self) -> float:
        self.acquires += 1
        return await super().acquire()


@dataclass(frozen=True, slots=True)
class StoredCursor:
    """One `store` a client made: the cursor it wrote and what it wrote into it."""

    source: str
    resource_type: str
    resource_key: str
    etag: str | None
    last_modified: str | None
    payload_digest: str


@dataclass(frozen=True, slots=True)
class RecordedFailure:
    """One `record_failure` a client made."""

    source: str
    resource_type: str
    resource_key: str
    error: str


@dataclass
class RecordingResponseCache:
    """A `ResponseCache` that answers every lookup with one primed entry and records every write."""

    primed: CachedResponse | None = None
    lookups: list[tuple[str, str, str]] = field(default_factory=list)
    stored: list[StoredCursor] = field(default_factory=list)
    failures: list[RecordedFailure] = field(default_factory=list)

    async def lookup(self, source: str, resource_type: str, resource_key: str) -> CachedResponse | None:
        self.lookups.append((source, resource_type, resource_key))
        return self.primed

    async def store(
        self,
        source: str,
        resource_type: str,
        resource_key: str,
        *,
        etag: str | None,
        last_modified: str | None,
        payload_digest: str,
    ) -> None:
        self.stored.append(StoredCursor(source, resource_type, resource_key, etag, last_modified, payload_digest))

    async def record_failure(self, source: str, resource_type: str, resource_key: str, error: str) -> None:
        self.failures.append(RecordedFailure(source, resource_type, resource_key, error))


def tmdb_client_for(
    *responses: httpx.Response,
    token: str | None = RECORDED_TOKEN,
    cache: ResponseCache | None = None,
    bucket: TokenBucket | None = None,
    clock: Callable[[], datetime] | None = None,
    responder: RecordingResponder | None = None,
) -> tuple[TmdbClient, RecordingResponder]:
    """A `TmdbClient` wired to canned answers. The http it is handed carries no credential; the client adds it."""
    responder = responder if responder is not None else RecordingResponder(*responses)
    http = build_provider_http(TMDB_API_BASE_URL, headers={"Accept": "application/json"}, transport=responder.transport)
    client = TmdbClient(
        None if token is None else SecretStr(token),
        http=http,
        bucket=bucket if bucket is not None else TokenBucket(TMDB_REQUESTS_PER_SECOND, A_BURST_NO_TEST_EXHAUSTS),
        cache=cache if cache is not None else RecordingResponseCache(),
        clock=clock if clock is not None else utcnow,
    )
    return client, responder


def tvdb_client_for(
    *responses: httpx.Response,
    api_key: str | None = A_RECORDED_KEY,
    pin: str | None = A_RECORDED_PIN,
    login: bool = True,
    cache: ResponseCache | None = None,
    bucket: TokenBucket | None = None,
    clock: Callable[[], datetime] | None = None,
    responder: RecordingResponder | None = None,
) -> tuple[TvdbClient, RecordingResponder]:
    """A `TvdbClient` wired to canned answers, with the recorded `/login` prepended unless `login=False`.

    Every TheTVDB call but the login needs a bearer first, so the login answer is the first canned response
    by default and a test's own responses follow it in order.
    """
    canned = (fixture_response(TVDB, "login"), *responses) if login else responses
    responder = responder if responder is not None else RecordingResponder(*canned)
    http = build_provider_http(TVDB_API_BASE_URL, headers={"Accept": "application/json"}, transport=responder.transport)
    client = TvdbClient(
        None if api_key is None else SecretStr(api_key),
        None if pin is None else SecretStr(pin),
        http=http,
        bucket=bucket if bucket is not None else TokenBucket(TVDB_REQUESTS_PER_SECOND, A_BURST_NO_TEST_EXHAUSTS),
        cache=cache if cache is not None else RecordingResponseCache(),
        clock=clock if clock is not None else utcnow,
    )
    return client, responder


def jellyfin_client_for(
    *responses: httpx.Response,
    base_url: str | None = A_JELLYFIN_BASE_URL,
    api_key: str | None = A_RECORDED_JELLYFIN_KEY,
    responder: RecordingResponder | None = None,
) -> tuple[JellyfinClient, RecordingResponder]:
    """A `JellyfinClient` wired to canned answers. The http it is handed carries no credential; the client adds it.

    `base_url=None` is the disabled shape rather than a broken one, so the pool is pinned to the same dead
    loopback address `build_jellyfin_client` pins an unconfigured client's to.
    """
    responder = responder if responder is not None else RecordingResponder(*responses)
    http = build_jellyfin_http(base_url or UNCONFIGURED_UPSTREAM_BASE_URL, transport=responder.transport)
    return JellyfinClient(base_url, None if api_key is None else SecretStr(api_key), http=http), responder


def qbittorrent_login_response(*, sid: str = A_RECORDED_SID) -> httpx.Response:
    """What `POST /api/v2/auth/login` answers on success: the body `Ok.` and a `SID` cookie."""
    return httpx.Response(200, text="Ok.", headers={"set-cookie": f"SID={sid}; path=/; HttpOnly"})


def qbittorrent_client_for(
    *responses: httpx.Response,
    base_url: str | None = A_QBITTORRENT_BASE_URL,
    user: str | None = A_RECORDED_QBITTORRENT_USER,
    password: str | None = A_RECORDED_QBITTORRENT_PASSWORD,
    login: bool = True,
    version: bool = True,
    responder: RecordingResponder | None = None,
) -> tuple[QbittorrentClient, RecordingResponder]:
    """A `QbittorrentClient` wired to canned answers, with the two calls every data call makes first.

    A qBittorrent data call logs in (no SID yet) and then reads `webapiVersion` (the version floor) before
    it asks for anything, so those two answers are prepended by default and a test's own responses follow
    in order. `login=False` / `version=False` are for the tests that drive those two calls themselves.

    `base_url=None` is the disabled shape rather than a broken one, so the pool is pinned to the same dead
    loopback address `build_qbittorrent_client` pins an unconfigured client's to.
    """
    canned: list[httpx.Response] = []
    if login:
        canned.append(qbittorrent_login_response())
    if version:
        canned.append(fixture_text_response(QBITTORRENT, "webapi_version"))
    canned.extend(responses)
    responder = responder if responder is not None else RecordingResponder(*canned)
    http = build_qbittorrent_http(base_url or UNCONFIGURED_UPSTREAM_BASE_URL, transport=responder.transport)
    client = QbittorrentClient(
        base_url,
        user,
        None if password is None else SecretStr(password),
        http=http,
    )
    return client, responder
