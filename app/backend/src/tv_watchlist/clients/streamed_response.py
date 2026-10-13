"""What a caller relaying an upstream media stream is allowed to see of it."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StreamedResponse:
    """One live upstream response, narrowed to the three things a relay may pass on.

    It exists so that the raw `httpx.Response` never leaves the client. A caller holding one of those holds
    every upstream header - a `Set-Cookie`, a `Server`, an upstream `WWW-Authenticate` - and the proxy's
    job is to relay a body, not an identity (CLAUDE.md section 10.3, B17). `headers` is already the
    allowlist; nothing filters it downstream, because nothing downstream can see anything else.

    `body` is the live byte iterator, so a multi-gigabyte remux is never buffered. It is valid only inside
    the `async with` that produced this object; the connection closes when that block exits.
    """

    status_code: int
    headers: Mapping[str, str]
    body: AsyncIterator[bytes]
