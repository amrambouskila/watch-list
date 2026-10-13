"""One category's curated rows, read out of the Postgres projection.

Served alongside the workbook-backed `CategoryDetail`, never instead of it: the sheet stays the editing
contract and the authority for order, and this is the derived side that carries episodes, resolution and
progress (CLAUDE.md sections 0.2 and 13.5).

The one rule that governs every line here: **nothing crosses the `from_attributes` boundary unless it was
eagerly loaded**. Every relationship on the ORM models is `lazy="raise_on_sql"`, so a missed `selectinload`
raises at serialisation time - which is what a `MissingGreenlet` would otherwise have been, several frames
deeper and without naming the relationship.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from stat import S_ISREG
from typing import Final
from uuid import UUID

from sqlalchemy import DateTime, Integer, Select, String, Uuid, column, select, table
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tv_watchlist.clients.jellyfin_client import JellyfinClient
from tv_watchlist.config import Settings
from tv_watchlist.constants import MAX_ENTRIES_PAGE_SIZE
from tv_watchlist.data.enums import ArtworkKind, WatchEventKind
from tv_watchlist.data.models import Artwork, Category, CuratedEntry, Title
from tv_watchlist.models.curated_entry_read import CuratedEntryRead
from tv_watchlist.models.entry_progress import EntryProgress
from tv_watchlist.models.title_read import TitleRead
from tv_watchlist.services.availability import NOT_IN_LIBRARY, availability_for
from tv_watchlist.services.entry_availability import EntryAvailability
from tv_watchlist.workbook import discovery

# The view revision 0001 raises, declared lightweight rather than as a model: a view is not a table, and
# `env.py`'s include_object hook deliberately keeps both views out of `Base.metadata`. `kind` is read as
# a plain string because that is what asyncpg hands back for a native enum; Pydantic makes it a
# `WatchEventKind`, and a label added by a later revision therefore needs no change here.
WATCH_STATE: Final = table(
    "curated_entry_watch_state",
    column("curated_entry_id", Uuid(as_uuid=True)),
    column("kind", String),
    column("episode_total", Integer),
    column("episode_completed", Integer),
    column("episode_skipped", Integer),
    column("episode_started", Integer),
    column("as_of", DateTime(timezone=True)),
)

# What an entry reports when the view has no row for it. The view's own WHERE is `removed_at IS NULL`,
# the same predicate the page uses, so the only way here is a concurrent ingest soft-deleting a row
# between the two statements - a race that must read as "nothing recorded", never as a 500.
UNSET_PROGRESS: Final[EntryProgress] = EntryProgress(
    kind=WatchEventKind.UNSET, episode_total=0, episode_completed=0, episode_skipped=0, episode_started=0
)

_HEROES_ROUTE: Final[str] = "/heroes"


def select_watch_state() -> Select[tuple[str, int, int, int, int, datetime | None]]:
    """The six columns `EntryProgress` reads, projected once.

    Exported beside `WATCH_STATE` because two services read this view - the page below, and the watch
    log's own derived read - and a projection spelled out twice is a projection that can drift by one
    column without either caller noticing.
    """
    return select(
        WATCH_STATE.c.kind,
        WATCH_STATE.c.episode_total,
        WATCH_STATE.c.episode_completed,
        WATCH_STATE.c.episode_skipped,
        WATCH_STATE.c.episode_started,
        WATCH_STATE.c.as_of,
    )


async def list_entries(
    session: AsyncSession,
    settings: Settings,
    category_slug: str,
    *,
    limit: int = MAX_ENTRIES_PAGE_SIZE,
    offset: int = 0,
    jellyfin: JellyfinClient | None = None,
) -> list[CuratedEntryRead]:
    """One page of a category's projection, in the sheet's own order.

    Raises `CategoryNotFoundError` when no workbook answers to the id. Answers `[]` when one does but has
    never been ingested: tracked-but-not-available-here is a state, not an error (CLAUDE.md section 18.2).
    """
    # The library on disk is the authority for what a category *is*, so the 404 is the workbook's, not
    # the projection's - and it costs no query.
    await asyncio.to_thread(discovery.resolve, settings.library_dir, category_slug)
    return await read_entries(
        session, settings, await _page(session, category_slug, limit=limit, offset=offset), jellyfin=jellyfin
    )


async def read_entries(
    session: AsyncSession,
    settings: Settings,
    entries: Sequence[CuratedEntry],
    *,
    jellyfin: JellyfinClient | None = None,
) -> list[CuratedEntryRead]:
    """The wire shape for a page of already-loaded entries: one progress query and one poster query.

    Shared with the review queue (T30), which selects a different page of the same table and must not
    grow a second copy of the progress join or the poster stat. Every entry must already carry its
    `title` relationship - see this module's docstring.
    """
    if not entries:
        return []
    progress = await _progress_for(session, [entry.id for entry in entries])
    posters = await _posters_for(session, settings.heroes_dir, {entry.title_id for entry in entries if entry.title_id})
    slugs = await _slugs_for(session, {entry.category_id for entry in entries})
    availability = await availability_for(session, jellyfin, entries)
    return [
        _read(
            entry,
            slugs[entry.category_id],
            progress.get(entry.id, UNSET_PROGRESS),
            posters,
            availability.entries[entry.id],
        )
        for entry in entries
    ]


async def _page(session: AsyncSession, slug: str, *, limit: int, offset: int) -> Sequence[CuratedEntry]:
    """The live entries of one category, in curated order, with the one relationship the model reads."""
    statement = (
        select(CuratedEntry)
        .join(Category, Category.id == CuratedEntry.category_id)
        .where(Category.slug == slug, CuratedEntry.removed_at.is_(None))
        # `CuratedEntryRead` reads exactly one relationship, and this is it. `category` and `items` are
        # never touched, so they are never loaded.
        .options(selectinload(CuratedEntry.title))
        .order_by(CuratedEntry.position)
        .limit(limit)
        .offset(offset)
    )
    return (await session.execute(statement)).scalars().all()


async def _progress_for(session: AsyncSession, entry_ids: Sequence[UUID]) -> dict[UUID, EntryProgress]:
    """Every entry on the page's derived state, in one query. One per entry would be the N+1 this avoids."""
    # The key is added rather than listed, so the six columns the model reads stay in one place.
    statement = (
        select_watch_state()
        .add_columns(WATCH_STATE.c.curated_entry_id)
        .where(WATCH_STATE.c.curated_entry_id.in_(entry_ids))
    )
    rows = (await session.execute(statement)).all()
    return {row.curated_entry_id: EntryProgress.model_validate(row) for row in rows}


