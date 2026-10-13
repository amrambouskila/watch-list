"""What the two clients that talk to a CONFIGURED upstream share, so neither can drift from the other.

A configured upstream is a server the owner runs - Jellyfin, qBittorrent - whose origin is configuration
rather than a constant, and which therefore sits on plain `http` on a loopback or LAN address. That single
difference from a public provider is what `clients/http_guard.assert_within_configured_base` exists for,
and everything in this module is the rest of the shape that goes with it:

- **one pool builder**, pinned to the base, no redirects, every request guarded on the way out;
- **one call log**, so both clients print the same key=value record an operator learns to read once;
- **one reading of a failure** - a refusal, an outage and an unreadable body are the same outcome (nothing
  a caller could use arrived) and are recorded the same way, by class name and never by message.

This module was extracted (R90) after the second such client was written and its private tail turned out
to be a verbatim copy of the first's. Two copies of "never repeat an upstream error's text" is one copy
too many: the rule has to be true in one place or it is a convention somebody will eventually not follow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import httpx
from pydantic import ValidationError

from tv_watchlist.clients.errors import ProviderUnavailableError
from tv_watchlist.clients.http_guard import assert_within_configured_base
from tv_watchlist.clients.transport import (
    ACCEPT_JSON,
    CacheOutcome,
    build_provider_http,
    log_call,
    scrubbed,
    unreachable,
)

# The two methods this project ever sends to a configured upstream, spelled once.
GET: Final[str] = "GET"
POST: Final[str] = "POST"

_FAILED: Final[CacheOutcome] = "failed"
_NO_BYTES: Final[int] = 0


def build_configured_http(
    base_url: str, *, timeout: float, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """A pool pinned to one configured base: fixed timeout, no redirects, every request guarded.

    The base is checked here as well, for callers that build a pool directly - but this is NOT where a
    misconfiguration is meant to surface. `Settings` validates both configured bases at boot (R80), because
    these pools are built inside lazy singletons and would otherwise first fail hours later, mid-use.
    """
    assert_within_configured_base(base_url, base_url)
    return build_provider_http(
        base_url,
        headers=ACCEPT_JSON,
        transport=transport,
        guard=assert_within_configured_base,
        timeout=timeout,
    )


def unreadable_shape(provider: str, error: ValidationError) -> ProviderUnavailableError:
    """A body whose shape a client cannot read: an unusable answer, not a crash.

    The problem COUNT, never the problems themselves. `ValidationError.errors()` embeds the input values,
    so a file path, a release name or a title would land in whatever a caller made of this message. The
    caller still raises `from error`, so a traceback keeps every one of them.
    """
    return ProviderUnavailableError(
        f"{provider} answered with a shape this client cannot read ({error.error_count()} problems)"
    )


@dataclass(frozen=True, slots=True)
class UpstreamCalls:
    """One configured upstream's call log, and the two ways a call can produce nothing usable."""

    logger: logging.Logger
    provider: str

    def log(
        self, url: str, status: int | None, elapsed_ms: int, bytes_read: int, outcome: CacheOutcome, method: str
    ) -> None:
        """One key=value record per outbound call, carrying the method that was actually sent."""
        parsed = httpx.URL(url)
        log_call(
            self.logger,
            method=method,
            host=parsed.host,
            path=parsed.path,
            status=status,
            elapsed_ms=elapsed_ms,
            bytes_read=bytes_read,
            outcome=outcome,
        )

    def failed(self, url: str, status: int | None, elapsed_ms: int, error: BaseException, *, method: str) -> None:
        """A refusal, an outage and an unreadable body are one outcome: nothing a caller could use arrived."""
        # There is no `sync_state` row behind either of these clients, so the reason is logged as its class
        # name and nothing more - a message could carry a path, a title or a credential.
        self.log(url, status, elapsed_ms, _NO_BYTES, _FAILED, method)
        self.logger.info(
            "%s_call_failed path=%s reason=%s",
            self.provider.lower(),
            scrubbed(httpx.URL(url).path),
            type(error).__name__,
        )

    def unreachable(
        self, url: str, elapsed_ms: int, error: httpx.HTTPError, *, method: str
    ) -> ProviderUnavailableError:
        """One outage, recorded once; there is no retry here and there must never be one.

        `transport.unreachable` is what keeps the error's TEXT out of the message, which is what stops a
        credential carrying a CR, an LF or a NUL arriving here inside h11's complaint about the header it
        was written into (CLAUDE.md section 10.3, B16 and B21).
        """
        failure = unreachable(self.provider, error)
        self.failed(url, None, elapsed_ms, failure, method=method)
        return failure
