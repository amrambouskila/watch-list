"""`sync_state` as the provider response cache: ETag and `Last-Modified` cursors, a payload digest,
the failure backoff, and the six-month term TMDB's licence caps caching at.

There is no Redis and no second datastore: this table IS the cache (CLAUDE.md section 2.2). Every
decision the cache makes - the backoff schedule, the cutoff, the due predicate, the redaction - is a
module-level function of its arguments, so it is proved on a workstation with no Postgres on it and
only the SQL needs the service container.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import ColumnElement, and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clients.response_cache import CachedResponse, ceiling_cutoff
from tv_watchlist.clock import utcnow
from tv_watchlist.constants import (
    MAX_LAST_ERROR_CHARS,
    PROVIDER_BACKOFF_BASE_SECONDS,
    PROVIDER_BACKOFF_MAX_SECONDS,
    TMDB_CACHE_CEILING_DAYS,
)
from tv_watchlist.data.enums import ExternalSource, SyncResourceType
from tv_watchlist.data.models import SyncState

# How many doublings the cap can absorb, derived from the two constants rather than written down.
# Past it the schedule is flat, and `2 ** consecutive_failures` for an unbounded count would build an
# integer no arithmetic wants.
_MAX_DOUBLINGS: Final[int] = math.ceil(math.log2(PROVIDER_BACKOFF_MAX_SECONDS / PROVIDER_BACKOFF_BASE_SECONDS))
# A provider error can only carry this project's credential in one shape, because the token travels in
# an `Authorization: Bearer` header and nowhere else (CLAUDE.md section 10.3, B10).
_BEARER: Final[re.Pattern[str]] = re.compile(r"\bbearer\s+\S+", re.IGNORECASE)
_REDACTED: Final[str] = "Bearer [redacted]"
# `last_error` is provider-supplied text that later reaches a log line and a reader's screen. The whole
# C0 range goes, CR and LF among it: a crafted message must not be able to end one log record and forge
# another (CLAUDE.md section 10.3, header/log injection), and no escape sequence belongs in a cursor.
_CONTROL_CHARACTERS: Final[dict[int, None]] = dict.fromkeys(range(0x20))


def backoff_delay(consecutive_failures: int) -> timedelta:
    """The wait a cursor earns after its nth consecutive failure: the base, doubled per failure, capped."""
    doublings = min(max(consecutive_failures - 1, 0), _MAX_DOUBLINGS)
    return timedelta(seconds=min(PROVIDER_BACKOFF_BASE_SECONDS * 2.0**doublings, PROVIDER_BACKOFF_MAX_SECONDS))


def attempt_is_due(next_attempt_at: datetime | None, now: datetime) -> bool:
    """A cursor with no stamp is waiting for nothing; one whose stamp has arrived may be fetched again."""
    return next_attempt_at is None or next_attempt_at <= now


def success_past_ceiling(last_success_at: datetime | None, now: datetime, ceiling_days: int) -> bool:
    """A cursor that has never succeeded is caching nothing, so no caching term has run out on it."""
    return last_success_at is not None and last_success_at <= ceiling_cutoff(now, ceiling_days)


def _redact(error: str) -> str:
    """The message as `last_error` may hold it: no credential, no control character, and bounded.

    Clipped last, so no length ever decides whether a token survives.
    """
    return _BEARER.sub(_REDACTED, error).translate(_CONTROL_CHARACTERS)[:MAX_LAST_ERROR_CHARS]


# The conflict target every write infers against: `uq(source, resource_type, resource_key)`. Bare
# `Final` so the mapped attributes keep their own column types rather than being widened to a lie.
_CURSOR_COLUMNS: Final = (SyncState.source, SyncState.resource_type, SyncState.resource_key)


def _matching(cursor: tuple[ExternalSource, SyncResourceType], resource_key: str) -> ColumnElement[bool]:
    """That same unique key, as the predicate the four reads select on."""
    return and_(
        SyncState.source == cursor[0], SyncState.resource_type == cursor[1], SyncState.resource_key == resource_key
    )


def _cursor_key(source: str, resource_type: str) -> tuple[ExternalSource, SyncResourceType]:
    """The plain strings `clients/` speaks, as the vocabulary the columns store.

    `clients/` never imports `data/`, so the two sides agree by value. A drift raises a `ValueError`
    here, at the one boundary that knows both, rather than writing a row nothing can read back.
    """
    return ExternalSource(source), SyncResourceType(resource_type)


class PostgresResponseCache:
    """The `ResponseCache` the provider clients consult, backed by `sync_state`.

    It is handed the ingest transaction's own session deliberately: a cursor that committed
    independently would record a digest as unchanged after the ingest rolled back, and the rows that
    ingest meant to write would never land.
    """

    def __init__(self, session: AsyncSession, *, clock: Callable[[], datetime] = utcnow) -> None:
        self._session = session
        self._clock = clock

    async def lookup(self, source: str, resource_type: str, resource_key: str) -> CachedResponse | None:
        """What the last successful fetch of this resource left behind, or `None` if there has not been one."""
        cursor = _cursor_key(source, resource_type)
        row = (
            await self._session.execute(
                select(
                    SyncState.etag, SyncState.last_modified, SyncState.payload_digest, SyncState.last_success_at
                ).where(_matching(cursor, resource_key))
            )
        ).one_or_none()
        if row is None:
            return None
        return CachedResponse(
            etag=row.etag,
            last_modified=row.last_modified,
            payload_digest=row.payload_digest,
            last_success_at=row.last_success_at,
        )

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
        """Record a fetch that came back 200: new validators, and a clean slate for the backoff."""
        cursor = _cursor_key(source, resource_type)
        now = self._clock()
        recorded = {
            "etag": etag,
            "last_modified": last_modified,
            "payload_digest": payload_digest,
            "last_attempt_at": now,
            # Written with the validators, always and in the same statement. The client reads the
            # six-month term off `last_success_at`, so a cursor holding an ETag with no success stamp
            # would read as cached forever; the pairing is made impossible here rather than guarded
            # against downstream.
            "last_success_at": now,
            "next_attempt_at": None,
            "consecutive_failures": 0,
            "last_error": None,
        }
        await self._session.execute(
            insert(SyncState)
            .values(source=cursor[0], resource_type=cursor[1], resource_key=resource_key, **recorded)
            .on_conflict_do_update(index_elements=_CURSOR_COLUMNS, set_={**recorded, "updated_at": func.now()})
        )

    async def record_failure(self, source: str, resource_type: str, resource_key: str, error: str) -> None:
        """One more consecutive failure and the wait it earns. The message only; never a header, never a body."""
        cursor = _cursor_key(source, resource_type)
        now = self._clock()
        message = _redact(error)
        written = (
            await self._session.execute(
                insert(SyncState)
                .values(
                    source=cursor[0],
                    resource_type=cursor[1],
                    resource_key=resource_key,
                    last_attempt_at=now,
                    consecutive_failures=1,
                    last_error=message,
                )
                .on_conflict_do_update(
                    index_elements=_CURSOR_COLUMNS,
                    set_={
                        "last_attempt_at": now,
                        "consecutive_failures": SyncState.consecutive_failures + 1,
                        "last_error": message,
                        "updated_at": func.now(),
                    },
                )
                .returning(SyncState.id, SyncState.consecutive_failures)
            )
        ).one()
        # The count comes back from the row the database actually wrote rather than from one read
        # beforehand, so the stamp and the count can never disagree and `backoff_delay` stays the only
        # place the schedule is written.
        await self._session.execute(
            update(SyncState)
            .where(SyncState.id == written.id)
            .values(next_attempt_at=now + backoff_delay(written.consecutive_failures))
        )

    async def is_due(self, source: str, resource_type: str, resource_key: str) -> bool:
        """True when nothing has been recorded for this resource yet, or its backoff has run out."""
        cursor = _cursor_key(source, resource_type)
        row = (
            await self._session.execute(select(SyncState.next_attempt_at).where(_matching(cursor, resource_key)))
        ).one_or_none()
        return row is None or attempt_is_due(row.next_attempt_at, self._clock())

    async def past_ceiling(
        self, source: str, resource_type: str, resource_key: str, *, ceiling_days: int = TMDB_CACHE_CEILING_DAYS
    ) -> bool:
        """TMDB's terms cap caching at six months, hard: past the term a cursor is refetched, not reused."""
        cursor = _cursor_key(source, resource_type)
        row = (
            await self._session.execute(select(SyncState.last_success_at).where(_matching(cursor, resource_key)))
        ).one_or_none()
        if row is None:
            return False
        return success_past_ceiling(row.last_success_at, self._clock(), ceiling_days)

    async def due_for_refresh(
        self, source: str, *, ceiling_days: int = TMDB_CACHE_CEILING_DAYS, limit: int = 500
    ) -> list[SyncState]:
        """One source's cursors whose cached payload has reached the term, oldest first.

        The scheduled refresh the six-month clause requires. `limit` caps one pass, defaulting to more
        rows than the nineteen workbooks can produce cursors for. A cursor that has never succeeded is
        absent by construction: `NULL` satisfies no comparison, and it is caching nothing to refresh.
        """
        known = ExternalSource(source)
        cutoff = ceiling_cutoff(self._clock(), ceiling_days)
        rows = await self._session.scalars(
            select(SyncState)
            .where(SyncState.source == known, SyncState.last_success_at <= cutoff)
            .order_by(SyncState.last_success_at)
            .limit(limit)
        )
        return list(rows)