async def _slugs_for(session: AsyncSession, category_ids: set[UUID]) -> dict[UUID, str]:
    """The workbook id behind each entry on the page, in one query (R82).

    Read as a column rather than through `CuratedEntry.category`: that relationship is
    `lazy="raise_on_sql"` and is deliberately never loaded, and a page spanning nineteen categories -
    which the review queue really does - would otherwise be nineteen loads or one more `selectinload`
    on every caller of `read_entries`. One `IN` over the distinct ids is neither.
    """
    statement = select(Category.id, Category.slug).where(Category.id.in_(category_ids))
    return {row.id: row.slug for row in (await session.execute(statement)).all()}


async def _posters_for(session: AsyncSession, heroes_dir: Path, title_ids: set[UUID]) -> dict[UUID, str]:
    """The cached primary poster of each title on the page, as the URL `/heroes` serves it."""
    if not title_ids:
        return {}
    statement = select(Artwork.title_id, Artwork.local_path).where(
        Artwork.title_id.in_(title_ids),
        Artwork.kind == ArtworkKind.POSTER,
        Artwork.is_primary.is_(True),
        # A row whose bytes were never cached points at nothing, so it is not a poster this can serve.
        Artwork.local_path.is_not(None),
    )
    cached = {row.title_id: row.local_path for row in (await session.execute(statement)).all()}
    if not cached:
        return {}
    return await asyncio.to_thread(_poster_urls, heroes_dir, cached)


def _poster_urls(heroes_dir: Path, cached: Mapping[UUID, str]) -> dict[UUID, str]:
    """Blocking: stats each file. `?v=` is the cache-buster `CategorySummary.hero_url` already needs."""
    root = heroes_dir.resolve()
    urls: dict[UUID, str] = {}
    for title_id, local_path in cached.items():
        found = (root / local_path).resolve()
        # A stored path that has left the directory is not this app's to serve, whatever is at the end of it.
        if not found.is_relative_to(root):
            continue
        try:
            status = found.stat()
        except OSError:
            # The file the row points at is gone - deleted by the owner, or moved aside by a pick being
            # written right now. One stat answers that and the stamp together.
            continue
        if not S_ISREG(status.st_mode):
            continue
        urls[title_id] = f"{_HEROES_ROUTE}/{local_path}?v={status.st_mtime_ns}"
    return urls


def _read(
    entry: CuratedEntry,
    category_slug: str,
    progress: EntryProgress,
    posters: Mapping[UUID, str],
    availability: EntryAvailability = NOT_IN_LIBRARY,
) -> CuratedEntryRead:
    """The wire shape. Listed by hand so every attribute that crosses the boundary is visible at one site."""
    return CuratedEntryRead.model_validate(
        {
            "id": entry.id,
            "category_slug": category_slug,
            "position": entry.position,
            "sheet_row": entry.sheet_row,
            "unit_kind": entry.unit_kind,
            "order_type": entry.order_type,
            "order_label": entry.order_label,
            "span_start": entry.span_start,
            "span_end": entry.span_end,
            "resolution_state": entry.resolution_state,
            "resolution_confidence": entry.resolution_confidence,
            "resolution_note": entry.resolution_note,
            "raw_title": entry.raw_title,
            "raw_unit": entry.raw_unit,
            "raw_release": entry.raw_release,
            # The validation alias: the column is `raw_cells`, the wire field is `cells`.
            "raw_cells": entry.raw_cells,
            "title": _title(entry.title, posters),
            "progress": progress,
            "availability": availability.availability,
            "jellyfin_item_id": availability.jellyfin_item_id,
        }
    )


def _title(title: Title | None, posters: Mapping[UUID, str]) -> TitleRead | None:
    """`poster_url` is not a column, so it is set after validation - the shape `Catalog._read_live_lock` uses."""
    if title is None:
        return None
    read = TitleRead.model_validate(title)
    poster = posters.get(title.id)
    return read if poster is None else read.model_copy(update={"poster_url": poster})
