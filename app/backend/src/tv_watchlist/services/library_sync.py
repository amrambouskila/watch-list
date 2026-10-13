"""Building and refreshing the `tmdb_id -> Jellyfin Id` index the availability layer reads.

Jellyfin has **no provider-id lookup endpoint** - there is no `?tmdbId=` filter anywhere in 12.1's API -
so the only way to answer "is this title in the library" is to walk the library once and keep the answer
(CLAUDE.md section 20.2, item 1). That walk is this module, and `jellyfin_item` is where it lands.

Four rules govern every line here:

1. **Series are matched by provider id ONLY.** Nothing in this file compares a Jellyfin `Name` to a
   title, ever. An anime carries a romaji name, an English name and a handful of synonyms, and a fuzzy
   match on any of them is a wrong file that plays silently. An item whose `ProviderIds` holds no usable
   TMDB id is indexed with `tmdb_id` NULL and joins to nothing - which is an honest "not in library"
   rather than a guess (CLAUDE.md section 10.3, and the master plan's 10.3 acceptance line).
2. **A vanished file is marked, never deleted.** `title.jellyfin_item_id` may point at the row, and the
   owner's pick must survive a file being moved and re-indexed.
3. **Only a FULL scan may soft-delete.** An incremental walk asks for what changed since a cursor, so
   absence from it proves nothing at all. Conflating the two would mark a whole library removed the first
   time an incremental pass returned little.
4. **The owner's pick is never written here.** This job maintains the index; `title.jellyfin_item_id` is
   T56's to set, and this file only has to leave it standing.

The scan is reconciled from two halves of the plan that were each right about one of them: movies and
series come from the paged `/Items` walk with `hasTmdbId=true`; episode rows come from
`GET /Shows/{seriesId}/Episodes` per series, because an episode rarely carries its own TMDB id and the
scan's own filter would exclude every one of them.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Final

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clients.errors import ProviderError
from tv_watchlist.clients.jellyfin_client import JellyfinClient
from tv_watchlist.clients.transport import elapsed_ms_since, scrubbed
from tv_watchlist.clock import utcnow
from tv_watchlist.constants import (
    JELLYFIN_EPISODE_TYPE,
    JELLYFIN_INDEXED_ITEM_TYPES,
    JELLYFIN_MOVIE_TYPE,
    JELLYFIN_SERIES_TYPE,
    LIBRARY_SYNC_ADVISORY_LOCK_KEY,
    LIBRARY_SYNC_JOB,
    MAX_JELLYFIN_ID_LENGTH,
)
from tv_watchlist.data.enums import JellyfinItemKind
from tv_watchlist.data.errors import JellyfinUnavailableError
from tv_watchlist.data.models import JellyfinItem
from tv_watchlist.models.jellyfin.jellyfin_item_dto import JellyfinItemDto
from tv_watchlist.models.library_sync_result import LibrarySyncResult

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

# Jellyfin's `Type` vocabulary is far wider than this - `Folder`, `BoxSet`, `Audio`, `Video` - and an
# item of any other type is skipped rather than stored under a label `JellyfinItemKind` would have to
# grow for. The request already filters, so reaching the `else` means the server sent something unasked.
_KIND_BY_TYPE: Final[dict[str, JellyfinItemKind]] = {
    JELLYFIN_MOVIE_TYPE: JellyfinItemKind.MOVIE,
    JELLYFIN_SERIES_TYPE: JellyfinItemKind.SERIES,
    JELLYFIN_EPISODE_TYPE: JellyfinItemKind.EPISODE,
}

# Everything one scan may change about a row. `jellyfin_id` is absent because it is the key the upsert
# is keyed on, and the three stamps are absent because they are this job's bookkeeping rather than the
# server's report. A row whose every field here already matches is not written at all.
_MUTABLE_FIELDS: Final[tuple[str, ...]] = (
    "kind",
    "name",
    "tmdb_id",
    "series_jellyfin_id",
    "parent_index_number",
    "index_number",
    "index_number_end",
    "run_time_seconds",
    "path",
    "date_last_saved",
)

# The one `text()` in this module, and it is one because `pg_advisory_xact_lock` is a Postgres function
# SQLAlchemy has no construct for. The key is a NAMED bind over a module constant - never a literal
# spliced into the string, and never anything a caller supplied.
_ADVISORY_LOCK: Final = text("SELECT pg_advisory_xact_lock(:key)")
# The delta walk an incremental pass makes for episodes. `has_tmdb_id` is left OFF entirely rather than
# set true: an episode file almost never carries its own TMDB id, and the filter would exclude it.
_EPISODE_TYPES: Final[tuple[str, ...]] = (JELLYFIN_EPISODE_TYPE,)

_UNCONFIGURED: Final[str] = "Jellyfin is not configured, so there is no library to index"
_UNREACHABLE: Final[str] = "Jellyfin did not answer ({reason})"


async def sync_library(
    session: AsyncSession,
    client: JellyfinClient,
    *,
    full: bool = False,
    since: datetime | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> LibrarySyncResult:
    """Walk the owner's Jellyfin into `jellyfin_item`, and report what one pass changed.

    Idempotent: a second pass over an unchanged library issues no UPDATE at all and reports
    `added == updated == removed == 0` with `seen` unchanged.

    Raises `JellyfinUnavailableError` when the client is unconfigured or the server did not answer, so
    the route reaches the normal error-envelope path (503) rather than carrying a check of its own (R72).
    Nothing is written in either case: the whole walk is collected before a single row is touched.
    """
    started = time.monotonic()
    synced_at = clock()
    # FIRST, before anything else reads or decides: two overlapping passes would otherwise both see a row
    # as absent and both INSERT it, and the second would land on `uq_jellyfin_item_jellyfin_id` as a 500.
    # Held for the transaction, so the waiting pass resumes with the first one's rows already visible
    # (READ COMMITTED gives each statement after the lock a fresh snapshot). Released by commit OR by
    # rollback, so even the refusal below cannot strand it.
    await session.execute(_ADVISORY_LOCK, {"key": LIBRARY_SYNC_ADVISORY_LOCK_KEY})
    if not client.configured:
        _failed(started, JellyfinUnavailableError(_UNCONFIGURED))
        raise JellyfinUnavailableError(_UNCONFIGURED)
    cursor = None if full else await _cursor(session, since)
    records = await _walk(client, cursor, started)
    counts = await _apply(session, records, synced_at=synced_at, incremental=cursor is not None)
    await session.flush()
    result = LibrarySyncResult(
        seen=len(records),
        added=counts[0],
        updated=counts[1],
        removed=counts[2],
        synced_at=synced_at,
        incremental=cursor is not None,
    )
    _LOGGER.info(
        "library_sync job=%s incremental=%s seen=%d added=%d updated=%d removed=%d elapsed_ms=%d outcome=%s",
        LIBRARY_SYNC_JOB,
        result.incremental,
        result.seen,
        result.added,
        result.updated,
        result.removed,
        elapsed_ms_since(started),
        "synced",
    )
    return result


async def _cursor(session: AsyncSession, since: datetime | None) -> datetime | None:
    """The `minDateLastSaved` an incremental walk is filtered on, or `None` for a full scan.

    Three steps, in this order (R87):

    1. **The caller's `since`**, which is how a scheduler hands back the previous pass's own `synced_at`.
    2. **`max(last_seen_at)` over live rows** - the last moment this job wrote anything. A stamp this app
       controls, unlike `date_last_saved`, which 12.1's `BaseItemDto` does not declare at all and which a
       server may therefore never send: a cursor derived from it would be `NULL` forever, and every pass
       would be a full walk. A pass that wrote nothing leaves the stamp where it was, so the next one
       re-asks from an older moment and **over**-fetches. That direction is the safe one; under-fetching
       is what makes a healthy library read as emptied, which is why the max is never taken over
       `date_last_saved` even when some rows carry it.
    3. **Nothing at all**, when the table holds no live rows - an empty index has nothing to be
       incremental about, and the first pass has to see the whole library.

    `date_last_saved` is still stored, because the picker and a later diagnosis read it; it is simply not
    the cursor.
    """
    if since is not None:
        return since
    return (
        await session.execute(select(func.max(JellyfinItem.last_seen_at)).where(JellyfinItem.removed_at.is_(None)))
    ).scalar_one()


async def _walk(client: JellyfinClient, cursor: datetime | None, started: float) -> dict[str, dict[str, object]]:
    """Every item one pass saw, keyed by Jellyfin id, collected before anything is written.

    Collected rather than streamed into the session on purpose: an outage halfway through a walk must
    leave the index exactly as it was, and "nothing was written" is then a property of this function
    rather than of whether the caller remembered not to commit.
    """
    records: dict[str, dict[str, object]] = {}
    series_ids: list[str] = []
    try:
        async for item in client.iter_items(include_item_types=JELLYFIN_INDEXED_ITEM_TYPES, min_date_last_saved=cursor):
            kind = _absorb(records, item)
            if kind is JellyfinItemKind.SERIES:
                series_ids.append(item.id)
        if cursor is not None:
            # An incremental pass's second walk, and it is not optional: a new episode file arrives without
            # its SERIES record being re-saved, so the scan above would not return that series and the
            # per-series calls below would never reach the new file. Asking for changed episodes directly
            # is the only way an incremental pass ever sees one; `SeriesId` on each is what links it back.
            async for episode in client.iter_items(
                include_item_types=_EPISODE_TYPES, has_tmdb_id=None, min_date_last_saved=cursor
            ):
                _absorb(records, episode)
        for series_id in series_ids:
            # One call per series, and only for the series this pass actually saw - an incremental walk
            # therefore re-reads the episodes of a changed show and nothing else.
            for episode in (await client.series_episodes(series_id)).items:
                _absorb(records, episode)
    except ProviderError as error:
        failure = JellyfinUnavailableError(_UNREACHABLE.format(reason=type(error).__name__))
        _failed(started, failure)
        raise failure from error
    return records


def _absorb(records: dict[str, dict[str, object]], item: JellyfinItemDto) -> JellyfinItemKind | None:
    """Record one item, or skip a type this index does not hold, and answer which it was."""
    kind = _KIND_BY_TYPE.get(item.kind)
    if kind is None:
        # Server-supplied free text in a log line: scrubbed of CR/LF so it cannot forge a record, and
        # bounded so a megabyte of it cannot fill the log (CLAUDE.md section 10.3, header/log injection).
        _LOGGER.info(
            "library_sync_skipped job=%s type=%s", LIBRARY_SYNC_JOB, scrubbed(item.kind)[:MAX_JELLYFIN_ID_LENGTH]
        )
        return None
    records[item.id] = {
        "kind": kind,
        "name": item.name,
        # The ONE reading of `ProviderIds`, through the DTO's single constant. No name is ever compared.
        "tmdb_id": item.provider_ids.tmdb_id,
        "series_jellyfin_id": item.series_id,
        "parent_index_number": item.parent_index_number,
        "index_number": item.index_number,
        "index_number_end": item.index_number_end,
        # A zero-tick runtime is not a runtime, and the column's CHECK says so; absent is the honest value.
        "run_time_seconds": item.run_time_seconds or None,
        "path": item.path,
        "date_last_saved": item.date_last_saved,
    }
    return kind


async def _apply(
    session: AsyncSession,
    records: dict[str, dict[str, object]],
    *,
    synced_at: datetime,
    incremental: bool,
) -> tuple[int, int, int]:
    """Insert, update and soft-delete, and answer `(added, updated, removed)`."""
    existing = {row.jellyfin_id: row for row in await session.scalars(select(JellyfinItem))}
    added = updated = removed = 0
    for jellyfin_id, values in records.items():
        row = existing.get(jellyfin_id)
        if row is None:
            session.add(
                JellyfinItem(jellyfin_id=jellyfin_id, first_seen_at=synced_at, last_seen_at=synced_at, **values)
            )
            added += 1
        elif _rewrite(row, values, synced_at):
            updated += 1
    if not incremental:
        # Only here. An incremental walk asked for a slice, so absence from it is not a vanished file.
        for jellyfin_id, row in existing.items():
            if jellyfin_id not in records and row.removed_at is None:
                row.removed_at = synced_at
                removed += 1
    return added, updated, removed


def _rewrite(row: JellyfinItem, values: dict[str, object], synced_at: datetime) -> bool:
    """Write one row only if the server's report differs from it, and say whether anything was written.

    The comparison is what keeps a scan over an unchanged library free of UPDATEs, which is the whole
    reason `last_seen_at` records when the row was last WRITTEN rather than when it was last observed.
    """
    stale = [name for name in _MUTABLE_FIELDS if getattr(row, name) != values[name]]
    if not stale and row.removed_at is None:
        return False
    for name in stale:
        setattr(row, name, values[name])
    # A file that came back: the mark is cleared, and the owner's pick on `title` was never touched.
    row.removed_at = None
    row.last_seen_at = synced_at
    return True


def _failed(started: float, error: JellyfinUnavailableError) -> None:
    """One record per refused pass, carrying the reason's class name and never the upstream's text."""
    _LOGGER.info(
        "library_sync job=%s incremental=%s seen=%d added=%d updated=%d removed=%d elapsed_ms=%d outcome=%s",
        LIBRARY_SYNC_JOB,
        False,
        0,
        0,
        0,
        0,
        elapsed_ms_since(started),
        type(error).__name__,
    )
