"""The one thing in this project that talks to qBittorrent, and it is **read-only** (ADR-015).

Six facts shape this file, and each is a rule rather than a preference:

1. **It cannot acquire anything, and that is the point.** ADR-015 records that the owner asked for an
   automated acquisition pipeline and that the controller declined to build one. The concrete consequence
   lives here: four methods, none of which adds a torrent, injects a magnet link or searches an indexer -
   this client lists what the owner has *already finished downloading* and reads which files that
   produced. `tests/clients/test_qbittorrent_client.py` asserts the public surface by name and by source,
   and `tests/test_no_acquisition_surface.py` sweeps the whole of `src/`, so nothing can be added quietly.
   Neither sweep is satisfied by a rename, because both read the text rather than the exported names.
2. **The configured host IS the allowlist.** qBittorrent is a WebUI the owner runs, so its origin is
   configuration - and it is loopback or LAN, over plain `http`. `agent/url_guard` rejects every private
   and loopback address by design and `clients/http_guard.assert_within_base` requires https, so neither
   is used here; `assert_within_configured_base` is, and this class exposes no method taking a URL at all.
   Everything that shape implies - the pool, the call log, the reading of a failure - is
   `clients/configured_upstream.py`, shared with the Jellyfin client so neither can drift (R90).
3. **The password is read in exactly one place and put in exactly one body.** It is form-encoded into
   `POST /api/v2/auth/login` and never enters a URL, a header, a log record or an exception message. What
   comes back is a `SID` cookie, which lives in this client's own in-memory jar for the process lifetime
   and is never written to disk.
4. **A 403 costs exactly one re-login, and never a loop.** The WebUI documents one status for two
   situations - an unauthenticated session, and *"User's IP is banned for too many failed login attempts"*.
   So a data call that is refused re-authenticates once and retries once; a second refusal raises. A retry
   loop here is precisely how a client earns the ban.
5. **No upstream error's TEXT is ever repeated.** Only its class name is, through `UpstreamCalls`, for the
   reason that module gives: h11 builds its message by quoting the whole offending header back, and this
   client's secret rides in a `Cookie` header.
6. **The Web API version is read, not assumed.** `content_path` is documented as exposed since WebAPI
   v2.6.1 and a file's `index` since 2.8.2. Anything below 2.8.2 is refused by name, once per session,
   rather than being asked for fields it does not send.

Like the Jellyfin client and for the same reason, this deliberately does not use
`clients/response_cache.py`: qBittorrent is a local server with no ETag discipline and nothing metered
about it, so a `sync_state` row for it would be a cursor about nothing.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from http import HTTPStatus
from logging import Logger, getLogger
from typing import Final
from urllib.parse import urlsplit

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
    OutboundUrlError,
    ProviderError,
    ProviderUnavailableError,
    QbittorrentAuthError,
    QbittorrentNotConfiguredError,
    QbittorrentUnsupportedVersionError,
)
from tv_watchlist.clients.http_guard import configured_url
from tv_watchlist.clients.transport import elapsed_ms_since, read_json, read_text, refusal_for, scrubbed
from tv_watchlist.config import Settings
from tv_watchlist.constants import (
    MAX_QBITTORRENT_RESPONSE_BYTES,
    MAX_QBITTORRENT_VERSION_LENGTH,
    QBITTORRENT_COMPLETED_FILTER,
    QBITTORRENT_LOGIN_OK,
    QBITTORRENT_LOGIN_PATH,
    QBITTORRENT_MIN_WEBAPI_VERSION,
    QBITTORRENT_ORIGIN_HEADER,
    QBITTORRENT_PASSWORD_FIELD,
    QBITTORRENT_REFERER_HEADER,
    QBITTORRENT_TIMEOUT_SECONDS,
    QBITTORRENT_TORRENTS_FILES_PATH,
    QBITTORRENT_TORRENTS_INFO_PATH,
    QBITTORRENT_USERNAME_FIELD,
    QBITTORRENT_WEBAPI_VERSION_PATH,
    UNCONFIGURED_UPSTREAM_BASE_URL,
)
from tv_watchlist.models.qbittorrent.qbittorrent_file import QbittorrentFile
from tv_watchlist.models.qbittorrent.qbittorrent_torrent import QbittorrentTorrent, is_recognised_hash

_LOGGER: Final[Logger] = getLogger(__name__)

_PROVIDER: Final[str] = "qBittorrent"
_VERSION_SEPARATOR: Final[str] = "."
_IPV6_MARKER: Final[str] = ":"


def _segments(path: str) -> tuple[str, ...]:
    """One documented endpoint's path, split so the shared builder percent-encodes each segment.

    The paths themselves are single constants in `constants.py` (the T60 block); splitting them here is
    what keeps that the only spelling of any of them, rather than a second tuple that could drift from it.
    """
    return tuple(part for part in path.split("/") if part)


def _parsed_version(version: str) -> tuple[int, ...]:
    """A version as integers, or `()` for anything that is not one - which refuses, since `() < (2, 8, 2)`.

    Component by component rather than lexically: `2.11.4` sorts BELOW `2.8.2` as a string, so a string
    comparison would refuse every modern server and admit none of the old ones this floor exists for.

    Bounded and ASCII-only before anything is converted, because this reads an upstream body: a megabyte
    of digits would be split into a megabyte of parts, and `"²".isdigit()` is `True` while `int("²")`
    raises - a bare `ValueError` escaping a version check is not a failure mode this client may have.
    """
    trimmed = version.strip()
    if not trimmed or len(trimmed) > MAX_QBITTORRENT_VERSION_LENGTH:
        return ()
    parts = trimmed.split(_VERSION_SEPARATOR)
    if not all(part.isascii() and part.isdigit() for part in parts):
        return ()
    return tuple(int(part) for part in parts)


# Every path this project asks qBittorrent for. Constants, never composed from anything a caller supplied.
_LOGIN: Final[tuple[str, ...]] = _segments(QBITTORRENT_LOGIN_PATH)
_TORRENTS_INFO: Final[tuple[str, ...]] = _segments(QBITTORRENT_TORRENTS_INFO_PATH)
_TORRENTS_FILES: Final[tuple[str, ...]] = _segments(QBITTORRENT_TORRENTS_FILES_PATH)
_WEBAPI_VERSION: Final[tuple[str, ...]] = _segments(QBITTORRENT_WEBAPI_VERSION_PATH)

# The floor, parsed by the same function that parses what the server answers - so the comparison cannot
# be made between two differently-read tuples, and the separator is spelled in exactly one place.
_MINIMUM_VERSION: Final[tuple[int, ...]] = _parsed_version(QBITTORRENT_MIN_WEBAPI_VERSION)
# One sentence for every refusal, so which of the three values is missing is never leaked by the wording
# and the check order cannot drift between the two places that make it.
_UNCONFIGURED: Final[str] = (
    "TV_QBITTORRENT_URL, TV_QBITTORRENT_USER or TV_QBITTORRENT_PASSWORD is unset, so qBittorrent is disabled"
)

# A reader turns one 200 into the thing the caller wanted, and hands back the bytes it read so the call
# log can say how many there were. Validation happens INSIDE a reader rather than after the call, so a
# body this client cannot read is logged as the failure it is rather than as a successful fetch.
type _BodyReader[T] = Callable[[httpx.Response], Awaitable[tuple[T, bytes]]]


class _Forbidden(Exception):  # noqa: N818 - not an error a caller sees; it never leaves this module
    """Internal: the upstream answered 403, so one re-login is due. Never raised past `_authenticated`."""


class QbittorrentClient:
    """Read-only. Lists what the owner has already finished downloading; it cannot add anything (ADR-015)."""

    def __init__(
        self,
        base_url: str | None,
        username: str | None,
        password: SecretStr | None,
        *,
        http: httpx.AsyncClient,
    ) -> None:
        self._base_url = base_url
        self._username = username
        self._password = password
        self._http = http
        self._calls = UpstreamCalls(_LOGGER, _PROVIDER)
        # Whether THIS session has logged in, rather than whether the jar holds a SID: qBittorrent can be
        # configured to bypass authentication for localhost, in which case a successful login sets no
        # cookie at all and reading the jar would log in again before every single call.
        self._logged_in = False
        self._version_checked = False

    @property
    def configured(self) -> bool:
        """A base URL and both credentials are present AND non-empty; `False` disables every call."""
        # Emptiness, not just absence. `TV_QBITTORRENT_USER=` in a .env is a blank line the owner wrote to
        # mean "I have not set this up", and a login posted with an empty username would be a real request
        # that really fails (R91). `Settings` maps a blank to `None` for the same reason; this is the half
        # of the rule that holds for a client constructed directly.
        return bool(self._base_url) and bool(self._username) and _has_a_secret(self._password)

    @property
    def closed(self) -> bool:
        """Whether the pool has been shut - the lifespan's only observable, as the Jellyfin client's is."""
        return self._http.is_closed

    async def webapi_version(self) -> str:
        """`GET /api/v2/app/webapiVersion` - a bare version string, not JSON."""
        return (await self._authenticated(GET, self._url(*_WEBAPI_VERSION), _read_capped_text)).strip()

    async def completed_torrents(self) -> list[QbittorrentTorrent]:
        """`GET /api/v2/torrents/info?filter=completed` - what the owner has already finished downloading."""
        # `filter=completed` is the server's word for it; `progress` and `amount_left` are the torrent's
        # own, and a row that fails either is dropped however the server chose to list it. Belt and
        # braces, because the import pipeline moves whatever comes back out of the staging directory.
        await self._ensure_supported_version()
        url = self._url(*_TORRENTS_INFO, filter=QBITTORRENT_COMPLETED_FILTER)
        torrents = await self._authenticated(GET, url, _read_torrents)
        return [torrent for torrent in torrents if torrent.progress >= 1.0 and torrent.amount_left == 0]

    async def torrent_files(self, torrent_hash: str) -> list[QbittorrentFile]:
        """`GET /api/v2/torrents/files?hash=…` - every file one torrent produced, in the order it lists them.

        Nothing is filtered here. What is small enough to be a sample is the import scan's judgement
        (`MEDIA_IMPORT_MIN_BYTES`), and a filter in this client would hide files from the pass that can
        explain them. Each file's absolute path is `QbittorrentFile.absolute_path(save_path)`.

        A caller that walks `completed_torrents()` should skip any row whose `has_recognised_hash` is
        `False` rather than call this and catch: an unrecognised hash is one torrent to pass over, not a
        reason for an import pass to stop.
        """
        # The hash is checked BEFORE anything else, so a caller-supplied value that is not one reaches
        # neither the version probe nor the login nor the transport.
        checked = _checked_hash(torrent_hash)
        await self._ensure_supported_version()
        return await self._authenticated(GET, self._url(*_TORRENTS_FILES, hash=checked), _read_files)

    async def aclose(self) -> None:
        """The connection pool, closed with the app; it must not outlive the process that opened it."""
        await self._http.aclose()

    async def _ensure_supported_version(self) -> None:
        """The version floor, read once per session and refused by name rather than guessed past."""
        if self._version_checked:
            return
        version = await self.webapi_version()
        if _parsed_version(version) < _MINIMUM_VERSION:
            raise QbittorrentUnsupportedVersionError(
                f"{_PROVIDER}'s Web API is {_message_safe(version)}; this client needs "
                f"{QBITTORRENT_MIN_WEBAPI_VERSION} or newer, because `content_path` arrived in 2.6.1 "
                "and a file's `index` in 2.8.2"
            )
        self._version_checked = True

    async def _authenticated[T](self, method: str, url: str, reader: _BodyReader[T]) -> T:
        """One authenticated call: log in if this session has not, and re-log-in exactly ONCE on a 403."""
        await self._ensure_logged_in()
        try:
            return await self._attempt(method, url, reader)
        except _Forbidden:
            # The session is unauthenticated - the SID expired, or the WebUI restarted. One fresh login.
            self._logged_in = False
        await self._ensure_logged_in()
        try:
            return await self._attempt(method, url, reader)
        except _Forbidden as error:
            # The second refusal is the other documented 403: this IP is banned for repeated failed
            # logins. There is deliberately no third attempt - a retry loop is how that ban is earned.
            raise QbittorrentAuthError(
                f"{_PROVIDER} refused {httpx.URL(url).path} with 403 twice; the documented causes are an "
                "unauthenticated session and an IP ban for repeated failed logins, so this is not retried"
            ) from error

    async def _ensure_logged_in(self) -> None:
        """One login per session, because a login per call is a login storm at a server that bans them."""
        if not self._logged_in:
            await self._login()

    async def _login(self) -> None:
        """`POST /api/v2/auth/login` - the one place the password is read, into the one body it travels in."""
        base_url, username, password = self._configuration()
        # Form-encoded, per the documented parameters. `data=` is what makes httpx encode it as a body;
        # anything that put either value in the URL would put it in every proxy log on the path.
        body = {QBITTORRENT_USERNAME_FIELD: username, QBITTORRENT_PASSWORD_FIELD: password.get_secret_value()}
        try:
            await self._attempt(POST, configured_url(base_url, *_LOGIN), _read_login_ok, data=body)
        except _Forbidden as error:
            raise QbittorrentAuthError(
                f"{_PROVIDER} refused the login with 403; the documented cause is an IP ban for too many "
                "failed login attempts, so this is not retried"
            ) from error
        self._logged_in = True

    async def _attempt[T](
        self, method: str, url: str, reader: _BodyReader[T], *, data: Mapping[str, str] | None = None
    ) -> T:
        """One guarded, streamed call parsed by `reader`; every refusal and outage lands here.

        The login goes through this too, so there is one place that streams, one place that logs and one
        place that reads a failure - `data` is the only thing that distinguishes it.
        """
        started = time.monotonic()
        status: int | None = None
        try:
            async with self._http.stream(method, url, headers=self._headers(), data=data) as response:
                status = response.status_code
                if status == HTTPStatus.FORBIDDEN:
                    raise _Forbidden
                if status != HTTPStatus.OK:
                    raise refusal_for(response, _PROVIDER)
                body, raw = await reader(response)
                self._calls.log(url, status, elapsed_ms_since(started), len(raw), "fresh", method)
                return body
        except _Forbidden:
            # Logged as the failed attempt it is, then handed to the caller's one re-login.
            self._calls.log(url, status, elapsed_ms_since(started), 0, "failed", method)
            raise
        except ProviderError as error:
            self._calls.failed(url, status, elapsed_ms_since(started), error, method=method)
            raise
        except httpx.HTTPError as error:
            raise self._calls.unreachable(url, elapsed_ms_since(started), error, method=method) from error

    def _url(self, *segments: str, **query: str | int | None) -> str:
        """A URL on the configured base, built by the shared builder and never held by anything."""
        base_url, _, _ = self._configuration()
        return configured_url(base_url, *segments, **query)

    def _headers(self) -> dict[str, str]:
        """The two headers qBittorrent requires, derived from the base and never from an inbound request.

        The wiki: "Set `Referer` or `Origin` header to the exact same domain and port as used in the HTTP
        query `Host` header." Both are sent, because a proxy in front of the WebUI may strip either. The
        SID is not here - it rides in the pool's own cookie jar.
        """
        base_url, _, _ = self._configuration()
        origin = _origin(base_url)
        return {QBITTORRENT_REFERER_HEADER: origin, QBITTORRENT_ORIGIN_HEADER: origin}

    def _configuration(self) -> tuple[str, str, SecretStr]:
        """The base and both credentials, or the one refusal: one check, one order, one sentence."""
        if not self.configured or self._base_url is None or self._username is None or self._password is None:
            raise QbittorrentNotConfiguredError(_UNCONFIGURED)
        return self._base_url, self._username, self._password


async def _read_capped_text(response: httpx.Response) -> tuple[str, bytes]:
    """The plain-text bodies - `Ok.` and `2.11.4` - bounded by this client's own cap rather than buffered."""
    return await read_text(response, limit=MAX_QBITTORRENT_RESPONSE_BYTES)


