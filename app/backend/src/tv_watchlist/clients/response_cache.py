"""What a previous fetch of one resource left behind, the seam a client reads it through, and the
one arithmetic both sides of the cache do on a caching term."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class CachedResponse:
    """The conditional-request state of one resource; every field is unknown until a fetch succeeds."""

    etag: str | None
    last_modified: str | None
    payload_digest: str | None
    last_success_at: datetime | None


def ceiling_cutoff(now: datetime, ceiling_days: int) -> datetime:
    """The oldest `last_success_at` a caching term still allows.

    TMDB's terms cap caching at six months, hard, and two sides act on that: the client renews a cursor
    that has reached it, and `ingest.sync_cursor` lists the cursors that have. It lives here because
    both already import this module, and one licence term written as two comparisons is how they come
    to disagree by a day.
    """
    return now - timedelta(days=ceiling_days)


@runtime_checkable
class ResponseCache(Protocol):
    """Per-resource fetch state. Keys are plain strings: `clients/` never imports `data/`; T15 converts."""

    async def lookup(self, source: str, resource_type: str, resource_key: str) -> CachedResponse | None: ...

    async def store(
        self,
        source: str,
        resource_type: str,
        resource_key: str,
        *,
        etag: str | None,
        last_modified: str | None,
        payload_digest: str,
    ) -> None: ...

    async def record_failure(self, source: str, resource_type: str, resource_key: str, error: str) -> None: ...


class NullResponseCache:
    """Remembers nothing, so every fetch is a fresh one. The dry run and the client unit tests use it."""

    async def lookup(self, source: str, resource_type: str, resource_key: str) -> CachedResponse | None:
        return None

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
        return None

    async def record_failure(self, source: str, resource_type: str, resource_key: str, error: str) -> None:
        return None
