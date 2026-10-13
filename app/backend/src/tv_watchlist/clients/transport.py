"""The one http client shape every provider call is made through, and the one line each call logs.

This module is also the single home for the pieces every provider client needs and none of them owns:
the `Cursor` a call's outcome is recorded against, the `ProviderBody` one 200 parses to, and the two
readings of a non-200 - `refusal_for` and `retry_after_seconds`. They lived privately in each client
until the second client made them a copy (Ruling 31); a refusal that means one thing in TMDB and
another in TheTVDB would be a bug nobody could see from either file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from types import MappingProxyType
from typing import Final, Literal

import httpx

from tv_watchlist.clients.errors import (
    ProviderError,
    ProviderNotFoundError,
    ProviderRefusedError,
    ProviderResponseTooLargeError,
    ProviderUnavailableError,
)
from tv_watchlist.clients.http_guard import assert_within_base
from tv_watchlist.constants import MAX_PROVIDER_RESPONSE_BYTES, PROVIDER_TIMEOUT_SECONDS

# `throttled` is a wait - on the token bucket, or on a 429's backoff - and a wait is not a failure.
# `failed` is the one outcome that says the attempt produced nothing a caller could write.
CacheOutcome = Literal["fresh", "not-modified", "cached", "throttled", "failed"]

# The one Accept every upstream in this project is asked in, so three modules cannot drift on it.
ACCEPT_JSON: Final[Mapping[str, str]] = MappingProxyType({"Accept": "application/json"})

_MISSING_STATUS: Final[str] = "none"
# A crafted path must not be able to end a record and start another one (CLAUDE.md section 10.3).
_NEWLINES: Final[dict[int, None]] = str.maketrans("", "", "\r\n")


@dataclass(frozen=True, slots=True)
class Cursor:
    """Which `sync_state` row a call's outcome belongs to.

    `None` at a call site means there is no row to record: a TMDB search is a query rather than a
    resource, and a TheTVDB login is a credential exchange rather than either.
    """

    resource_type: str
    resource_key: str


@dataclass(frozen=True, slots=True)
class ProviderBody:
    """One 200: what it parsed to, the digest of the bytes it parsed, its cursor headers and its timings."""

    parsed: object
    digest: str
    etag: str | None
    last_modified: str | None
    elapsed_ms: int
    bytes_read: int


def elapsed_ms_since(started: float) -> int:
    """Milliseconds since a `time.monotonic()` reading, which is the only clock a duration is measured on."""
    return int((time.monotonic() - started) * 1000)


def retry_after_seconds(header: str | None) -> float | None:
    """The `Retry-After` delay in seconds, or `None` when the header is absent or is an HTTP-date."""
    if header is None:
        return None
    try:
        return float(header)
    except ValueError:
        return None


def refusal_for(response: httpx.Response, provider: str) -> ProviderError:
    """What one non-200, non-304 status means. Only the status and the path appear - never a body."""
    status = response.status_code
    if status == HTTPStatus.NOT_FOUND:
        return ProviderNotFoundError(f"{provider} has no resource at {response.url.path}")
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        return ProviderRefusedError(
            f"{provider} refused {response.url.path} with {status}",
            retry_after_seconds(response.headers.get("retry-after")),
        )
    if HTTPStatus.BAD_REQUEST <= status < HTTPStatus.INTERNAL_SERVER_ERROR:
        return ProviderRefusedError(f"{provider} refused {response.url.path} with {status}")
    # 5xx, and the 3xx a non-following client reports rather than chases.
    return ProviderUnavailableError(f"{provider} answered {response.url.path} with {status}")


def unreachable(provider: str, error: httpx.HTTPError) -> ProviderUnavailableError:
    """What one transport failure means. The error's CLASS name, and deliberately never its text.

    `httpx.LocalProtocolError` is an `HTTPError`, and h11 builds its message by quoting the whole offending
    header back: a credential carrying a CR, an LF or a NUL produces `Illegal header value b'Bearer ...'`.
    Interpolating `{error}` here would therefore carry that credential into the raised message, into
    `sync_state.last_error`, into the call log and into whatever a route made of it. Every client's
    unreachable path goes through this one function so there is one place that rule can be true
    (CLAUDE.md section 10.3, B10 and B16). The caller still raises `from error`, so a traceback keeps
    everything this message leaves out.
    """
    return ProviderUnavailableError(f"{provider} could not be reached ({type(error).__name__})")


def build_provider_http(
    base_url: str,
    *,
    headers: Mapping[str, str],
    transport: httpx.AsyncBaseTransport | None = None,
    guard: Callable[[str, str], None] = assert_within_base,
    timeout: float = PROVIDER_TIMEOUT_SECONDS,
) -> httpx.AsyncClient:
    """A client pinned to one base: fixed timeout, no redirects, every request guarded on the way out.

    `guard` and `timeout` are defaulted to the public-provider rule, so both provider clients are unchanged
    and neither can be relaxed by something another upstream needed. Jellyfin passes
    `assert_within_configured_base`, which is the one configured LAN upstream (CLAUDE.md section 10.3, B16);
    a second near-identical builder for it would be the thing that eventually drifts.
    """

    async def guarded(request: httpx.Request) -> None:
        guard(str(request.url), base_url)

    return httpx.AsyncClient(
        base_url=base_url,
        headers=dict(headers),
        timeout=timeout,
        # A redirect would have to be re-checked against the base, and no provider endpoint issues one;
        # a hop is reported back as the status it is rather than followed.
        follow_redirects=False,
        transport=transport,
        event_hooks={"request": [guarded]},
    )


async def _read_capped(response: httpx.Response, limit: int) -> bytes:
    """Every byte up to `limit`, and a refusal rather than a truncation past it."""
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            # The reader that stopped pulling is the one that closes the door. A caller's
            # `async with client.stream(...)` is a convention, and an abandoned body would hold its
            # connection open until the pool reaped it. `aclose` is idempotent, so a caller that does
            # wrap the call loses nothing.
            await response.aclose()
            raise ProviderResponseTooLargeError(f"the upstream answered {response.status_code} with over {limit} bytes")
    return bytes(body)


async def read_json(response: httpx.Response, *, limit: int = MAX_PROVIDER_RESPONSE_BYTES) -> tuple[object, bytes]:
    """The parsed body and the bytes it came from, refused rather than truncated once past `limit`."""
    raw = await _read_capped(response, limit)
    try:
        return json.loads(raw), raw
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        await response.aclose()
        raise ProviderUnavailableError(
            f"the upstream answered {response.status_code} with something that is not JSON ({type(error).__name__})"
        ) from error


async def read_text(response: httpx.Response, *, limit: int = MAX_PROVIDER_RESPONSE_BYTES) -> tuple[str, bytes]:
    """The decoded body and the bytes it came from, refused rather than truncated once past `limit`.

    The sibling of `read_json` for the endpoints that do not answer JSON - Jellyfin's `/health` is plain
    text and its `/Library/Refresh` answers 204 with nothing at all. Both still need a capped read, because
    a buffered `.get()` pulls whatever the upstream sends: a server that is mid-crash, or one that is not
    the server we think it is, can answer a health probe with a megabyte of HTML.
    """
    raw = await _read_capped(response, limit)
    # `replace`, never `strict`: this reader exists so a body can be bounded and logged, and a byte that is
    # not UTF-8 is a thing to report rather than a second exception on the failure path.
    return raw.decode("utf-8", errors="replace"), raw


def payload_digest(body: bytes) -> str:
    """sha256 over the body re-serialised with sorted keys and no spacing: neither is a change worth a rewrite."""
    try:
        canonical = json.dumps(json.loads(body), sort_keys=True, separators=(",", ":"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        # Nothing public in `clients/` raises outside the ProviderError hierarchy, so an ingest can
        # catch one base class and record the detail.
        raise ProviderUnavailableError(
            f"a digest was asked for bytes that are not JSON ({type(error).__name__})"
        ) from error
    return hashlib.sha256(canonical.encode()).hexdigest()


def log_call(
    logger: logging.Logger,
    *,
    method: str,
    host: str,
    path: str,
    status: int | None,
    elapsed_ms: int,
    bytes_read: int,
    outcome: CacheOutcome,
) -> None:
    """One key=value record per outbound call. Never a header, never a body, never a credential."""
    logger.info(
        "provider_call method=%s host=%s path=%s status=%s elapsed_ms=%d bytes=%d outcome=%s",
        scrubbed(method),
        scrubbed(host),
        scrubbed(path),
        _MISSING_STATUS if status is None else status,
        elapsed_ms,
        bytes_read,
        scrubbed(outcome),
    )


def scrubbed(value: str) -> str:
    """A value with its newlines removed, so nothing logged can end one record and forge another."""
    return value.translate(_NEWLINES)