async def _read_login_ok(response: httpx.Response) -> tuple[str, bytes]:
    """The login's body, which the wiki documents as exactly `Ok.` on success."""
    text, raw = await _read_capped_text(response)
    if text.strip() != QBITTORRENT_LOGIN_OK:
        # A 200 that is not `Ok.` is the WebUI's login page, or a proxy in front of it. Either way nothing
        # authenticated us, and the body is deliberately not repeated back.
        raise QbittorrentAuthError(f"{_PROVIDER} answered the login with 200 but not `Ok.`")
    return text, raw


async def _read_torrents(response: httpx.Response) -> tuple[list[QbittorrentTorrent], bytes]:
    """One torrent list, validated before the call is called a success."""
    parsed, raw = await read_json(response, limit=MAX_QBITTORRENT_RESPONSE_BYTES)
    return _validated(parsed, QbittorrentTorrent), raw


async def _read_files(response: httpx.Response) -> tuple[list[QbittorrentFile], bytes]:
    """One torrent's contents, validated before the call is called a success."""
    parsed, raw = await read_json(response, limit=MAX_QBITTORRENT_RESPONSE_BYTES)
    return _validated(parsed, QbittorrentFile), raw


def _validated[T: (QbittorrentTorrent, QbittorrentFile)](parsed: object, model: type[T]) -> list[T]:
    """The body as a list of rows; a shape this client cannot read is an unusable answer, not a crash."""
    if not isinstance(parsed, list):
        raise ProviderUnavailableError(f"{_PROVIDER} answered with something that is not a list of rows")
    try:
        return [model.model_validate(row) for row in parsed]
    except ValidationError as error:
        raise unreadable_shape(_PROVIDER, error) from error


def _has_a_secret(password: SecretStr | None) -> bool:
    """A password that is present and not blank. A blank one is not a credential, it is an empty line."""
    return password is not None and bool(password.get_secret_value())


def _checked_hash(torrent_hash: str) -> str:
    """The one caller-supplied value that reaches a URL, refused unless it is 40 or 64 lowercase hex.

    Forty is a v1 (SHA-1) infohash and sixty-four is a v2 (SHA-256) one, and both are what qBittorrent
    really reports (R85). The value is deliberately not repeated into the message: a hash that failed this
    check is, by definition, a string somebody else chose.
    """
    if not is_recognised_hash(torrent_hash):
        raise OutboundUrlError("a torrent hash must be 40 or 64 lowercase hex characters to reach a qBittorrent URL")
    return torrent_hash


def _message_safe(version: str) -> str:
    """The version, safe to put in a message: newlines removed and length capped.

    The refusal has to say what it found or it is unactionable, and this is the one upstream string this
    client repeats back - so a crafted body cannot end a log record or fill an exception (CLAUDE.md 10.3).
    """
    return scrubbed(version.strip())[:MAX_QBITTORRENT_VERSION_LENGTH]


def _origin(base_url: str) -> str:
    """The scheme, host and port of the base and nothing else - what `Referer` and `Origin` must equal.

    Built from the parsed parts rather than from `netloc`, so any userinfo in a base that somehow got past
    the guard still cannot be written into a header. `urlsplit` strips the brackets an IPv6 literal must
    carry in a URL authority, so they are put back: `http://::1:8080` is not an address at all.
    """
    split = urlsplit(base_url)
    host = split.hostname or ""
    authority = f"[{host}]" if _IPV6_MARKER in host else host
    port = "" if split.port is None else f":{split.port}"
    return f"{split.scheme}://{authority}{port}"


def build_qbittorrent_http(base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """The pool this client holds - the shared configured-upstream builder, at qBittorrent's own timeout."""
    return build_configured_http(base_url, timeout=QBITTORRENT_TIMEOUT_SECONDS, transport=transport)


def build_qbittorrent_client(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> QbittorrentClient:
    """The composition seam: all three values come from settings, and none is required for the app to boot."""
    base_url = settings.qbittorrent_url
    # An unconfigured client still holds a pool, because `configured` is a property of the client rather
    # than of its absence. It is pinned to a loopback port nothing listens on, so even a bug that got past
    # the `configured` refusal is guarded against a dead address rather than against no base at all.
    http = build_qbittorrent_http(base_url or UNCONFIGURED_UPSTREAM_BASE_URL, transport=transport)
    return QbittorrentClient(base_url, settings.qbittorrent_user, settings.qbittorrent_password, http=http)
